"""Read/catalog + download endpoint contract tests (SPEC §8.1–§8.5, §13)."""

import sqlite3
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from just_dna_format.integrity import IntegrityError, verify_manifest
from just_dna_format.manifest import ModuleManifest

from just_dna_registry.services.publish import ingest_manifest


@pytest.fixture
def seeded(seed: Callable[..., ModuleManifest]) -> None:
    seed("just-dna-seq", "longevity_variants_2026", "1.0.0",
         genes=["CGAS", "TERT"], categories=["cGAS-STING pathway"],
         created_at="2025-01-01T00:00:00Z")
    seed("just-dna-seq", "longevity_variants_2026", "2.0.0",
         genes=["CGAS", "TERT", "SIRT1"], categories=["cGAS-STING pathway"],
         created_at="2025-06-01T00:00:00Z")
    seed("just-dna-seq", "coronary", "1.0.0",
         genes=["LPA"], categories=["cardio"], created_at="2025-03-01T00:00:00Z")


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"]  # reported from package metadata, surfaces the live build
    assert body["storage"] in {"local", "hf"}
    assert body["mode"] in {"prod", "test"}
    assert body["uptime_seconds"] >= 0
    assert body["enrichment"] == {"active": 0, "queued": 0, "limit": 1}


def test_health_counts_the_catalog(client: TestClient, seed: Callable[..., ModuleManifest]) -> None:
    """S4: the numbers an operator would otherwise open a shell to get.

    Asserted as a *delta* across a publish rather than against fixed totals, so it states the
    relationship instead of hardcoding whatever a fixture happens to hold.
    """
    before = client.get("/health").json()["catalog"]

    seed("just-dna-seq", "cardio_risk", "1.0.0", genes=["LPA"], categories=["cardio"],
         created_at="2025-03-01T00:00:00Z")
    after = client.get("/health").json()["catalog"]

    assert after["modules"] == before["modules"] + 1
    assert after["versions"] == before["versions"] + 1
    assert after["yanked"] == before["yanked"], "a fresh publish is not yanked"


def test_health_degrades_instead_of_failing_when_the_catalog_is_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Liveness that 500s pulls a process that is still serving, and hides the reason with it.

    Injected on the repository rather than mocked at the route, so the real handler path — the one
    that chooses between reporting and propagating — is what runs.
    """
    def boom() -> dict:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(client.app.state.repo, "catalog_counts", boom)

    resp = client.get("/health")
    assert resp.status_code == 200, "a sick catalog is a degraded report, not a dead endpoint"
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["catalog"] is None
    assert "OperationalError" in body["degraded_reason"]
    # The half that still works is still reported — that is what degrading is for.
    assert body["mode"] in {"prod", "test"} and body["version"]


def test_list_empty(client: TestClient) -> None:
    body = client.get("/api/v1/modules").json()
    assert body == {"items": [], "total": 0, "page": 1, "per_page": 20}


def test_list_returns_cards(client: TestClient, seeded: None) -> None:
    body = client.get("/api/v1/modules").json()
    assert body["total"] == 2
    names = {item["name"] for item in body["items"]}
    assert names == {"longevity_variants_2026", "coronary"}
    longevity = next(i for i in body["items"] if i["name"] == "longevity_variants_2026")
    assert longevity["latest_version"] == "2.0.0"  # highest non-yanked SemVer
    assert longevity["stats"]["gene_count"] == 3
    assert len(longevity["stats"]["genes"]) <= 3  # card genes truncated


def test_search_by_gene_facet(client: TestClient, seeded: None) -> None:
    body = client.get("/api/v1/modules", params={"gene": "LPA"}).json()
    assert [i["name"] for i in body["items"]] == ["coronary"]


def test_search_by_category_and_q(client: TestClient, seeded: None) -> None:
    assert client.get("/api/v1/modules", params={"category": "cardio"}).json()["total"] == 1
    assert client.get("/api/v1/modules", params={"q": "coronary"}).json()["total"] == 1
    assert client.get("/api/v1/modules", params={"q": "nomatch"}).json()["total"] == 0


def test_sort_recent(client: TestClient, seeded: None) -> None:
    items = client.get("/api/v1/modules", params={"sort": "recent"}).json()["items"]
    # longevity's latest ingest (2025-06) is newer than coronary (2025-03).
    assert items[0]["name"] == "longevity_variants_2026"


def test_detail_and_404(client: TestClient, seeded: None) -> None:
    assert client.get("/api/v1/modules/just-dna-seq/missing").status_code == 404
    detail = client.get("/api/v1/modules/just-dna-seq/longevity_variants_2026").json()
    assert {v["version"] for v in detail["versions"]} == {"1.0.0", "2.0.0"}
    assert detail["latest_manifest"]["identity"]["version"] == "2.0.0"
    assert detail["stats"]["gene_count"] == 3  # full/from latest manifest


def test_detail_returns_full_genes_but_card_truncates(
    client: TestClient, seed: Callable[..., ModuleManifest]
) -> None:
    seed("just-dna-seq", "big_module", "1.0.0", genes=["A", "B", "C", "D", "E"],
         categories=["x"], created_at="2025-01-01T00:00:00Z")
    card = next(i for i in client.get("/api/v1/modules").json()["items"] if i["name"] == "big_module")
    assert len(card["stats"]["genes"]) == 3  # card truncates
    detail = client.get("/api/v1/modules/just-dna-seq/big_module").json()
    assert detail["stats"]["genes"] == ["A", "B", "C", "D", "E"]  # detail is full (SPEC §8.3)
    assert detail["stats"]["gene_count"] == 5


def test_versions_endpoint(client: TestClient, seeded: None) -> None:
    body = client.get("/api/v1/modules/just-dna-seq/longevity_variants_2026/versions").json()
    assert body["total"] == 2
    assert body["items"][0]["manifest_url"].endswith("/manifest")


def test_manifest_fetch_and_404(client: TestClient, seeded: None) -> None:
    ok = client.get("/api/v1/modules/just-dna-seq/coronary/versions/1.0.0/manifest")
    assert ok.status_code == 200
    assert ok.json()["compilation"]["compiled_by"] == "marketplace-server"
    missing = client.get("/api/v1/modules/just-dna-seq/coronary/versions/9.9.9/manifest")
    assert missing.status_code == 404


def test_download_and_integrity_roundtrip(
    client: TestClient, seeded: None, tmp_path
) -> None:
    base = "/api/v1/modules/just-dna-seq/coronary/versions/1.0.0"
    listing = client.get(f"{base}/download").json()
    assert {f["name"] for f in listing["files"]} == {
        "weights.parquet", "annotations.parquet", "studies.parquet"
    }
    # Download each file, reconstruct the module dir, and verify against the manifest.
    module_dir = tmp_path / "install"
    module_dir.mkdir()
    for f in listing["files"]:
        data = client.get(f"{base}/files/{f['name']}").content
        (module_dir / f["name"]).write_bytes(data)
    manifest = ModuleManifest.model_validate(
        client.get(f"{base}/manifest").json()
    )
    verify_manifest(module_dir, manifest)  # passes on untampered install

    # Tamper one byte -> verification fails.
    (module_dir / "weights.parquet").write_bytes(b"corrupted")
    with pytest.raises(IntegrityError):
        verify_manifest(module_dir, manifest)


def test_download_increments_counter(client: TestClient, seeded: None) -> None:
    base = "/api/v1/modules/just-dna-seq/coronary/versions/1.0.0/download"
    client.get(base)
    client.get(base)
    card = next(
        i for i in client.get("/api/v1/modules").json()["items"] if i["name"] == "coronary"
    )
    assert card["downloads"] == 2


def _reindex_with_compilation(
    app, manifest: ModuleManifest, version: str, *, content_signature: str | None = None, **fields: object
) -> ModuleManifest:
    """Re-ingest `manifest` at `version` with `compilation` overridden. Returns what was stored.

    The `seed` fixture builds one honest default compilation, and S14 is about fields it does not
    set — a fact signature, a source list, and the pre-0.6 `resolution_subjects: 0` that the era gate
    exists to swallow. Built here rather than widened into the fixture: every other test wants the
    default, and a fixture that took six compilation kwargs would obscure that.
    """
    payload = manifest.model_dump(mode="json")
    payload["identity"] = payload["identity"] | {
        "version": version,
        "canonical_id": f"{manifest.identity.namespace}/{manifest.identity.name}@{version}",
    }
    payload["compilation"] = payload["compilation"] | fields
    payload["content_signature"] = content_signature or f"sha256:{version.replace('.', ''):0>64}"
    stored = ModuleManifest.model_validate(payload)
    ingest_manifest(app.state.repo, stored, created_at=f"2025-0{version[0]}-01T00:00:00Z")
    return stored


#: One authored dataset, published twice. Shared deliberately: it is what makes the fact signature
#: the *only* thing that moved between the two versions below.
_SHARED_CONTENT = "sha256:" + "de" * 32


def test_a_version_row_carries_both_identities_and_the_fact_signature(
    client: TestClient, app, seed: Callable[..., ModuleManifest]
) -> None:
    """S14: the version list is the only cross-version endpoint, so it has to answer *what moved*.

    Through 0.18 it could not. `resolution.signature` was `null` on every row while the same field was
    populated on the module card and in each manifest, and there was no `content_signature` at all —
    so "did the authored data move between 1.0.0 and 2.0.0" cost one manifest fetch per version from
    the endpoint that had already walked those very rows.

    Asserted as set equality between the list and the manifests it lists, per version and across the
    whole chain, rather than as "the field is not null": the failure this closes was a *projection*
    disagreeing with the document it projects, which an existence check cannot see.
    """
    base = seed("just-dna-seq", "chain", "1.0.0", genes=["CGAS"], categories=["longevity"],
                created_at="2025-01-01T00:00:00Z")
    # One authored dataset resolved twice against sources that revised an answer: `content_signature`
    # holds still, the fact signature moves. That is the exact case the reporter's tool exists to
    # detect, and the case a digest comparison cannot distinguish from a no-op recompile.
    stored = {
        "2.0.0": _reindex_with_compilation(
            app, base, "2.0.0",
            content_signature=_SHARED_CONTENT,
            resolution_signature="sha256:" + "a1" * 32,
            resolution_sources=["Ensembl", "gnomAD"],
            resolution_subjects=990,
            compiler_version="0.6.1",
        ),
        "3.0.0": _reindex_with_compilation(
            app, base, "3.0.0",
            content_signature=_SHARED_CONTENT,
            resolution_signature="sha256:" + "b2" * 32,
            resolution_sources=["Ensembl", "gnomAD"],
            resolution_subjects=990,
            compiler_version="0.6.1",
        ),
    }

    rows = {
        r["version"]: r
        for r in client.get("/api/v1/modules/just-dna-seq/chain/versions").json()["items"]
    }
    for version, manifest in stored.items():
        row = rows[version]
        assert row["resolution"]["signature"] == manifest.compilation.resolution_signature
        assert row["resolution"]["sources"] == list(manifest.compilation.resolution_sources)
        assert row["content_signature"] == manifest.content_signature
        assert row["artifact_digest"] == manifest.artifact.digest

    # The whole point: both questions answerable from the one list call, and answering differently.
    assert rows["2.0.0"]["content_signature"] == rows["3.0.0"]["content_signature"]
    assert rows["2.0.0"]["resolution"]["signature"] != rows["3.0.0"]["resolution"]["signature"]


def test_the_row_reports_not_measured_where_the_pre_06_manifest_stores_a_default_zero(
    client: TestClient, app, seed: Callable[..., ModuleManifest]
) -> None:
    """S14 (3), which is the half we did *not* change, and the reason is worth pinning.

    A 0.5-era manifest stores `resolution_subjects: 0` — pydantic's default on a field that compile
    never populated, not a count of zero. The row reports `null`, and the reporter read the
    difference as the projection contradicting the manifest and asked us to pass the `0` through.

    That would restore exactly the vacuity RM44/S31 added the counter to expose. The gate is applied
    once, in `db.facets._counters`, and shared by both projections — so the card and the row agree
    with each other and only the *raw manifest* differs, which is the one surface that has to keep
    reporting its own stored bytes. Asserted here across all three surfaces at once, because the
    claim under test is about their relationship rather than any one value.
    """
    base = seed("just-dna-seq", "legacy", "1.0.0", genes=["TERT"], categories=["longevity"],
                created_at="2025-01-01T00:00:00Z")
    _reindex_with_compilation(
        app, base, "2.0.0",
        compiler_version="0.5.4",
        resolution_signature="sha256:" + "c3" * 32,
        resolution_subjects=0,
    )

    row = next(
        r for r in client.get("/api/v1/modules/just-dna-seq/legacy/versions").json()["items"]
        if r["version"] == "2.0.0"
    )
    manifest = client.get("/api/v1/modules/just-dna-seq/legacy/versions/2.0.0/manifest").json()
    card = client.get("/api/v1/modules/just-dna-seq/legacy").json()

    assert manifest["compilation"]["resolution_subjects"] == 0, "the stored byte is untouched"
    assert row["resolution"]["resolution_subjects"] is None, "not measured, and never a count"
    assert card["resolution"]["resolution_subjects"] is None, "the two projections agree"
    # The fact signature is *not* gated — it has been `str | None` since 0.5, so an absent one is
    # already `None` and there is no default that could be mistaken for a measurement.
    assert row["resolution"]["signature"] == "sha256:" + "c3" * 32
