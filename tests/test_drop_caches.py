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
from just_dna_registry.services import cache_drop, enrich, lane_readers


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
    partial = base / "mane"
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
        "mane": _lane("mane", partial, "pull"),
        "civic": _lane("civic", base / "civic", "pull"),
    }
    state = {"present": dict(dirs)}

    def presence(settings: object) -> dict[str, Path | None]:
        return {
            name: (where if where.is_dir() else None) if (where := state["present"].get(name)) else None
            for name in lanes
        }

    monkeypatch.setattr(lane_readers, "cache_lanes", lambda: lanes)
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
    # The present lanes, largest first, then the partial one (0.28.6: through 0.28.5 it was not listed).
    assert set(rows) == {*box.dirs, "mane"} and rows[0] == "alphagenome_avi" and rows[-1] == "mane", out
    assert "mane partial (not a snapshot)" in out and "--leftovers --apply" in out, out
    clinvar = next(line for line in out.splitlines() if line.startswith("  clinvar"))
    assert "[publish; check: resolution; builds: mitomap_miss; proxy: derived, hints, drafts]" in clinvar, out
    assert "alphagenome_avi [nothing here]" in out
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
    assert code == 1 and "needs --force: read here [publish; check: resolution;" in out, out
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
    assert code == 1 and "mitomap_miss were built from it" in out, out


def test_a_lane_only_the_proxy_or_an_enrichment_reads_needs_force(box) -> None:
    """Through 0.28.3 these read as "not read here" and went without --force: the drafts route opens
    `mitomap_miss`, and every enrichment opens `civic`, and `mitomap_miss` is built from `mitomap`."""
    for name, reader in (("mitomap_miss", "proxy: drafts"), ("mitomap", "builds: mitomap_miss")):
        code, out = _run("--lane", name, "--apply")
        assert code == 1 and reader in out and "needs --force" in out, out
    _intact(box)


def test_a_partial_directory_is_removable_and_says_so(box) -> None:
    code, out = _run("--lane", "mane", "--apply")
    assert code == 0 and "mane [nothing here] partial" in out, out
    assert not box.partial.exists()


def test_leftovers_go_and_the_live_lane_stays(box) -> None:
    """Sibling leftovers, the partial lane (0.28.6), and what an interrupted fetch or build left inside a
    present lane go; every present lane's `data/` stays whole."""
    clinvar = box.dirs["clinvar"]
    (clinvar / "data" / "chr2.parquet.part").write_bytes(b"p" * 3)
    (clinvar / "data.building").mkdir()
    (clinvar / "data.building" / "variants.parquet").write_bytes(b"b" * 4)
    (clinvar / "source" / "25.09" / "variant").mkdir(parents=True)
    (clinvar / "source" / "25.09" / "variant" / "part-0.parquet.part").write_bytes(b"s" * 6)
    data_before = {lane: sorted((where / "data").iterdir()) for lane, where in box.dirs.items()}

    code, out = _run("--leftovers")
    assert code == 0 and "mane [nothing here] partial" in out, out
    junk = {clinvar / "data" / "chr2.parquet.part", clinvar / "data.building", clinvar / "source"}
    listed = {Path(line.split(": ", 1)[1].split(" — ")[0]) for line in out.splitlines() if "leftover:" in line}
    # Outermost only: the `.part` inside `source/` goes with it rather than as a line of its own.
    assert listed == {*junk, box.leftover}, out
    assert all(path.exists() for path in junk) and box.partial.is_dir(), "the dry run removed something"

    code, out = _run("--leftovers", "--apply")
    assert code == 0 and "leftover" in out, out
    assert not box.leftover.exists() and not box.partial.exists()
    assert not any(path.exists() for path in junk), out
    assert box.dirs["mitomap_miss"].is_dir()
    assert {
        lane: sorted((where / "data").iterdir()) for lane, where in box.dirs.items()
    } == {**data_before, "clinvar": [p for p in data_before["clinvar"] if not p.name.endswith(".part")]}


def test_the_inner_leftover_names_are_upstreams(box) -> None:
    """`INNER_LEFTOVERS` names upstream's private staging; read each off the enricher, so a rename upstream
    fails here rather than leaving a cut-off download on the disk unnoticed."""
    import inspect

    from just_dna_enricher import caches, net, opentargets_build

    assert cache_drop.INNER_LEFTOVERS, "nothing to look for"
    assert '".part"' in inspect.getsource(net.stream_to_file)
    assert '"data.building"' in inspect.getsource(opentargets_build.build_snapshot)
    assert '/ "source" /' in inspect.getsource(caches._rebuild_opentargets)


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
