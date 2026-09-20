"""Rate limiting — token buckets per caller × category (SPEC §7)."""

import math
from pathlib import Path

import pytest
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
    # The wait is the bucket's own: one token back at 2/min is 30s, not the flat 60 every `429`
    # said through 0.25.2. Computed from the settings the app was built with, never a literal.
    settings = client.app.state.settings
    assert r.headers["Retry-After"] == str(math.ceil(60 / settings.rate_search_per_min))
    assert r.headers["X-RateLimit-Bucket"] == "search"


def test_rate_limit_can_be_disabled(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, rate_limit_enabled=False, rate_search_per_min=1))
    for _ in range(5):
        assert client.get("/api/v1/modules").status_code == 200


# ── 0.11: the pre-flight buckets, and the guard against forgetting one ────────


def _buckets_routes_ask_for(tmp_path: Path, mode: str) -> set[str]:
    """Every category some route's `rate_limit(...)` dependency names, read off the app itself."""
    app = _app(tmp_path, mode=mode)
    asked: set[str] = set()
    for route in _walk_routes(app.routes):
        dependant = getattr(route, "dependant", None)
        for dep in getattr(dependant, "dependencies", []):
            category = getattr(dep.call, "rate_category", None)
            if category is not None:
                asked.add(category)
    return asked


def _walk_routes(routes):
    """FastAPI ≥ 0.141 includes a router lazily as one `_IncludedRouter` entry rather than
    flattening its routes onto the app, so a flat scan of `app.routes` sees seven `APIRoute`s and
    none of the API — which is what the floor in the test below caught on the first run."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _walk_routes(inner.routes)
        else:
            yield route


@pytest.mark.parametrize("mode", ["prod", "test"])
def test_every_route_bucket_is_registered(tmp_path: Path, mode: str) -> None:
    """`RateLimiter.allow` returns True for a category nobody registered, so a route asking for a
    bucket that `default_limiter` does not build is *silently unlimited*.

    Through 0.25.2 this compared `CATEGORIES` to `default_limiter`'s keys — two hand-kept sets that
    agreed with each other while `hints.py` asked for a `hint` bucket neither of them had, so the
    whole hint proxy shipped unlimited. The route side now comes from the app, which is the only
    place the question is actually asked. The floor keeps the walk honest: an attribute rename would
    otherwise empty `asked` and pass."""
    asked = _buckets_routes_ask_for(tmp_path, mode)
    assert len(asked) >= 5
    assert asked == CATEGORIES
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


def test_hint_rate_limit_trips(tmp_path: Path) -> None:
    """The bucket every hint route names has to exist, or the proxy is unlimited (it was, through
    0.25.2). Anonymous online is refused before any lookup runs, so nothing here reaches the
    network; the bucket dependency resolves ahead of that refusal, which is what makes the third
    call a `429` whatever the first two answered."""
    client = TestClient(_app(tmp_path, rate_hint_per_hour=2))
    url = "/api/v1/hint/gene"
    first = client.get(url, params={"symbol": "CYP2C19"})
    second = client.get(url, params={"symbol": "CYP2C19"})
    assert first.status_code == second.status_code != 429
    r = client.get(url, params={"symbol": "CYP2C19"})
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"


# ── S23: a refusal says which bucket and how long, and a busy gate spends nothing ────────────


def test_an_enrich_refusal_names_its_bucket_and_the_real_wait(tmp_path: Path) -> None:
    """S23's reporter retried `/check` at five and ten minutes on a `Retry-After: 60` and got `429`
    both times: the 5/h bucket refills one token per 720s. The header now carries that number, and
    the bucket name says which of the server's budgets it was — the body stays the bare string a
    client already compares against."""
    client, parts, auth = _preflight_client(tmp_path, rate_enrich_per_hour=2)
    url = "/api/v1/modules/just-dna-seq/coronary/check"
    for _ in range(2):
        assert client.post(url, params={"offline": True}, files=parts, headers=auth).status_code == 200
    r = client.post(url, params={"offline": True}, files=parts, headers=auth)
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"
    assert r.headers["X-RateLimit-Bucket"] == "enrich"
    settings = client.app.state.settings
    expected = math.ceil(3600 / settings.rate_enrich_per_hour)
    assert expected > 60  # the flat value would have been wrong here, which is the point
    assert int(r.headers["Retry-After"]) == expected


def test_a_busy_gate_refunds_the_enrich_token(tmp_path: Path) -> None:
    """The bucket is a route dependency, so it resolves before the handler reaches the gate; through
    0.25.2 a `503 enrichment_busy` therefore cost a token for a run that never happened. S23's
    batch was one run plus four busy refusals — five tokens, the whole hour. With capacity 1 the
    caller must still get through after the gate opens, and only *then* be out."""
    client, parts, auth = _preflight_client(tmp_path, rate_enrich_per_hour=1, enrich_max_concurrency=1)
    gate = client.app.state.enrichment_gate
    url = "/api/v1/modules/just-dna-seq/coronary/check"
    assert gate.try_acquire()
    busy = client.post(url, params={"offline": True}, files=parts, headers=auth)
    assert busy.status_code == 503 and busy.json()["detail"] == "enrichment_busy"
    gate.release()
    ran = client.post(url, params={"offline": True}, files=parts, headers=auth)
    assert ran.status_code == 200
    out = client.post(url, params={"offline": True}, files=parts, headers=auth)
    assert out.status_code == 429 and out.headers["X-RateLimit-Bucket"] == "enrich"


def test_a_refund_never_mints_credit(tmp_path: Path) -> None:
    """Refunding a bucket that was never charged, or one already full, leaves it at capacity."""
    from just_dna_registry.ratelimit import RateLimiter

    limiter = RateLimiter({"x": (2.0, 1e-9)})  # refills, but not within this test
    limiter.refund("who", "x")  # nothing charged yet: no entry, nothing to do
    assert limiter.take("who", "x").allowed and limiter.take("who", "x").allowed
    assert not limiter.take("who", "x").allowed
    limiter.refund("who", "x")
    limiter.refund("who", "x")
    limiter.refund("who", "x")  # bounded at capacity 2, not 3
    assert limiter.take("who", "x").allowed and limiter.take("who", "x").allowed
    assert not limiter.take("who", "x").allowed


def test_a_bucket_that_never_refills_sends_no_retry_after(tmp_path: Path) -> None:
    """`rate_search_per_min=0` is a bucket with no capacity and no refill — "closed", which an
    operator may well configure. The verdict says `inf` rather than dividing by zero (found by the
    unit test above, on its first version), and the route sends the bucket name with no
    `Retry-After`, because there is no honest number to put in one."""
    from just_dna_registry.ratelimit import RateLimiter

    verdict = RateLimiter({"x": (0.0, 0.0)}).take("who", "x")
    assert not verdict.allowed and verdict.retry_after == math.inf
    client = TestClient(_app(tmp_path, rate_search_per_min=0))
    r = client.get("/api/v1/modules")
    assert r.status_code == 429 and r.headers["X-RateLimit-Bucket"] == "search"
    assert "Retry-After" not in r.headers
