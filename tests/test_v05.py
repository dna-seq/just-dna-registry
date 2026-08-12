"""0.5.0 accommodation of just-dna-format 0.2.0: structured provenance, gene-panel + icon_set +
ClinVar-stat surfacing, module logo (served, in card, amend without version bump), and optional
Ed25519 signing (publish signs, /pubkey serves, client verifies a pinned key)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from just_dna_format.integrity import IntegrityError, verify_manifest
from just_dna_format.manifest import ModuleManifest
from just_dna_format.signing import generate_private_key_pem, public_key_b64_from_pem

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository

_YAML = """\
schema_version: "1.0"
module:
  name: cardio
  title: Cardio
  description: d
  report_title: R
  icon: heartbeat
  icon_set: awesome
  color: "#21ba45"
defaults:
  curator: t
  method: m
genome_build: GRCh38
panel:
  source: clinvar
  reference: "2026-06"
  genes: [BRCA1, BRCA2]
  significance: [pathogenic, likely_pathogenic]
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,negatives,gene,category,clinvar,pathogenic,benign\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,a trade-off,CYP2C19,cyp2c19,true,true,false\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,[PMID: 29165669],T,0.05,E,U\n"
_PROVENANCE = json.dumps(
    {"generator": "agent-x", "model": "claude", "agent_version": "1.0",
     "items": [{"variant_key": "rs4244285", "rationale": "curated", "human_reviewed": True}]}
).encode()
_LOGO = b"\x89PNG\r\n\x1a\n cardio-logo"
_BASE = "/api/v1/modules/just-dna-seq/cardio/versions/1.0.0"


def _files(*, logo: bool = True, provenance: bool = True, readme: bytes | None = None,
           readme_name: str = "README.md") -> list:
    files = [
        ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
        ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
        ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
    ]
    if provenance:
        files.append(("files", ("provenance.json", _PROVENANCE, "application/json")))
    if logo:
        files.append(("files", ("logo.png", _LOGO, "image/png")))
    if readme is not None:
        files.append(("files", (readme_name, readme, "text/markdown")))
    return files


def _publish(client: TestClient, key: str, **kw) -> dict:
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "1.0.0"},
        files=_files(**kw),
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _signing_app(tmp_path: Path):
    """A fresh app configured to sign, plus a usable owner key. Returns (app, api_key, pem)."""
    pem = generate_private_key_pem()
    key_path = tmp_path / "signing_key.pem"
    key_path.write_bytes(pem)
    settings = Settings(
        db_path=tmp_path / "m.db",
        storage_backend="local",
        local_storage_dir=tmp_path / "artifacts",
        signing_key=key_path,
    )
    app = create_app(settings)
    repo: Repository = app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    return app, "mk_live_testkey", pem


# ── Provenance / panel / icon_set / clinvar / logo surfacing ────────────────────


def test_publish_carries_provenance_panel_and_stats(client: TestClient, api_key: str) -> None:
    manifest = _publish(client, api_key)
    assert manifest["provenance"]["item_count"] == 1
    assert manifest["provenance"]["generator"] == "agent-x"
    assert manifest["panel"]["source"] == "clinvar"
    assert manifest["panel"]["genes"] == ["BRCA1", "BRCA2"]
    assert manifest["display"]["icon_set"] == "awesome"
    assert manifest["stats"]["clinvar_count"] == 1
    assert manifest["stats"]["pathogenic_count"] == 1
    assert manifest["logo"]["name"] == "logo.png"


def test_provenance_and_logo_are_served(client: TestClient, api_key: str) -> None:
    _publish(client, api_key)
    assert client.get(f"{_BASE}/files/provenance.json").content == _PROVENANCE
    assert client.get(f"{_BASE}/files/logo.png").content == _LOGO


def test_detail_card_surfaces_logo_and_stats(client: TestClient, api_key: str) -> None:
    _publish(client, api_key)
    card = client.get("/api/v1/modules/just-dna-seq/cardio").json()
    assert card["icon_set"] == "awesome"
    assert card["logo_url"] == f"{_BASE}/files/logo.png"
    assert card["stats"]["clinvar_count"] == 1
    assert card["stats"]["pathogenic_count"] == 1


def test_tarball_includes_logo(client: TestClient, api_key: str) -> None:
    import io
    import tarfile

    _publish(client, api_key)
    resp = client.get(f"{_BASE}/download", params={"format": "tarball"})
    with tarfile.open(fileobj=io.BytesIO(resp.content)) as tar:
        assert "logo.png" in tar.getnames()


# ── Logo amendment (out of digest, no version bump) ─────────────────────────────


def test_amend_logo_keeps_digest_and_version(client: TestClient, api_key: str) -> None:
    published = _publish(client, api_key)
    digest_before = published["artifact"]["digest"]
    new_logo = b"\xff\xd8\xff new-jpeg-logo"  # jpg bytes

    resp = client.post(
        f"{_BASE}/logo",
        files={"logo": ("logo.jpg", new_logo, "image/jpeg")},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["logo"]["name"] == "logo.jpg"

    manifest = client.get(f"{_BASE}/manifest").json()
    assert manifest["logo"]["name"] == "logo.jpg"
    assert manifest["artifact"]["digest"] == digest_before  # content identity unchanged
    assert client.get(f"{_BASE}/files/logo.jpg").content == new_logo

    # Still exactly one version — no bump.
    versions = client.get("/api/v1/modules/just-dna-seq/cardio/versions").json()
    assert [v["version"] for v in versions["items"]] == ["1.0.0"]


_README = (
    "# Cardio\n\nThese findings are **candidates**. One association was *not significant*.\n"
)


def test_publish_projects_the_readme_onto_the_card(client: TestClient, api_key: str) -> None:
    """S5: `readme` was declared, stored and returned, and nothing ever wrote it.

    The end-to-end claim, not the column: a `README.md` in the spec has to reach the field a catalog
    client actually renders.
    """
    _publish(client, api_key, readme=_README.encode())
    detail = client.get("/api/v1/modules/just-dna-seq/cardio").json()
    assert detail["readme"] == _README


def test_publish_without_a_readme_leaves_the_card_empty_not_broken(
    client: TestClient, api_key: str
) -> None:
    _publish(client, api_key)
    assert client.get("/api/v1/modules/just-dna-seq/cardio").json()["readme"] == ""


def test_a_republish_without_a_readme_does_not_blank_the_existing_one(
    client: TestClient, api_key: str
) -> None:
    """`None` means "leave it", not "clear it" — the difference between preserving a card and wiping it.

    This is the case a future reindex will hit: a caller that knows nothing about readmes must not
    silently erase every module's prose just by re-projecting manifests.
    """
    _publish(client, api_key, readme=_README.encode())
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "2.0.0"},
        files=_files(readme=None),
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    assert client.get("/api/v1/modules/just-dna-seq/cardio").json()["readme"] == _README


def test_amend_readme_keeps_digest_and_version(client: TestClient, api_key: str) -> None:
    """The reason this endpoint exists: prose is fixable on an immutable registry.

    A caveat phrased badly must not cost a version number and a `content_hash` that `yank` would
    not release — so the amend is asserted to move neither.
    """
    published = _publish(client, api_key, readme=_README.encode())
    digest_before = published["artifact"]["digest"]
    fixed = "# Cardio\n\nCandidate findings only. The PMID 29165669 association was NOT significant.\n"

    resp = client.post(
        f"{_BASE}/readme",
        files={"readme": ("README.md", fixed.encode(), "text/markdown")},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["readme"] == fixed

    assert client.get("/api/v1/modules/just-dna-seq/cardio").json()["readme"] == fixed
    manifest = client.get(f"{_BASE}/manifest").json()
    assert manifest["artifact"]["digest"] == digest_before  # content identity unchanged
    versions = client.get("/api/v1/modules/just-dna-seq/cardio/versions").json()
    assert [v["version"] for v in versions["items"]] == ["1.0.0"]  # no bump


def test_amend_readme_requires_a_token(client: TestClient, api_key: str) -> None:
    _publish(client, api_key)
    resp = client.post(f"{_BASE}/readme", files={"readme": ("README.md", b"x", "text/markdown")})
    assert resp.status_code == 401


def test_amend_readme_404s_on_an_unknown_version(client: TestClient, api_key: str) -> None:
    _publish(client, api_key)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions/9.9.9/readme",
        files={"readme": ("README.md", b"x", "text/markdown")},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404


def test_module_md_is_renamed_to_the_name_the_registry_reads(
    client: TestClient, api_key: str
) -> None:
    """`README.md` is the one name — and the corpus written against the old advice still publishes.

    `MODULE.md` is what this project's own docs promised for two releases and what
    `just-module-creator` still emits, so refusing it (or silently dropping the prose, which is what
    0.14 did) would charge an author for a rename we made after they wrote the file.
    """
    _publish(client, api_key, readme=b"# old convention\n", readme_name="MODULE.md")
    assert client.get("/api/v1/modules/just-dna-seq/cardio").json()["readme"] == "# old convention\n"


def test_readme_wins_when_both_names_arrive(client: TestClient, api_key: str) -> None:
    """The one case the rename must not act on: overwriting prose the author wrote with prose they
    did not is the most surprising thing this pass could do, so the legacy file is left alone."""
    files = _files(readme=_README.encode())
    files.append(("files", ("MODULE.md", b"# stale\n", "text/markdown")))
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "1.0.0"},
        files=files,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    assert client.get("/api/v1/modules/just-dna-seq/cardio").json()["readme"] == _README


def test_the_readme_reaches_the_card_but_not_a_downloader(client: TestClient, api_key: str) -> None:
    """The half of S5 that is upstream's, pinned so it cannot be lost.

    `/files/{path}` and the tarball are both built from what the **manifest** attests, and the
    manifest has no readme entry — the logo has one (`manifest.logo`), which is exactly why the logo
    is fetchable and this is not. So the prose reaches the catalog card and no further.

    When `just-dna-format` adds the field, this test is the one to change: it is asserting a
    limitation, not a desired property.
    """
    import io
    import tarfile

    _publish(client, api_key, readme=_README.encode())
    assert client.get("/api/v1/modules/just-dna-seq/cardio").json()["readme"] == _README

    assert client.get(f"{_BASE}/files/README.md").status_code == 404
    assert client.get(f"{_BASE}/files/logo.png").status_code == 200, "the logo IS in the manifest"

    resp = client.get(f"{_BASE}/download", params={"format": "tarball"})
    with tarfile.open(fileobj=io.BytesIO(resp.content)) as tar:
        names = set(tar.getnames())
    assert "README.md" not in names and "logo.png" in names


def test_amend_logo_rejects_bad_extension(client: TestClient, api_key: str) -> None:
    _publish(client, api_key)
    resp = client.post(
        f"{_BASE}/logo",
        files={"logo": ("logo.gif", b"GIF89a", "image/gif")},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422, resp.text


# ── Optional Ed25519 signing ────────────────────────────────────────────────────


def test_publish_signs_and_pubkey_matches(tmp_path: Path) -> None:
    app, key, pem = _signing_app(tmp_path)
    client = TestClient(app)
    manifest = _publish(client, key)
    assert manifest["signature"] is not None
    assert manifest["signature"]["algorithm"] == "ed25519"

    pub = client.get("/api/v1/pubkey").json()
    assert pub["public_key"] == public_key_b64_from_pem(pem)
    assert manifest["signature"]["public_key"] == pub["public_key"]

    versions = client.get("/api/v1/modules/just-dna-seq/cardio/versions").json()
    assert versions["items"][0]["signed"] is True


def test_pubkey_404_when_unsigned(client: TestClient) -> None:
    assert client.get("/api/v1/pubkey").status_code == 404


def _download_to(client: TestClient, dest: Path) -> ModuleManifest:
    """Fetch a version's files + manifest into `dest` (what the reference client does)."""
    dest.mkdir(parents=True, exist_ok=True)
    listing = client.get(f"{_BASE}/download").json()
    manifest = ModuleManifest.model_validate(client.get(f"{_BASE}/manifest").json())
    names = [f["name"] for f in listing["files"]]
    names += [e["name"] for e in client.get(f"{_BASE}/logs").json()["items"]]
    if manifest.logo is not None:
        names.append(manifest.logo.name)
    if manifest.provenance is not None and manifest.provenance.file:
        names.append(manifest.provenance.file)
    for rel in names:
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(client.get(f"{_BASE}/files/{rel}").content)
    return manifest


def test_served_signed_module_verifies_with_pinned_key(tmp_path: Path) -> None:
    app, key, pem = _signing_app(tmp_path)
    client = TestClient(app)
    _publish(client, key)

    good = client.get("/api/v1/pubkey").json()["public_key"]
    assert good == public_key_b64_from_pem(pem)
    bad = public_key_b64_from_pem(generate_private_key_pem())

    manifest = _download_to(client, tmp_path / "dl")
    # The served bytes + served pubkey verify together; a different pinned key is rejected.
    verify_manifest(
        tmp_path / "dl", manifest,
        check_logs=True, check_logo=True, check_provenance=True, public_key=good,
    )
    with pytest.raises(IntegrityError):
        verify_manifest(tmp_path / "dl", manifest, public_key=bad)


def test_amend_logo_preserves_signature(tmp_path: Path) -> None:
    app, key, pem = _signing_app(tmp_path)
    client = TestClient(app)
    published = _publish(client, key)
    sig_before = published["signature"]["signature"]

    resp = client.post(
        f"{_BASE}/logo",
        files={"logo": ("logo.jpg", b"\xff\xd8\xff jpeg", "image/jpeg")},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200, resp.text
    manifest = client.get(f"{_BASE}/manifest").json()
    # Signature is over artifact.digest, which the logo swap doesn't touch → still valid, unchanged.
    assert manifest["signature"]["signature"] == sig_before


# ── Spec layout: authored at the root, machine-written under `derived/` ────────


_SOURCES = "source,layer\nensembl,resolution\n"


def _validate(client: TestClient, key: str, files: list) -> dict:
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/validate",
        files=files,
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_subfoldered_spec_is_the_same_module_as_the_flat_one(
    client: TestClient, api_key: str
) -> None:
    """The point of the flatten: a `derived/` tree and a flat tree are one module, not two.

    Asserted on `content_signature`, which is what `409 duplicate_content` gates on — so if the
    flatten ever stopped happening, this module would silently become publishable twice under two
    different names. Set equality on the served file listing is the second half: the hoisted table
    has to land at the root the manifest names, not merely somewhere.
    """
    flat = _files() + [("files", ("sources.csv", _SOURCES.encode(), "text/csv"))]
    split = _files() + [("files", ("derived/sources.csv", _SOURCES.encode(), "text/csv"))]

    assert _validate(client, api_key, split)["valid"] is True
    assert (
        _validate(client, api_key, split)["content_signature"]
        == _validate(client, api_key, flat)["content_signature"]
    )

    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "1.0.0"},
        files=split,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    # The compiler reads one flat directory, so the hoisted table must be at the root by then.
    assert {e["name"] for e in resp.json()["inputs"]} == {
        "module_spec.yaml", "variants.csv", "studies.csv"
    }
    assert client.get(f"{_BASE}/files/sources.parquet").status_code == 200


def test_one_root_name_from_two_paths_is_refused(client: TestClient, api_key: str) -> None:
    """Only the author knows which copy is current, so this is a refusal and never a guess."""
    files = _files() + [
        ("files", ("sources.csv", _SOURCES.encode(), "text/csv")),
        ("files", ("derived/sources.csv", b"source,layer\nclinvar,clin_sig\n", "text/csv")),
    ]
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "1.0.0"},
        files=files,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "ambiguous_spec_layout"
    assert "`derived/sources.csv`" in detail["errors"][0] and "`sources.csv`" in detail["errors"][0]


def test_the_dry_run_reports_exactly_what_the_publish_rewrites(
    client: TestClient, api_key: str
) -> None:
    """A pre-flight has to predict the operation it precedes (the S6 lesson, applied to layout).

    Equality, not "non-empty": the two paths run the same normalization through `normalize_spec`,
    and the moment they diverge this test is the one that says so.
    """
    files = _files() + [
        ("files", ("MODULE.md", b"# prose\n", "text/markdown")),
        ("files", ("derived/sources.csv", _SOURCES.encode(), "text/csv")),
    ]
    predicted = _validate(client, api_key, files)["info"]
    assert any("MODULE.md" in line and "README.md" in line for line in predicted)
    assert any("derived/sources.csv" in line for line in predicted)

    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "1.0.0"},
        files=files,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    # The publish emits its notes into the eliot log, not the manifest, so the observable proof that
    # it did the same work is the outcome: prose on the card, table compiled from the root.
    assert client.get("/api/v1/modules/just-dna-seq/cardio").json()["readme"] == "# prose\n"
    assert client.get(f"{_BASE}/files/sources.parquet").status_code == 200


def test_a_logs_subtree_is_never_flattened(client: TestClient, api_key: str) -> None:
    """`logs/` is the one folder the manifest attests by path, so hoisting one would rename an
    attested file. A top-level `*.log` is equally discovered and equally left where it is."""
    files = _files() + [
        ("files", ("logs/reviewer.log", b"reviewed\n", "text/plain")),
        ("files", ("v1.log", b"agent run\n", "text/plain")),
    ]
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "1.0.0"},
        files=files,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    assert {e["name"] for e in resp.json()["logs"]} == {"logs/reviewer.log", "v1.log"}
    assert client.get(f"{_BASE}/files/logs/reviewer.log").content == b"reviewed\n"


def test_a_run_log_stays_out_of_the_content_identity(client: TestClient, api_key: str) -> None:
    """What a `just-module-creator` zip ships beside the spec: a 240 KB agent transcript.

    It is hashed and served — provenance a reader can check — but it moves neither `artifact.digest`
    nor `content_signature`, so re-publishing the same data with a different run log is still the
    same module and is still caught by the duplicate-content claim.
    """
    without = _publish(client, api_key)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/cardio/versions",
        data={"version": "1.0.1"},
        files=_files() + [("files", ("v2.log", b"a different run entirely\n", "text/plain"))],
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    with_log = resp.json()
    assert with_log["artifact"]["digest"] == without["artifact"]["digest"]
    assert with_log["content_signature"] == without["content_signature"]
    assert [e["name"] for e in with_log["logs"]] == ["v2.log"]
