"""`?gene=` and `?category=` read a module's current version, as every other facet does (0.28.1).
Through 0.28.0 they matched any non-yanked version, so a gene dropped long ago kept a module listed."""

from collections.abc import Callable

from fastapi.testclient import TestClient


def _names(client: TestClient, **params: str) -> list[str]:
    return sorted(i["name"] for i in client.get("/api/v1/modules", params=params).json()["items"])


def test_a_gene_or_category_dropped_from_the_latest_version_stops_matching(
    client: TestClient, seed: Callable
) -> None:
    seed("ns1", "modul", "1.0.0", genes=["BRCA1", "TP53"], categories=["cancer", "old"],
         created_at="2026-01-01T00:00:00Z")
    seed("ns1", "modul", "1.0.1", genes=["TP53"], categories=["cancer"], created_at="2026-01-02T00:00:00Z")
    assert _names(client, gene="TP53") == ["modul"] and _names(client, category="cancer") == ["modul"]
    assert _names(client, gene="BRCA1") == [] and _names(client, category="old") == []
