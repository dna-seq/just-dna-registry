"""`warm-caches` rebuilds a present derived lane that an older enricher built.

`prepare_lane` leaves a present cache alone, so without this a derivation upstream corrects in a patch
(RM293) never reaches a box that had already built the lane. See `services.enrich.LaneAge`.
"""

import json
import shutil
from pathlib import Path

import pytest
from just_dna_enricher import caches

from just_dna_registry.config import Settings
from just_dna_registry.services.enrich import (
    LaneAge,
    _builder_version,
    cache_lanes,
    derived_lane_ages,
    lane_presence,
    rebuild_derived_lane,
)
from just_dna_registry.version import installed_enricher


def test_there_is_a_derived_lane_to_watch() -> None:
    """Floor: an emptied or renamed `parents` field would make every check below vacuous."""
    derived = {name for name, lane in cache_lanes().items() if lane.parents}
    assert "mitomap_miss" in derived


@pytest.mark.parametrize(
    ("built_by", "installed", "stale"),
    [
        ("0.7.2", "0.7.3", True),  # a patch is enough: the rebuild is local and cheap
        ("0.6.6", "0.7.3", True),
        ("0.7.3", "0.7.3", False),  # converges: a rebuild stamps the installed version
        ("0.7.4", "0.7.3", False),  # a downgrade is not staleness
        (None, "0.7.3", None),  # unrecorded is *cannot say*, never current
        ("0.7.3", None, None),
        ("0.7.3.dev1", "0.7.3", None),  # unparseable likewise
    ],
)
def test_staleness_compares_versions(built_by: str | None, installed: str | None, stale: bool | None) -> None:
    assert LaneAge("mitomap_miss", Path("unused"), built_by, installed).stale is stale


def test_builder_version_is_read_from_release_json(tmp_path: Path) -> None:
    lane = tmp_path / "lane"
    lane.mkdir()
    assert _builder_version(lane) is None
    (lane / "release.json").write_text("{not json")
    assert _builder_version(lane) is None
    (lane / "release.json").write_text(json.dumps({"builder_version": 7}))
    assert _builder_version(lane) is None
    (lane / "release.json").write_text(json.dumps({"builder_version": "0.7.2", "built_at": "x"}))
    assert _builder_version(lane) == "0.7.2"
    payload = lane / "data.parquet"
    payload.write_bytes(b"")
    assert _builder_version(payload) == "0.7.2"  # a lane that resolves to a file reads its directory


def _old_lane(root: Path) -> LaneAge:
    target = root / "mitomap_miss"
    target.mkdir()
    (target / "release.json").write_text(json.dumps({"builder_version": "0.0.1"}))
    (target / "old.marker").write_text("previous build")
    target.chmod(0o2775)
    return LaneAge("mitomap_miss", target, "0.0.1", "0.7.3")


def test_rebuild_swaps_in_the_new_build_and_keeps_the_old(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def build(lane: caches.CacheLane, request: caches.RebuildRequest) -> caches.RebuildOutcome:
        (request.out_dir / "release.json").write_text(json.dumps({"builder_version": "0.7.3"}))
        return caches.RebuildOutcome(lane.name, True, "built", request.out_dir)

    monkeypatch.setattr(caches, "rebuild_lane", build)
    age = _old_lane(tmp_path)
    built, detail = rebuild_derived_lane(Settings(), age)

    assert built is True
    backup = tmp_path / "mitomap_miss.pre-0.7.3"
    assert backup.name in detail
    assert (backup / "old.marker").read_text() == "previous build"
    assert _builder_version(age.path) == "0.7.3"
    assert not (age.path / "old.marker").exists()
    assert age.path.stat().st_mode & 0o7777 == 0o2775  # not mkdtemp's 0700
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mitomap_miss", "mitomap_miss.pre-0.7.3"]

    # A second swap on the same installed version does not overwrite the first backup.
    (age.path / "release.json").write_text(json.dumps({"builder_version": "0.0.1"}))
    assert rebuild_derived_lane(Settings(), age)[0] is True
    assert (backup / "old.marker").exists()
    assert (tmp_path / "mitomap_miss.pre-0.7.3.2").is_dir()


@pytest.mark.parametrize("built", [False, None])
def test_a_rebuild_that_does_not_finish_leaves_the_live_lane_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, built: bool | None
) -> None:
    monkeypatch.setattr(
        caches, "rebuild_lane", lambda lane, request: caches.RebuildOutcome(lane.name, built, "parents missing")
    )
    age = _old_lane(tmp_path)
    result, detail = rebuild_derived_lane(Settings(), age)

    assert result is built
    assert "parents missing" in detail and "untouched" in detail
    assert (age.path / "old.marker").read_text() == "previous build"
    assert not list(tmp_path.glob("mitomap_miss.pre-*"))


def test_real_rebuild_of_a_stale_copy(tmp_path: Path) -> None:
    """The real join, on a copy of this box's lane with its stamp backdated. Skips where the parents
    or the lane are not provisioned — the unit tests above carry the logic everywhere else."""
    present = lane_presence(Settings())
    if any(present.get(name) is None for name in ("mitomap", "clinvar", "mitomap_miss")):
        pytest.skip("mitomap, clinvar and mitomap_miss snapshots are not provisioned on this box")
    copy = tmp_path / "mitomap_miss"
    shutil.copytree(Path(present["mitomap_miss"]), copy)
    stamp = copy / "release.json"
    stamp.write_text(json.dumps(json.loads(stamp.read_text()) | {"builder_version": "0.0.1"}))

    settings = Settings(mitomap_miss_cache=copy)
    ages = {age.lane: age for age in derived_lane_ages(settings)}
    assert ages["mitomap_miss"].stale is True

    built, detail = rebuild_derived_lane(settings, ages["mitomap_miss"])
    assert built is True, detail
    assert _builder_version(copy) == installed_enricher()
    assert {age.lane: age.stale for age in derived_lane_ages(settings)}["mitomap_miss"] is False
