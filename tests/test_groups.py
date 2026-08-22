"""Listing groups (0.8.0): server-owned namespace grouping behind the webui's tabs
(all / featured / popular / new / test). Membership is defined server-side so every client agrees;
test/sandbox namespaces (a config regex) are isolated to the `test` tab and hidden elsewhere.

Since 0.21.1 the hiding is a *production* policy: on the polygon the sandbox spaces are the whole
catalog, so excluding them left every listing route answering `total: 0` on a box that was not empty
(S17). Both directions are asserted below, because a mode-dependent rule tested from one side is half
a rule — and here the half that matters is that production still hides them.
"""

from pathlib import Path

from conftest import seed_into
from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository


def _seed_catalog(seed) -> None:
    common = {"categories": ["c"]}
    seed("just-dna-seq", "coronary", "1.0.0", genes=["LPA"], created_at="2025-01-01T00:00:00Z", **common)
    seed("acme", "cancer", "1.0.0", genes=["BRCA1"], created_at="2025-02-01T00:00:00Z", **common)
    seed("sandbox-alice", "toy", "1.0.0", genes=["X"], created_at="2025-03-01T00:00:00Z", **common)
    seed("test-bob", "scratch", "1.0.0", genes=["Y"], created_at="2025-04-01T00:00:00Z", **common)


def _namespaces(body: dict) -> set[str]:
    return {i["namespace"] for i in body["items"]}


def test_default_listing_hides_test_and_sandbox(client: TestClient, seed) -> None:
    _seed_catalog(seed)
    ns = _namespaces(client.get("/api/v1/modules").json())
    assert {"just-dna-seq", "acme"} <= ns
    assert "sandbox-alice" not in ns and "test-bob" not in ns


def test_group_test_isolates_test_namespaces(client: TestClient, seed) -> None:
    _seed_catalog(seed)
    ns = _namespaces(client.get("/api/v1/modules", params={"group": "test"}).json())
    assert ns == {"sandbox-alice", "test-bob"}


def test_explicit_namespace_reaches_a_test_space(client: TestClient, seed) -> None:
    # A test/sandbox space is hidden from the tabs but still reachable by exact name.
    _seed_catalog(seed)
    body = client.get("/api/v1/modules", params={"namespace": "sandbox-alice"}).json()
    assert _namespaces(body) == {"sandbox-alice"}


def test_group_featured(client: TestClient, seed, app, api_key: str) -> None:
    _seed_catalog(seed)
    repo: Repository = app.state.repo
    assert repo.set_namespace_flags("just-dna-seq", featured=True)  # api_key fixture owns this ns
    body = client.get("/api/v1/modules", params={"group": "featured"}).json()
    assert _namespaces(body) == {"just-dna-seq"}


def test_group_popular_and_new_exclude_test(client: TestClient, seed) -> None:
    _seed_catalog(seed)
    for group in ("popular", "new"):
        ns = _namespaces(client.get("/api/v1/modules", params={"group": group}).json())
        assert "sandbox-alice" not in ns and "test-bob" not in ns, group
        assert {"just-dna-seq", "acme"} <= ns, group


def test_group_all_matches_default(client: TestClient, seed) -> None:
    _seed_catalog(seed)
    assert _namespaces(client.get("/api/v1/modules", params={"group": "all"}).json()) == _namespaces(
        client.get("/api/v1/modules").json()
    )


def test_groups_discovery_endpoint(client: TestClient) -> None:
    body = client.get("/api/v1/modules/groups").json()
    assert [g["key"] for g in body] == ["all", "featured", "curated", "popular", "new", "test"]
    assert all(g["label"] and g["description"] for g in body)


def test_invalid_group_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/modules", params={"group": "bogus"}).status_code == 422


# ── The polygon lists what it holds (S17) ───────────────────────────────────────────────────────


def _instance(tmp_path: Path, mode: str, namespaces: tuple[str, ...]) -> TestClient:
    """An app in `mode` holding one module per namespace, seeded past the publish gate."""
    empty = tmp_path / "no-cache"
    app = create_app(Settings(
        mode=mode,
        db_path=tmp_path / f"{mode}.db",
        local_storage_dir=tmp_path / f"artifacts-{mode}",
        ensembl_cache=empty, clinvar_cache=empty, constraint_cache=empty,
    ))
    for i, ns in enumerate(namespaces):
        seed_into(app, ns, f"longevity_{i}", "1.0.0", genes=["FOXO3"], categories=["c"],
                  created_at="2026-08-22T00:00:00Z")
    return TestClient(app)


_POLYGON_SPACES = ("test-sheep", "sandbox-alice")


def test_polygon_default_listing_agrees_with_health(tmp_path: Path) -> None:
    # The reported symptom: /health counted the modules and every read path answered zero.
    c = _instance(tmp_path, "test", _POLYGON_SPACES)
    counted = c.get("/health").json()["catalog"]["modules"]
    assert counted == len(_POLYGON_SPACES)
    for params in ({}, {"group": "all"}, {"q": "longevity"}, {"group": "new"}):
        assert c.get("/api/v1/modules", params=params).json()["total"] == counted, params


def test_production_still_hides_test_spaces(tmp_path: Path) -> None:
    # The half that matters: a production instance holding accepted test data keeps hiding it.
    c = _instance(tmp_path, "prod", ("just-dna-seq", *_POLYGON_SPACES))
    assert c.get("/health").json()["catalog"]["modules"] == 3
    assert _namespaces(c.get("/api/v1/modules").json()) == {"just-dna-seq"}
    assert _namespaces(c.get("/api/v1/modules", params={"group": "test"}).json()) == set(
        _POLYGON_SPACES
    )


def test_group_test_means_the_same_thing_on_both_instances(tmp_path: Path) -> None:
    # `test` is not special-cased alongside the dropped exclusion: it still names the sandbox spaces.
    polygon = _instance(tmp_path / "a", "test", ("just-dna-seq", *_POLYGON_SPACES))
    prod = _instance(tmp_path / "b", "prod", ("just-dna-seq", *_POLYGON_SPACES))
    both = [_namespaces(c.get("/api/v1/modules", params={"group": "test"}).json())
            for c in (polygon, prod)]
    assert both[0] == both[1] == set(_POLYGON_SPACES)


def test_groups_discovery_describes_the_instance_it_runs_on(tmp_path: Path) -> None:
    """Same keys and order on both; exactly one description moves, and it is `all`'s.

    Asserted structurally rather than by matching wording: what must hold is that the tab whose
    *contents* differ by instance is the only one whose description does, so a UI cannot render a
    label contradicting the listing behind it.
    """
    polygon = _instance(tmp_path / "a", "test", _POLYGON_SPACES).get("/api/v1/modules/groups").json()
    prod = _instance(tmp_path / "b", "prod", _POLYGON_SPACES).get("/api/v1/modules/groups").json()
    assert [g["key"] for g in polygon] == [g["key"] for g in prod]
    described = ({g["key"]: g["description"] for g in polygon},
                 {g["key"]: g["description"] for g in prod})
    assert {k for k in described[0] if described[0][k] != described[1][k]} == {"all"}
    assert all(g["label"] and g["description"] for g in polygon)
