"""Rate limiting — token buckets per caller × category (SPEC §7)."""

from pathlib import Path

from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.ratelimit import CATEGORIES, default_limiter

_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  title: Coronary
  description: d
  report_title: R
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _app(tmp_path: Path, **over):
    return create_app(Settings(db_path=tmp_path / "m.db", local_storage_dir=tmp_path / "a", **over))


def _preflight_client(tmp_path: Path, **over):
    """An authed client plus a valid spec upload, for the two authenticated pre-flight buckets."""
    empty = tmp_path / "no-cache"
    client = TestClient(
        _app(tmp_path, ensembl_cache=empty, clinvar_cache=empty, constraint_cache=empty, **over)
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    parts = [
        ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
        ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
        ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
    ]
    return client, parts, {"Authorization": "Bearer mk_live_testkey"}


def test_search_rate_limit_trips(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, rate_search_per_min=2))  # capacity 2, negligible refill
    assert client.get("/api/v1/modules").status_code == 200
    assert client.get("/api/v1/modules").status_code == 200
    r = client.get("/api/v1/modules")
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"


def test_rate_limit_can_be_disabled(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, rate_limit_enabled=False, rate_search_per_min=1))
    for _ in range(5):
        assert client.get("/api/v1/modules").status_code == 200


# ── 0.11: the pre-flight buckets, and the guard against forgetting one ────────


def test_every_route_bucket_is_registered() -> None:
    """`RateLimiter.allow` returns True for a category nobody registered, so a route asking for a
    bucket that `default_limiter` does not build is *silently unlimited*. Pinning the exact set turns
    that failure mode from invisible into a red test."""
    assert set(default_limiter(Settings()).limits) == CATEGORIES


def test_validate_rate_limit_trips(tmp_path: Path) -> None:
    client, parts, auth = _preflight_client(tmp_path, rate_validate_per_hour=2)
    url = "/api/v1/modules/just-dna-seq/coronary/validate"
    assert client.post(url, files=parts, headers=auth).status_code == 200
    assert client.post(url, files=parts, headers=auth).status_code == 200
    r = client.post(url, files=parts, headers=auth)
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"


def test_enrich_rate_limit_is_tighter_than_validate(tmp_path: Path) -> None:
    """Sized by who bears the cost: validation spends our CPU, enrichment spends the deployment's
    standing with IP-throttled public APIs."""
    limits = default_limiter(Settings()).limits
    assert limits["enrich"][0] < limits["validate"][0]


def test_the_concurrency_gate_rejects_a_second_run(tmp_path: Path) -> None:
    """The token bucket caps one caller; the gate caps the process. Two callers each within their own
    bucket must still not both be enriching at once."""
    client, parts, auth = _preflight_client(tmp_path, enrich_max_concurrency=1)
    gate = client.app.state.enrichment_gate
    assert gate.try_acquire()  # stand in for a run already in flight
    r = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check", params={"offline": True},
        files=parts, headers=auth,
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "enrichment_busy"
    assert r.headers["Retry-After"] == "60"
    gate.release()
