"""`/api/v1/hint/*` — the enricher's authoring lookups, proxied and metered.

What is ours to test is not the lookups (upstream's, and already covered there) but the three things
this layer adds: who may ask what, whether the answer leaks this server's filesystem, and whether the
meter charges the right upstream for the right shape of request.

The claim the whole release rests on gets its own test with the socket tripwire armed: a batch of
keys against a provisioned snapshot must charge **nothing** and reach **nothing**.
"""

import json

import pytest
from test_preflight_api import (  # noqa: F401 — the two autouse fixtures register for this module
    _AUTH,
    _app,
    no_network,
    pinned_environment,
)

from just_dna_registry import pacing
from just_dna_registry.services import hints as hint_service


def _real(lane: str):
    from just_dna_enricher.caches import LANES_BY_NAME

    return LANES_BY_NAME[lane].resolve()


_ENSEMBL = _real("ensembl")


def test_anonymous_callers_get_the_free_tier_and_nothing_else(tmp_path) -> None:
    """The offline tier is the product; the online tier is the one that spends our IP's standing.

    An anonymous online hint would let one caller throttle every publisher on the box against a gnomAD
    limit nobody can buy out of, and the ledger needs a stable identity for its cooldown to mean
    anything — a shared NAT makes the IP branch worthless as a key.
    """
    client = _app(tmp_path)

    free = client.get("/api/v1/hint/variant", params={"rsid": "rs4244285", "offline": True})
    assert free.status_code == 200, free.text
    assert free.json()["cost"]["charged"] == {}

    paid = client.get("/api/v1/hint/variant", params={"rsid": "rs4244285", "offline": False})
    assert paid.status_code == 401
    assert paid.json()["detail"]["error"] == "online_hint_needs_a_token"


def test_gnomad_is_behind_its_own_switch_and_off_by_default(tmp_path) -> None:
    """It is the same allowance `/check?frequencies=true` needs to gate a publish."""
    client = _app(tmp_path)
    resp = client.get(
        "/api/v1/hint/variant",
        params={"rsid": "rs4244285", "offline": False, "frequencies": True},
        headers=_AUTH,
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "gnomad_not_enabled"
    assert "no key purchasable at any price" in resp.json()["detail"]["errors"][0]


def test_a_hint_with_no_key_is_refused_rather_than_answered_emptily(tmp_path) -> None:
    client = _app(tmp_path)
    resp = client.get("/api/v1/hint/variant", params={"offline": True})

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "hint_needs_a_key"


def test_no_snapshot_path_reaches_the_wire(tmp_path) -> None:
    """`VariantHint.checked` holds an absolute path and one finding interpolates it into prose.

    Both are scrubbed to lane names here. Asserted against the rendered body using the path this
    deployment is actually configured with, rather than a list of likely prefixes — a prefix list
    passes on a box whose caches live somewhere it did not think of.
    """
    cache = tmp_path / "pretend-ensembl"
    cache.mkdir()
    (cache / "stray.parquet").write_bytes(b"x")

    client = _app(tmp_path, ensembl_cache=cache)
    resp = client.get("/api/v1/hint/variant", params={"rsid": "rs4244285", "offline": True})

    assert resp.status_code == 200, resp.text
    raw = json.dumps(resp.json())
    assert str(cache) not in raw
    assert str(tmp_path) not in raw


def test_the_scrubber_maps_a_snapshot_path_to_its_lane_name(tmp_path) -> None:
    """The mapping is built from the same resolution the lookup used, so it cannot describe another set."""
    from just_dna_registry.config import Settings

    settings = Settings(
        db_path=tmp_path / "r.db", storage_backend="local", storage_root=tmp_path / "s",
        clinvar_cache=tmp_path / "cv",
    )
    (tmp_path / "cv").mkdir()
    scrub = hint_service.HintScrubber.build(settings)

    assert scrub.label(str(tmp_path / "cv")) == "clinvar"
    # A label that is not a path is passed through: `_lookup_live_loci` records `ensembl-live`, and
    # that is the half a caller actually needs.
    assert scrub.label("ensembl-live") == "ensembl-live"
    assert "<clinvar snapshot>" in scrub.text(f"snapshot at {tmp_path / 'cv'} unreadable")


def test_the_charge_is_shaped_by_which_legs_will_run() -> None:
    """NCBI only with an rsID, gnomAD only with frequencies, nothing at all offline.

    `_check_rsid_currency` returns immediately without an rsID, so charging a coordinate-only lookup
    would bill for a request that is never made — and it runs on *every* online rsID lookup even when
    the snapshot answers, because dbSNP merge status has no snapshot in this tree.
    """
    assert hint_service.variant_charges(rsid="rs1", frequencies=False, offline=True) == {}
    assert hint_service.variant_charges(rsid="rs1", frequencies=True, offline=True) == {}
    assert hint_service.variant_charges(rsid=None, frequencies=False, offline=False) == {}
    assert hint_service.variant_charges(rsid="rs1", frequencies=False, offline=False) == {"ncbi": 1}
    assert hint_service.variant_charges(rsid="rs1", frequencies=True, offline=False) == {
        "ncbi": 1, "gnomad": 1,
    }


def test_ensembl_is_reconciled_from_the_structured_member_not_from_prose() -> None:
    """A warning's wording is upstream's to change; only the pinned member is an API."""

    class _Hint:
        checked = {"/some/snapshot", "ensembl-live"}

    class _Cached:
        checked = {"/some/snapshot"}

    assert hint_service.reconcile_ensembl(_Hint(), {"ncbi": 1}) == {"ncbi": 1, "ensembl": 1}
    assert hint_service.reconcile_ensembl(_Cached(), {"ncbi": 1}) == {"ncbi": 1}


def test_the_ledger_is_grounded_in_the_clients_that_actually_pace(tmp_path) -> None:
    """`EutilsClient` picks 10/s with a key and 3/s without, so a constant describes the wrong box."""
    client = _app(tmp_path)
    ledger = client.app.state.pace_ledger

    assert ledger.intervals, "no interval was read off a client, so the decay is guessing"
    assert set(ledger.intervals) <= set(pacing.UPSTREAMS)
    assert ledger.interval_for("gnomad") == 6.0


def test_a_decayed_pace_comes_back_as_a_429_that_names_the_upstream_and_the_remedy(tmp_path) -> None:
    """Past the inline-absorb threshold the honest answer is a header, not a held connection.

    The remedy has to be the one true for *that* upstream: gnomAD sells no key at any price, so a
    message telling a caller to buy one is a lie they can check.
    """
    # gnomAD switched on deliberately: with the default off this test would answer 403 and skip
    # itself, which is a test that never runs. The switch is the deployment's, the decay is not.
    client = _app(tmp_path, hint_allow_gnomad=True)
    ledger = client.app.state.pace_ledger

    # Walk this identity far past the gnomAD allowance, then ask for something that charges it.
    # `_rate_identity` keys an anonymous caller by IP and a bearer by its prefix, so the key here is
    # the one the request will present.
    ledger.charge("key:mk_live_testkey", {"gnomad": ledger.budget_for("gnomad") * 8})

    resp = client.get(
        "/api/v1/hint/variant",
        params={"rsid": "rs4244285", "offline": False, "frequencies": True},
        headers=_AUTH,
    )

    assert resp.status_code == 429, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "hint_pace_decayed"
    assert detail["upstream"] == "gnomad"
    assert "no API key at any price" in detail["remedy"]
    assert int(resp.headers["Retry-After"]) >= 1


def test_an_online_batch_of_frequencies_is_refused_rather_than_started(tmp_path) -> None:
    """128 keys at six seconds apiece is 12.8 minutes against a request that will not live that long."""
    client = _app(tmp_path)
    resp = client.post(
        "/api/v1/hint/variants",
        params={"offline": False, "frequencies": True},
        json={"keys": [{"rsid": "rs4244285"}]},
        headers=_AUTH,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "frequencies_not_batchable"


def test_the_online_batch_cap_is_far_below_the_offline_one(tmp_path) -> None:
    """The bound is what can finish inside one request, not a round number.

    An online batch runs its misses sequentially at the upstream's own pace; an offline one is duckdb.
    """
    client = _app(tmp_path)
    settings = client.app.state.settings
    assert settings.hint_max_batch_online < settings.hint_max_batch

    keys = [{"rsid": f"rs{n}"} for n in range(settings.hint_max_batch_online + 1)]
    resp = client.post(
        "/api/v1/hint/variants", params={"offline": False}, json={"keys": keys}, headers=_AUTH
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "too_many_variants"
    assert detail["limit"] == settings.hint_max_batch_online


@pytest.mark.skipif(_ENSEMBL is None, reason="this box has no Ensembl snapshot")
def test_a_batch_against_a_provisioned_snapshot_charges_nothing_and_reaches_nothing(tmp_path) -> None:
    """**The claim the release rests on**, with the socket tripwire armed.

    `no_network` makes any non-loopback connection raise, so a batch that quietly egressed would fail
    here rather than merely costing something. Zero charge and zero egress on a provisioned box is the
    number that makes this worth deploying — if it ever stops being true, the caching proxy is a proxy
    and not a cache.
    """
    client = _app(tmp_path, ensembl_cache=_ENSEMBL)
    keys = [{"rsid": rs} for rs in ("rs4244285", "rs1799853", "rs1057910", "rs12248560")]

    resp = client.post("/api/v1/hint/variants", params={"offline": True}, json={"keys": keys})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_charged"] == {}
    assert len(body["results"]) == len(keys)
    assert all(result["cost"]["charged"] == {} for result in body["results"])

    placed = [r for r in body["results"] if r["loci"]]
    assert placed, "no key resolved, so this proved nothing about answering from a snapshot"
    assert all("ensembl" in " ".join(r["cost"]["served_from"]) for r in placed)
