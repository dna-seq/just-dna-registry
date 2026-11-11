"""The caching proxy's coverage guards (0.30, the pm's acceptance gate).

Every snapshot lane upstream registers answers a keyed lookup through a route, or is exempt with a reason
a reader can check; every derived-table producer upstream registers runs through a route, or is exempt
likewise. The served sets are read off the app's routes (`proxy_coverage.proxies`), never kept by hand,
and both rosters are upstream's. Each guard carries a floor on the upstream count, because a subset check
over an emptied import passes and proves nothing (CLAUDE.md, *denominator floors*)."""

import pytest
from just_dna_compiler.compiler import _FACT_TABLES
from just_dna_enricher.caches import CACHE_LANES
from just_dna_enricher.producers import DERIVED_PRODUCERS, WRITTEN_BY_EVERY_PASS

from just_dna_registry.proxy_coverage import (
    ENRICH_PRODUCERS,
    EXEMPT_LANES,
    EXEMPT_PRODUCERS,
    served,
)


def _lanes() -> set[str]:
    return {lane.name for lane in CACHE_LANES}


def _producers() -> set[tuple[str, str]]:
    return {(p.table, p.command) for entries in DERIVED_PRODUCERS.values() for p in entries}


@pytest.mark.parametrize("mode", ["prod", "test"])
def test_every_lane_is_proxied_or_exempt_with_a_reason(mode: str, tmp_path, monkeypatch) -> None:
    from just_dna_registry.api.app import create_app
    from just_dna_registry.config import Settings

    upstream = _lanes()
    assert len(upstream) >= 10, upstream  # the floor: an emptied roster would pass the rest
    lanes, _ = served(create_app(Settings(mode=mode, db_path=tmp_path / "r.db")))
    assert lanes & set(EXEMPT_LANES) == set(), "a lane is both served and exempt"
    assert set(EXEMPT_LANES) <= upstream, f"exempt lanes upstream no longer has: {set(EXEMPT_LANES) - upstream}"
    assert lanes <= upstream, f"routes claim lanes upstream does not have: {lanes - upstream}"
    missing = upstream - lanes - set(EXEMPT_LANES)
    assert not missing, f"lanes neither proxied nor exempt: {sorted(missing)}"
    assert all(reason.strip() for reason in EXEMPT_LANES.values())


@pytest.mark.parametrize("mode", ["prod", "test"])
def test_every_producer_runs_through_a_route_or_is_exempt_with_a_reason(mode: str, tmp_path) -> None:
    from just_dna_registry.api.app import create_app
    from just_dna_registry.config import Settings

    upstream = _producers()
    assert len(upstream) >= 10, upstream
    _, producers = served(create_app(Settings(mode=mode, db_path=tmp_path / "r.db")))
    assert producers & set(EXEMPT_PRODUCERS) == set()
    assert set(EXEMPT_PRODUCERS) <= upstream, set(EXEMPT_PRODUCERS) - upstream
    assert producers <= upstream, producers - upstream
    missing = upstream - producers - set(EXEMPT_PRODUCERS)
    assert not missing, f"producers neither run here nor exempt: {sorted(missing)}"


def test_every_fact_table_has_a_producer_upstream() -> None:
    """The cross-check: a fact table the compiler reads with no producer in the roster would escape the
    producer guard entirely. `_FACT_TABLES` is private, so it is the cross-check and never the roster."""
    tables = {csv for csv, _parquet, _model in _FACT_TABLES} - set(WRITTEN_BY_EVERY_PASS)
    assert len(tables) >= 10, tables
    assert tables <= set(DERIVED_PRODUCERS), tables - set(DERIVED_PRODUCERS)


def test_the_enrich_producers_are_upstreams() -> None:
    assert set(ENRICH_PRODUCERS) == {p for p in _producers() if p[1] == "enrich"}
