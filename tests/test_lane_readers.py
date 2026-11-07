"""`lane_readers` (0.28.4): what opens each snapshot lane, read from the tuples the call sites pass.

Against upstream's real lane registry and the real `enrich()`, `DRAFT_SOURCES` and `HINT_LANES`, so a
lane upstream adds, or a route that starts opening one, moves the answer without a list here moving.
"""

import inspect
from pathlib import Path

import pytest
from just_dna_enricher.enrich import enrich
from typer.testing import CliRunner

from just_dna_registry import cli
from just_dna_registry.services.drafting import DRAFT_SOURCES
from just_dna_registry.services.enrich import ENRICH_LANES, LANE_GROUPS, cache_lanes
from just_dna_registry.services.hints import HINT_LANES
from just_dna_registry.services.lane_readers import lane_readers, proxy_lanes, reader_tag


def test_enrich_lanes_are_every_cache_enrich_takes() -> None:
    """`enrich_spec` passes `ENRICH_LANES`; a `*_cache` upstream adds and we omit resolves ambiently."""
    taken = {p.removesuffix("_cache") for p in inspect.signature(enrich).parameters if p.endswith("_cache")}
    assert len(taken) >= 5, taken
    assert set(ENRICH_LANES) == taken


def test_every_call_site_lane_has_its_reader() -> None:
    readers = lane_readers()
    assert set(readers) == set(cache_lanes()) and len(readers) >= 15
    drafted = {lane for source in DRAFT_SOURCES.values() for lane in source.lanes}
    assert drafted and all("proxy: drafts" in readers[lane] for lane in drafted)
    assert all("publish" in readers[lane] and "proxy: derived" in readers[lane] for lane in ENRICH_LANES)
    assert all("proxy: hints" in readers[lane] for lane in HINT_LANES)
    assert all(f"check: {group}" in readers[lane] for lane, group in LANE_GROUPS.items())


def test_the_lanes_0_28_3_called_unread() -> None:
    readers = lane_readers()
    for lane in ("pubmind", "civic", "clinvar_gkm", "strchive", "mitomap_miss", "mitomap"):
        assert readers[lane], f"{lane} is opened by something here"
    assert readers["alphagenome_avi"] == ()
    assert reader_tag(()) == "[nothing here]"


def test_proxy_lanes_carry_their_build_parents() -> None:
    lanes, proxied = cache_lanes(), proxy_lanes()
    assert "mitomap_miss" in proxied and set(lanes["mitomap_miss"].parents) <= proxied
    assert "alphagenome_avi" not in proxied


def _warm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> str:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("JUST_DNA_PIPELINES_CACHE_DIR", str(tmp_path / "empty"))
    cli.get_settings.cache_clear()
    try:
        return CliRunner().invoke(cli.app, ["warm-caches", *args]).output
    finally:
        cli.get_settings.cache_clear()


def _queued(out: str) -> set[str]:
    """The lanes the dry run would provision: the `✗ <lane> [` rows."""
    return {line.split()[1] for line in out.splitlines() if line.lstrip().startswith("✗ ")}


def test_warm_caches_proxy_selects_the_proxy_surface(tmp_path: Path, monkeypatch) -> None:
    out = _warm(tmp_path, monkeypatch, "--proxy")
    queued = _queued(out)
    assert set(proxy_lanes()) <= queued, out
    assert "alphagenome_avi" not in queued


def test_exclude_overrides_all_proxy_and_the_default_pair(tmp_path: Path, monkeypatch) -> None:
    out = _warm(tmp_path, monkeypatch, "--all", "--proxy", "--exclude", "alphagenome_avi",
                "--exclude", "ensembl")
    queued = _queued(out)
    assert queued and "alphagenome_avi" not in queued and "ensembl" not in queued, out
    assert "alphagenome_avi [nothing here]: excluded" in out
    assert "clinvar" in queued


def test_an_unknown_exclude_is_a_usage_error(tmp_path: Path, monkeypatch) -> None:
    out = _warm(tmp_path, monkeypatch, "--exclude", "alphagenom")
    assert "unknown lane(s): alphagenom" in out
