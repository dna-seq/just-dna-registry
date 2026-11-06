"""The ClinVar-tier facet (0.28, M7): `?clin_sig=<tier>` keeps modules whose current version has
variants in that tier, from format 0.8's `stats.clin_sig_variant_counts` (RM300). Upstream spells
*not counted* (a manifest compiled before 0.8) as an empty map, and that is not zero of each: such a
module never matches, and its card says `null`, not zeros."""

from conftest import _make_manifest
from fastapi.testclient import TestClient
from just_dna_format.manifest import VALID_CLIN_SIG

from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.services.ingest import ingest_manifest


def _counts(**nonzero: int) -> dict[str, int]:
    """Upstream's shape: every tier, zeros included."""
    return {tier: nonzero.get(tier, 0) for tier in sorted(VALID_CLIN_SIG)}


def _seed(repo: Repository, name: str, version: str, counts: dict[str, int]) -> None:
    manifest, _ = _make_manifest("ns1", name, version, genes=["G"], categories=["x"])
    manifest.stats.clin_sig_variant_counts = counts
    ingest_manifest(repo, manifest, created_at=f"2026-01-0{version[-1]}T00:00:00Z")


def _names(client: TestClient, tier: str) -> list[str]:
    resp = client.get("/api/v1/modules", params={"clin_sig": tier})
    assert resp.status_code == 200, resp.text
    return sorted(i["name"] for i in resp.json()["items"])


def test_the_facet_keeps_modules_with_variants_in_the_tier(client: TestClient, repo: Repository) -> None:
    assert len(VALID_CLIN_SIG) >= 5  # a floor: an emptied upstream vocabulary must not pass
    _seed(repo, "brca", "1.0.0", _counts(pathogenic=3, benign=1))
    _seed(repo, "cardio", "1.0.0", _counts(likely_pathogenic=2))
    _seed(repo, "pgx", "1.0.0", _counts())          # counted on 0.8, no variants in any tier
    _seed(repo, "legacy", "1.0.0", {})              # compiled before 0.8: not counted
    assert _names(client, "pathogenic") == ["brca"]
    assert _names(client, "likely_pathogenic") == ["cardio"]
    assert _names(client, "uncertain_significance") == []

    cards = {i["name"]: i["stats"]["clin_sig_variant_counts"] for i in client.get("/api/v1/modules").json()["items"]}
    assert cards["legacy"] is None and cards["pgx"] == _counts()
    assert client.get("/api/v1/modules/ns1/legacy").json()["stats"]["clin_sig_variant_counts"] is None
    assert client.get("/api/v1/modules/ns1/brca").json()["stats"]["clin_sig_variant_counts"]["pathogenic"] == 3


def test_the_facet_reads_the_current_version_only(client: TestClient, repo: Repository) -> None:
    _seed(repo, "brca", "1.0.0", _counts(pathogenic=3))
    _seed(repo, "brca", "1.0.1", _counts(benign=2))  # the pathogenic rows were dropped
    assert _names(client, "pathogenic") == [] and _names(client, "benign") == ["brca"]


def test_an_unknown_tier_is_refused_naming_the_tiers(client: TestClient) -> None:
    resp = client.get("/api/v1/modules", params={"clin_sig": "pathogenicc"})
    assert resp.status_code == 422 and resp.json()["detail"]["error"] == "invalid_clin_sig"
    assert "pathogenic" in resp.json()["detail"]["errors"][0]


def test_an_existing_catalog_is_backfilled_at_start(tmp_path) -> None:
    conn = connect(tmp_path / "r.db")
    init_db(conn)
    repo = Repository(conn)
    _seed(repo, "brca", "1.0.0", _counts(pathogenic=3))
    conn.execute("DELETE FROM version_clin_sig")  # a catalog written before 0.28
    conn.commit()
    assert repo.search_modules(clin_sig="pathogenic")[1] == 0
    init_db(conn)
    assert repo.search_modules(clin_sig="pathogenic")[1] == 1
