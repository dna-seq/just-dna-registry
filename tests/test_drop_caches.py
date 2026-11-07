"""`registry drop-caches` removes a snapshot lane from this box, and nothing beside it.

The lane registry is replaced by stand-ins resolving under a temporary cache base, so nothing here
reads or deletes the machine's real caches. The stand-ins keep the two properties the command reads
off a real lane: its route (`ensure` / `rebuild`) and its `parents`. The group a pass here reads a lane
under comes from the real `LANE_GROUPS`, which is why the stand-ins carry real lane names.
"""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from just_dna_registry import cli
from just_dna_registry.services import cache_drop, enrich


def _lane(name: str, where: Path, route: str, parents: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        ensure=(lambda: where) if route == "pull" else None,
        rebuild=(lambda request: None) if route == "build" else None,
        parents=parents,
        unpublished="needs a personal key" if route == "build" else None,
        unbuilt=None,
        default_dir=lambda: where,
    )


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    base = tmp_path / "cache"
    dirs = {name: base / name for name in ("alphagenome_avi", "clinvar", "pharmvar", "mitomap", "mitomap_miss")}
    for name, where in dirs.items():
        (where / "data").mkdir(parents=True)
        (where / "data" / "part.parquet").write_bytes(b"x" * (1000 if name == "alphagenome_avi" else 10))
    partial = base / "civic"
    partial.mkdir()
    (partial / "download.part").write_bytes(b"y" * 5)
    leftover = base / "mitomap_miss.pre-0.8.0"
    (leftover / "data").mkdir(parents=True)
    (leftover / "data" / "old.parquet").write_bytes(b"z" * 7)

    lanes = {
        "alphagenome_avi": _lane("alphagenome_avi", dirs["alphagenome_avi"], "pull"),
        "clinvar": _lane("clinvar", dirs["clinvar"], "pull"),
        "pharmvar": _lane("pharmvar", dirs["pharmvar"], "build"),
        "mitomap": _lane("mitomap", dirs["mitomap"], "pull"),
        "mitomap_miss": _lane("mitomap_miss", dirs["mitomap_miss"], "build", parents=("mitomap", "clinvar")),
        "civic": _lane("civic", partial, "pull"),
    }
    state = {"present": dict(dirs)}

    def presence(settings: object) -> dict[str, Path | None]:
        return {
            name: (where if where.is_dir() else None) if (where := state["present"].get(name)) else None
            for name in lanes
        }

    for module in (enrich, cache_drop):
        monkeypatch.setattr(module, "cache_lanes", lambda: lanes)
        monkeypatch.setattr(module, "lane_presence", presence)
        monkeypatch.setattr(module, "lane_destinations", lambda settings: dict.fromkeys(lanes))
    monkeypatch.setattr(enrich, "enricher_available", lambda: True)
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "data" / "registry.db"))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "artifacts"))
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(tmp_path / "runs"))
    cli.get_settings.cache_clear()
    yield SimpleNamespace(base=base, dirs=dirs, lanes=lanes, partial=partial, leftover=leftover,
                          state=state, runs=tmp_path / "runs")
    cli.get_settings.cache_clear()


def _run(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(cli.app, ["drop-caches", *args])
    return result.exit_code, result.output


def _intact(box: SimpleNamespace, *except_: str) -> None:
    for name, where in box.dirs.items():
        assert where.is_dir() == (name not in except_), name
    assert box.partial.is_dir() and box.leftover.is_dir()


def test_with_no_lane_it_lists_what_holds_the_disk_largest_first(box) -> None:
    code, out = _run()
    rows = [line.split()[0] for line in out.splitlines() if line.startswith("  ")]
    assert code == 0, out
    assert set(rows) == set(box.dirs) and rows[0] == "alphagenome_avi", out
    assert "[resolution]" in next(line for line in out.splitlines() if line.startswith("  clinvar"))
    _intact(box)


def test_the_dry_run_removes_nothing_and_names_the_restore(box) -> None:
    code, out = _run("--lane", "alphagenome_avi")
    assert code == 0, out
    assert "would be freed" in out and "restore: registry warm-caches --lane alphagenome_avi --apply" in out
    _intact(box)


def test_apply_removes_the_lane_and_only_the_lane(box) -> None:
    code, out = _run("--lane", "alphagenome_avi", "--apply")
    assert code == 0, out
    _intact(box, "alphagenome_avi")
    assert not any(p.name.startswith(".alphagenome_avi.dropping-") for p in box.base.iterdir())


def test_the_removal_is_in_the_run_log(box) -> None:
    code, out = _run("--lane", "alphagenome_avi", "--apply")
    logs = list(box.runs.glob("*-drop-caches/run.log"))
    assert code == 0 and len(logs) == 1, (out, list(box.runs.glob("*")))
    assert str(box.dirs["alphagenome_avi"]) in logs[0].read_text()


def test_a_lane_read_here_needs_force(box) -> None:
    code, out = _run("--lane", "clinvar", "--apply")
    assert code == 1 and "needs --force: read here (resolution)" in out, out
    _intact(box)
    code, out = _run("--lane", "clinvar", "--apply", "--force")
    assert code == 0, out
    _intact(box, "clinvar")


def test_a_lane_nothing_publishes_needs_force_and_says_why(box) -> None:
    code, out = _run("--lane", "pharmvar")
    assert code == 1, out
    assert "no published snapshot to pull back (needs a personal key)" in out
    assert "restore:" not in out


def test_one_blocked_lane_blocks_the_whole_selection(box) -> None:
    code, out = _run("--lane", "alphagenome_avi", "--lane", "clinvar", "--apply")
    assert code == 1 and "nothing removed" in out, out
    _intact(box)


def test_a_parent_names_the_derived_lanes_built_from_it(box) -> None:
    code, out = _run("--lane", "mitomap")
    assert code == 0 and "mitomap_miss were built from it" in out, out


def test_a_partial_directory_is_removable_and_says_so(box) -> None:
    code, out = _run("--lane", "civic", "--apply")
    assert code == 0 and "civic [not read here] partial" in out, out
    assert not box.partial.exists()


def test_leftovers_go_and_the_live_lane_stays(box) -> None:
    code, out = _run("--leftovers", "--apply")
    assert code == 0 and "leftover" in out, out
    assert not box.leftover.exists()
    assert box.dirs["mitomap_miss"].is_dir() and box.partial.is_dir()


@pytest.mark.parametrize("target", ["base", "catalog", "symlink"])
def test_a_directory_holding_anything_else_is_refused_even_with_force(box, tmp_path, target) -> None:
    if target == "base":
        where = box.base
    elif target == "catalog":
        where = tmp_path / "data"
        where.mkdir(exist_ok=True)
        sqlite3.connect(where / "registry.db").close()
    else:
        where = tmp_path / "link"
        where.symlink_to(box.dirs["alphagenome_avi"], target_is_directory=True)
    box.lanes["alphagenome_avi"] = _lane("alphagenome_avi", where, "pull")
    box.state["present"]["alphagenome_avi"] = where
    code, out = _run("--lane", "alphagenome_avi", "--apply", "--force")
    assert code == 1 and "refused:" in out, out
    assert box.dirs["alphagenome_avi"].is_dir() and box.dirs["clinvar"].is_dir()
    assert (target != "catalog") or (tmp_path / "data" / "registry.db").exists()


def test_an_unknown_lane_is_a_usage_error(box) -> None:
    code, out = _run("--lane", "alphagenom")
    assert code == 2 and "unknown lane(s): alphagenom" in out, out
