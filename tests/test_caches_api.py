"""`GET /api/v1/caches` and the projection behind it (0.25).

The dashboard exists because this service is the box in the ecosystem that *holds* the multi-gigabyte
snapshots, and a thin client deciding whether to lean on it has no other way to ask which ones. So the
things worth pinning are the ones a wrong answer would mislead somebody about: the three states, the
recorded reason for an absent lane, and the fact that no filesystem path leaves the process.
"""

import json

import pytest
from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.api.routers import caches as caches_router
from just_dna_registry.config import Settings
from just_dna_registry.services import enrich

pytestmark = pytest.mark.skipif(
    not enrich.enricher_available(), reason="the network tier is not installed"
)


@pytest.fixture(autouse=True)
def _no_ttl_bleed():
    """The route memoizes per settings; a test changing settings must not read a neighbour's report."""
    caches_router._cached.clear()
    yield
    caches_router._cached.clear()


def body(client: TestClient) -> dict:
    resp = client.get("/api/v1/caches")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_route_is_anonymous_and_reports_every_provisionable_lane(client: TestClient) -> None:
    """Set equality against the enricher's own registry — a count would pass while a lane went missing."""
    report = body(client)

    assert report["enricher_available"] is True
    assert {lane["name"] for lane in report["lanes"]} == set(enrich.provisionable_lanes())
    assert report["declared_use"] == "unstated"


def test_no_filesystem_path_reaches_the_wire(client: TestClient, settings: Settings) -> None:
    """The one rule this endpoint cannot break, asserted over the whole serialized body.

    Lane *presence* is an operational fact `/health` already publishes the analogue of. The server's
    directory layout is not, and it is the half an anonymous reader has no business with — so this
    greps the rendered JSON rather than trusting the model's field list, which is what would have to
    be re-audited every time a field is added.
    """
    raw = json.dumps(body(client))

    # Ground truth rather than a hardcoded prefix list: these are the paths this box would actually
    # leak, resolved through the same ladder the report walks. A list of likely-looking prefixes
    # passes on a machine whose caches live somewhere the list did not think of.
    resolved = [path for path in enrich.lane_presence(settings).values() if path is not None]
    assert resolved, "no lane is provisioned here, so this test would pass without proving anything"
    for path in resolved:
        assert str(path) not in raw, f"the report leaked {path}"
        assert str(path.parent) not in raw

    assert str(settings.db_path.parent) not in raw
    # And nothing that merely *reads* as an absolute path in any field, at any depth — which is what
    # catches a future field holding one this box happens not to have provisioned.
    assert '"/' not in raw.replace('"/api', "")

    for lane in enrich.lane_status(settings).lanes:
        assert lane.name in raw


def test_read_here_names_exactly_the_lanes_a_pass_here_opens(client: TestClient) -> None:
    """`read_here` is a claim that something on this box opens the lane, so it tracks one tuple.

    A lane named there that nothing reads is how `constraint` came to trigger boot warnings about a
    file no pass would open, so the set is asserted rather than spot-checked — and `group` has to
    agree with it in both directions.
    """
    lanes = body(client)["lanes"]

    assert {lane["name"] for lane in lanes if lane["read_here"]} == set(enrich.REFERENCE_NAMES)
    assert {lane["name"] for lane in lanes if lane["group"]} == set(enrich.REFERENCE_NAMES)
    for lane in lanes:
        assert (lane["group"] is not None) == lane["read_here"]


def test_the_route_a_lane_would_take_is_read_from_its_two_stages_independently(
    client: TestClient,
) -> None:
    """`pullable` / `buildable` / `none` come off `ensure` and `rebuild` separately.

    Never from one alone: a lane can carry an `ensure` and no `rebuild` for an acquisition reason
    rather than a division of labour, and upstream already has one that does.
    """
    lanes = {lane["name"]: lane for lane in body(client)["lanes"]}
    registry = enrich.cache_lanes()

    for name, lane in lanes.items():
        upstream = registry[name]
        expected = (
            "pullable" if upstream.ensure is not None
            else "buildable" if upstream.rebuild is not None
            else "none"
        )
        assert lane["route"] == expected, name
        if expected != "pullable":
            assert lane["route_reason"], f"{name} has no route and no recorded reason for it"


def test_an_unreadable_directory_is_partial_and_not_absent(tmp_path) -> None:
    """The state that sends an operator somewhere else, driven through the real resolver.

    A directory holding something that is not a readable snapshot is exactly what `prepare_lane`
    refuses to act on — provisioning never deletes — so reporting it as `absent` would tell an
    operator to run a pull that is going to decline.
    """
    junk = tmp_path / "half-a-clinvar"
    junk.mkdir()
    (junk / "clinvar.parquet.part").write_bytes(b"not a snapshot")

    settings = Settings(
        db_path=tmp_path / "registry.db",
        storage_backend="local",
        storage_root=tmp_path / "artifacts",
        clinvar_cache=junk,
    )
    lanes = {lane.name: lane for lane in enrich.lane_status(settings).lanes}

    assert lanes["clinvar"].state == "partial"
    assert lanes["clinvar"].configured is True
    assert lanes["clinvar"].release is None


def test_a_configured_but_empty_directory_is_absent(tmp_path) -> None:
    """The other side of the same discrimination: empty is absent, occupied is partial."""
    empty = tmp_path / "nothing-here"
    empty.mkdir()

    settings = Settings(
        db_path=tmp_path / "registry.db",
        storage_backend="local",
        storage_root=tmp_path / "artifacts",
        clinvar_cache=empty,
    )
    lanes = {lane.name: lane for lane in enrich.lane_status(settings).lanes}

    assert lanes["clinvar"].state == "absent"
    assert lanes["clinvar"].configured is True


def test_a_licence_gated_lane_says_why_a_pull_would_decline(client: TestClient) -> None:
    """"Not provisioned" and "will never arrive under this declared use" are different instructions.

    Computed with the enricher's own `check_declared_use`, so the report agrees with the gate that
    would later refuse rather than describing a parallel policy.
    """
    lanes = {lane["name"]: lane for lane in body(client)["lanes"]}
    registry = enrich.cache_lanes()

    gated = {name for name, lane in registry.items() if lane.terms is not None}
    assert gated, "the fixture registry carries no licence-gated lane to check"
    assert {name for name, lane in lanes.items() if lane["licence_gated"]} == gated

    # Under the default `unstated`, a no-sale source is skipped with a reason rather than taken.
    skipping = {name for name in gated if lanes[name]["licence_skip"]}
    assert skipping, "every gated lane claimed unstated use was fine, which contradicts the gate"


def test_a_deployment_without_the_network_tier_says_so_once(monkeypatch, settings: Settings) -> None:
    """Fourteen absent lanes and one missing package are different reports.

    A client that cannot tell them apart tells an operator to provision snapshots on a box that has
    nothing to read them with.
    """
    monkeypatch.setattr(enrich, "cache_lanes", dict)
    report = enrich.lane_status(settings)

    assert report.enricher_available is False
    assert report.lanes == []


def test_two_deployments_in_one_process_do_not_share_a_memoized_report(tmp_path) -> None:
    """The TTL is keyed on what the report depends on, not held in a single slot.

    A single slot is right until something builds two apps — this suite does, production and polygon
    — and then the second reads the first's answer for the length of the TTL.
    """
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "stray.part").write_bytes(b"x")

    plain = Settings(
        db_path=tmp_path / "a.db", storage_backend="local", storage_root=tmp_path / "sa",
    )
    pinned = Settings(
        db_path=tmp_path / "b.db", storage_backend="local", storage_root=tmp_path / "sb",
        clinvar_cache=occupied,
    )

    with TestClient(create_app(plain)) as first, TestClient(create_app(pinned)) as second:
        a = {lane["name"]: lane for lane in body(first)["lanes"]}
        b = {lane["name"]: lane for lane in body(second)["lanes"]}

    assert b["clinvar"]["state"] == "partial"
    assert b["clinvar"]["configured"] is True
    assert a["clinvar"]["configured"] is False
    assert a["clinvar"]["state"] != "partial" or a["clinvar"]["release"] is not None


def test_a_present_lane_reports_its_release_or_says_it_could_not_be_read(
    client: TestClient,
) -> None:
    """`release: null` must never be a placeholder — a caller has to tell a release from silence."""
    for lane in body(client)["lanes"]:
        if lane["state"] != "present":
            assert lane["release"] is None
            continue
        assert lane["release"] is None or lane["release"].strip()
        if lane["release"] is not None:
            assert lane["release_unreadable"] is False
