"""`GET /stats` (0.28): the totals `RegistryClient.catalog_stats()` used to compute by paging the whole
listing, now one request. The property that matters is that the two agree, for every scope, so a
consumer sees nothing but latency; and that asking costs no module a search hit."""

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from sdk_transport import sdk_transport

from just_dna_registry.client import RegistryClient
from just_dna_registry.db.repository import Repository


@pytest.fixture
def catalog(repo: Repository, seed: Callable) -> Repository:
    for ns, name, genes in (("ns-one", "alpha", ["A", "B"]), ("ns-one", "beta", ["C"]),
                            ("ns-two", "gamma", ["D", "E", "F"]), ("test-sandbox", "delta", ["G"])):
        seed(ns, name, "1.0.0", genes=genes, categories=["x"], created_at="2026-01-01T00:00:00Z")
    reviewer = repo.create_account("reviewer")
    alpha = int(repo.get_module_row("ns-one", "alpha")["id"])
    repo.upsert_review(alpha, "1.0.0", reviewer, rating=5, verdict=None, notes=None, now="2026-01-02")
    repo.set_review_highlight(alpha, "1.0.0", reviewer, True)
    repo.conn.execute("UPDATE modules SET downloads = 7, stars = 2, views = 11 WHERE name = 'gamma'")
    repo.conn.commit()
    return repo


@pytest.mark.parametrize(
    "scope", [{}, {"namespace": "ns-one"}, {"group": "test"}, {"group": "curated"}, {"namespace": "test-sandbox"}]
)
def test_the_route_agrees_with_paging_the_listing(client: TestClient, catalog: Repository, scope: dict) -> None:
    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    served = sdk.catalog_stats(**scope)
    paged = sdk._paged_catalog_stats(scope.get("namespace"), group=scope.get("group"))
    assert served == paged, scope


def test_the_totals_are_the_card_figures_summed(client: TestClient, catalog: Repository) -> None:
    body = client.get("/api/v1/stats").json()
    assert body["modules"] == 3 and body["namespaces"] == 2  # the sandbox is outside the default listing
    assert (body["downloads"], body["stars"], body["views"]) == (7, 2, 11)
    assert (body["reviews"], body["curated"]) == (1, 1)
    assert body["variants"] == 2 * 6 and body["genes"] == 6  # the seed writes two variants per gene


def test_asking_charges_no_module_a_search_hit(client: TestClient, catalog: Repository) -> None:
    def hits() -> list[int]:
        return [r[0] for r in catalog.conn.execute("SELECT search_hits FROM modules ORDER BY id")]

    before = hits()
    assert client.get("/api/v1/stats").status_code == 200
    assert hits() == before


def test_an_older_server_without_the_route_is_paged(client: TestClient, catalog: Repository) -> None:
    inner = sdk_transport(client)

    def older(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stats"):
            return httpx.Response(404, json={"detail": "Not Found"}, request=request)
        return inner.handle_request(request)

    sdk = RegistryClient("http://testserver", transport=httpx.MockTransport(older), check_version=False)
    assert sdk.catalog_stats()["modules"] == 3
