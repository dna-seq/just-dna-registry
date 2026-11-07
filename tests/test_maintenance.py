"""The maintenance run's core: log, snapshot, storage journal, and a revert that reads itself back.

The per-command half (every `registry` command, seeded catalog, revert to the byte) is
`test_maintenance_commands.py`; this file drives `maintenance_run` and `revert_run` directly.
"""

import gzip
import json
import logging
import sqlite3
import sys
import threading
from pathlib import Path

import click
import pytest

from just_dna_registry.config import Settings
from just_dna_registry.maintenance import (
    SNAPSHOT_FILE,
    RevertRefused,
    Run,
    apply_prune,
    db_digest,
    disk_usage,
    journaled,
    list_runs,
    maintenance_run,
    plan_prune,
    quiet_console,
    read_record,
    revert_run,
    run_root,
)
from just_dna_registry.storage.local import LocalStorage


def _settings(tmp_path: Path) -> Settings:
    db = tmp_path / "db" / "registry.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES ('a', '1')")
    conn.commit()
    conn.close()
    return Settings(db_path=db, run_dir=tmp_path / "runs", local_storage_dir=tmp_path / "store")


def _write(settings: Settings, sql: str) -> None:
    conn = sqlite3.connect(settings.db_path)
    conn.execute(sql)
    conn.commit()
    conn.close()


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _dirs(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}


def test_default_root_is_beside_the_db(tmp_path: Path) -> None:
    assert run_root(Settings(db_path=tmp_path / "x" / "r.db")) == (tmp_path / "x" / "runs").resolve()


def test_a_changing_run_keeps_log_snapshot_and_journal_and_reverts_without_remnants(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = LocalStorage(settings.local_storage_dir)
    store.store_module("ns/kept/1.0.0", {"manifest.json": b"old", "data/a.parquet": b"A"})
    store.store_module("ns/gone/1.0.0", {"manifest.json": b"bye", "logs/x.log": b"L"})
    db_before, tree_before, dirs_before = db_digest(settings.db_path), _tree(store.root), _dirs(store.root)

    with maintenance_run(settings, "rename-account", "registry rename-account a b --apply") as run:
        storage = journaled(store)
        storage.store_module("ns/kept/1.0.0", {"manifest.json": b"new"})          # overwrite
        storage.store_module("ns/new/1.0.1", {"deep/nested/f.parquet": b"N"})     # add, new dirs
        storage.remove("ns/gone/1.0.0")                                           # remove
        _write(settings, "UPDATE t SET v = '2' WHERE k = 'a'")
        click.echo("did it")
        logging.getLogger("just_dna_registry.x").info("a record")

    record = read_record(run.path)
    assert record["changed"] is True and record["outcome"] == "ok" and record["db_before"] == db_before
    assert db_digest(run.path / SNAPSHOT_FILE) == db_before
    log = (run.path / "run.log").read_text()
    assert log.startswith("# registry rename-account a b --apply") and "did it" in log and "a record" in log
    journal = [json.loads(line) for line in (run.path / "journal.jsonl").read_text().splitlines()]
    assert [e["op"] for e in journal] == ["overwrite", "add", "remove", "remove"]

    with maintenance_run(settings, "revert-run", "registry revert-run") as reverting:
        report = revert_run(settings, run.id, journaled(store))
    assert report.files_restored == 3 and report.files_removed == 1
    assert db_digest(settings.db_path) == db_before
    assert _tree(store.root) == tree_before and _dirs(store.root) == dirs_before
    assert read_record(run.path)["reverted_by"] == reverting.id
    assert read_record(reverting.path)["reverts"] == run.id


def test_a_revert_is_revertible(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = LocalStorage(settings.local_storage_dir)
    with maintenance_run(settings, "remove-version", "x") as run:
        journaled(store).store_module("ns/m/1.0.1", {"manifest.json": b"m"})
        _write(settings, "INSERT INTO t VALUES ('b', '2')")
    after_db, after_tree = db_digest(settings.db_path), _tree(store.root)
    with maintenance_run(settings, "revert-run", "x") as first:
        revert_run(settings, run.id, journaled(store))
    with maintenance_run(settings, "revert-run", "x"):
        revert_run(settings, first.id, journaled(store))
    assert db_digest(settings.db_path) == after_db and _tree(store.root) == after_tree
    assert read_record(run.path)["reverted_by"] is None, "the reverted run is live again"


def test_older_runs_revert_newest_first(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with maintenance_run(settings, "site-admin", "x") as older:
        _write(settings, "INSERT INTO t VALUES ('b', '2')")
    with maintenance_run(settings, "site-admin", "x"):
        _write(settings, "INSERT INTO t VALUES ('c', '3')")
    with pytest.raises(RevertRefused, match="newer run"):
        revert_run(settings, older.id, LocalStorage(settings.local_storage_dir))


def test_a_change_since_the_run_refuses_unless_forced(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = LocalStorage(settings.local_storage_dir)
    with maintenance_run(settings, "site-admin", "x") as run:
        journaled(store).store_module("ns/m/1.0.1", {"manifest.json": b"m"})
        _write(settings, "INSERT INTO t VALUES ('b', '2')")
    before = read_record(run.path)["db_before"]
    _write(settings, "INSERT INTO t VALUES ('server', 'wrote')")  # a write the run did not make
    store.store_module("ns/m/1.0.1", {"manifest.json": b"someone else"})
    with pytest.raises(RevertRefused, match="the catalog DB") as refused:
        revert_run(settings, run.id, store)
    assert "ns/m/1.0.1/manifest.json" in str(refused.value)
    revert_run(settings, run.id, store, force=True)
    assert db_digest(settings.db_path) == before and not store.exists("ns/m/1.0.1", "manifest.json")


def test_an_unchanged_run_leaves_nothing_unless_its_report_is_the_point(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with maintenance_run(settings, "list-members", "x"):
        click.echo("read only")
    with maintenance_run(settings, "upgrade", "registry upgrade --dry-run") as kept:
        click.echo("held ns/m@1.0.0: needs --online")
    assert [p.name for p in list_runs(settings)] == [kept.id]
    assert (kept.path / "run.log").is_file() and not (kept.path / SNAPSHOT_FILE).exists()
    assert "held ns/m@1.0.0" in (kept.path / "run.log").read_text()


def test_a_failed_run_is_kept_and_says_how_it_ended(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(click.exceptions.Exit), maintenance_run(settings, "site-admin", "x") as run:
        raise click.exceptions.Exit(1)
    assert read_record(run.path)["outcome"] == "failed: Exit (exit 1)"
    with pytest.raises(click.exceptions.Exit), maintenance_run(settings, "site-admin", "x") as ok:
        raise click.exceptions.Exit(0)  # typer.Exit() is a success, not a failure
    assert not ok.path.exists()


def test_two_runs_in_one_instant_get_two_directories(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with maintenance_run(settings, "upgrade", "a") as first, maintenance_run(settings, "upgrade", "b") as second:
        pass
    assert first.path != second.path


def test_a_stream_captured_during_the_run_still_works_after_it(tmp_path: Path) -> None:
    """A handler built inside the run holds the tee; logging flushes it at exit, after the log closed."""
    settings = _settings(tmp_path)
    with maintenance_run(settings, "upgrade", "x") as run:
        captured = logging.StreamHandler(sys.stdout)
    captured.stream.write("after the run\n")
    captured.flush()
    assert "after the run" not in (run.path / "run.log").read_text()


def test_no_db_before_reverts_to_no_db(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "fresh.db", run_dir=tmp_path / "runs")
    with maintenance_run(settings, "init-db", "x") as run:
        sqlite3.connect(settings.db_path).execute("CREATE TABLE t (k)").connection.commit()
    assert read_record(run.path)["db_before"] is None and not (run.path / SNAPSHOT_FILE).exists()
    revert_run(settings, run.id, LocalStorage(tmp_path / "store"))
    assert not settings.db_path.exists()


def test_an_api_key_never_reaches_the_log(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with maintenance_run(settings, "issue-key", "x") as run:
        click.echo("API key: mk_live_AbC-123_xyz")
        logging.getLogger("just_dna_registry.x").warning("key mk_test_Q9 leaked into a record")
        _write(settings, "INSERT INTO t VALUES ('k', 'v')")
    log = (run.path / "run.log").read_text()
    assert "mk_live_AbC" not in log and "mk_test_Q9" not in log
    assert "mk_live_…(redacted)" in log and "mk_test_…(redacted)" in log


def test_walking_back_newest_first_passes_a_revert_and_its_target(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = LocalStorage(settings.local_storage_dir)
    original = db_digest(settings.db_path)
    with maintenance_run(settings, "feature", "x") as a:
        _write(settings, "INSERT INTO t VALUES ('a2', '1')")
    with maintenance_run(settings, "set-funding", "x") as b:
        _write(settings, "INSERT INTO t VALUES ('b', '1')")
    with maintenance_run(settings, "revert-run", "x"):
        revert_run(settings, b.id, store)
    with maintenance_run(settings, "revert-run", "x"):
        revert_run(settings, a.id, store)
    assert db_digest(settings.db_path) == original


def test_a_failed_run_that_changed_nothing_keeps_no_snapshot(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(click.exceptions.Exit), maintenance_run(settings, "revert-run", "x") as run:
        raise click.exceptions.Exit(1)
    assert (run.path / "run.log").is_file() and not (run.path / SNAPSHOT_FILE).exists()


def test_the_snapshot_and_the_captures_are_stored_gzipped_and_revert_to_the_byte(tmp_path: Path) -> None:
    """0.28.2: a run's catalog copy and its captured prior bytes are compressed, and come back exact."""
    settings = _settings(tmp_path)
    # Compressible on purpose, so "smaller than the source" is a property and not luck.
    _write(settings, "INSERT INTO t VALUES ('pad', '" + "x" * 200_000 + "')")
    store = LocalStorage(settings.local_storage_dir)
    prior = b"parquet-ish " * 10_000
    store.store_module("ns/m/1.0.0", {"data/a.parquet": prior})
    db_before, tree_before = db_digest(settings.db_path), _tree(store.root)

    with maintenance_run(settings, "rename-account", "x") as run:
        journaled(store).store_module("ns/m/1.0.0", {"data/a.parquet": b"new"})
        _write(settings, "UPDATE t SET v = '2' WHERE k = 'a'")

    snapshot = run.path / SNAPSHOT_FILE
    assert snapshot.name.endswith(".gz") and not (run.path / "db.sqlite").exists()
    assert gzip.decompress(snapshot.read_bytes())[:16] == b"SQLite format 3\x00"
    assert snapshot.stat().st_size < settings.db_path.stat().st_size
    assert db_digest(snapshot) == db_before
    [entry] = [json.loads(line) for line in (run.path / "journal.jsonl").read_text().splitlines()]
    capture = run.path / entry["before"]
    assert capture.suffix == ".gz" and gzip.decompress(capture.read_bytes()) == prior
    assert capture.stat().st_size < len(prior)
    assert not list(run.path.glob(".*.tmp")), "the backup API's temporary file was left behind"

    revert_run(settings, run.id, store)
    assert db_digest(settings.db_path) == db_before and _tree(store.root) == tree_before


def test_a_run_written_raw_by_0_28_1_still_reverts(tmp_path: Path) -> None:
    """The polygon holds runs from before compression: raw `db.sqlite` and raw captures."""
    settings = _settings(tmp_path)
    store = LocalStorage(settings.local_storage_dir)
    store.store_module("ns/m/1.0.0", {"manifest.json": b"old"})
    db_before, tree_before = db_digest(settings.db_path), _tree(store.root)
    with maintenance_run(settings, "rename-account", "x") as run:
        journaled(store).store_module("ns/m/1.0.0", {"manifest.json": b"new"})
        _write(settings, "INSERT INTO t VALUES ('b', '2')")

    # Rewrite the run as 0.28.1 left it.
    (run.path / "db.sqlite").write_bytes(gzip.decompress((run.path / SNAPSHOT_FILE).read_bytes()))
    (run.path / SNAPSHOT_FILE).unlink()
    journal = run.path / "journal.jsonl"
    entries = [json.loads(line) for line in journal.read_text().splitlines()]
    for entry in entries:
        packed = run.path / entry["before"]
        raw = packed.with_suffix("")
        raw.write_bytes(gzip.decompress(packed.read_bytes()))
        packed.unlink()
        entry["before"] = raw.relative_to(run.path).as_posix()
    journal.write_text("".join(json.dumps(e) + "\n" for e in entries))

    revert_run(settings, run.id, store)
    assert db_digest(settings.db_path) == db_before and _tree(store.root) == tree_before


def test_quiet_console_keeps_warnings_off_the_terminal_and_in_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`upgrade`'s sweep prints one line per module; an upstream warning goes to run.log, not between them."""
    settings = _settings(tmp_path)
    # With no root handler the run adds its own terminal handler, which is the CLI's situation (pytest
    # installs root handlers of its own, so they are set aside for this test).
    monkeypatch.setattr(logging.getLogger(), "handlers", [])
    upstream = logging.getLogger("just_dna_enricher.enrich")
    with maintenance_run(settings, "upgrade", "x") as run:
        assert run.console is not None
        with quiet_console():
            upstream.warning("quietened drift note")
            upstream.error("an error still shows")
        upstream.warning("loud note")
    err = capsys.readouterr().err
    assert "quietened drift note" not in err
    assert "an error still shows" in err and "loud note" in err
    log = (run.path / "run.log").read_text()
    assert "quietened drift note" in log and "loud note" in log


# ── Pruning (0.28.2) ─────────────────────────────────────────────────────────────────────────────────


def _changing_runs(settings: Settings, store: LocalStorage, count: int) -> list[tuple[Run, str | None, dict[str, bytes]]]:
    """`count` runs, each adding a stored file and a row; with the state *before* each one."""
    made = []
    for i in range(count):
        before = (db_digest(settings.db_path), _tree(store.root) if store.root.is_dir() else {})
        with maintenance_run(settings, "site-admin", f"x{i}") as run:
            journaled(store).store_module(f"ns/m/1.0.{i}", {"manifest.json": b"m" * (1000 + i)})
            _write(settings, f"INSERT INTO t VALUES ('k{i}', '{i}')")
        made.append((run, *before))
    return made


def test_prune_keeps_the_newest_two_revertible_runs_whole_and_the_rest_their_logs(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"run_keep": 0})  # no auto-prune: the call is the test
    store = LocalStorage(settings.local_storage_dir)
    made = _changing_runs(settings, store, 5)
    runs = [run for run, _, _ in made]

    plan = plan_prune(settings, 2)
    assert [name for name, _ in plan.prune] == [run.id for run in runs[:3]]
    assert set(plan.whole) == {runs[3].id, runs[4].id}
    expected = sum(disk_usage(r.path / SNAPSHOT_FILE) + disk_usage(r.path / "journal.jsonl")
                   + disk_usage(r.path / "storage") for r in runs[:3])
    assert plan.freed == expected > 0
    assert all((r.path / SNAPSHOT_FILE).is_file() for r in runs), "planning deleted something"

    assert apply_prune(settings, plan) == expected
    for run in runs[:3]:
        assert sorted(p.name for p in run.path.iterdir()) == ["run.json", "run.log"]
        record = read_record(run.path)
        assert record["pruned"] and record["pruned_bytes"] > 0 and record["changed"] is True
        with pytest.raises(RevertRefused, match="pruned"):
            revert_run(settings, run.id, store)
    assert plan_prune(settings, 2).prune == [], "a second prune finds nothing left to free"

    # The two kept whole revert to the byte, newest first.
    _, db_before_fourth, tree_before_fourth = made[3]
    revert_run(settings, runs[4].id, store)
    revert_run(settings, runs[3].id, store)
    assert db_digest(settings.db_path) == db_before_fourth
    assert _tree(store.root) == tree_before_fourth


def test_every_run_prunes_at_its_end_per_run_keep(tmp_path: Path) -> None:
    settings = _settings(tmp_path)  # run_keep defaults to 2
    assert settings.run_keep == 2
    store = LocalStorage(settings.local_storage_dir)
    runs = [run for run, _, _ in _changing_runs(settings, store, 3)]
    assert read_record(runs[0].path).get("pruned") and not (runs[0].path / SNAPSHOT_FILE).exists()
    assert all((r.path / SNAPSHOT_FILE).is_file() and not read_record(r.path).get("pruned") for r in runs[1:])


def test_run_keep_zero_turns_the_automatic_prune_off(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"run_keep": 0})
    store = LocalStorage(settings.local_storage_dir)
    runs = [run for run, _, _ in _changing_runs(settings, store, 4)]
    assert all((r.path / SNAPSHOT_FILE).is_file() and not read_record(r.path).get("pruned") for r in runs)


def test_the_newest_replays_keep_their_scratch_tree(tmp_path: Path) -> None:
    """A replay changes nothing, so it is never revertible; its tree is kept on the same count."""
    settings = _settings(tmp_path).model_copy(update={"run_keep": 0})
    replays = []
    for i in range(3):
        with maintenance_run(settings, "replay-upgrade", f"r{i}") as run:
            (run.path / "replay" / "storage").mkdir(parents=True)
            (run.path / "replay" / "catalog.db").write_bytes(b"c" * 100)
        replays.append(run)
    plan = plan_prune(settings, 2)
    assert [name for name, _ in plan.prune] == [replays[0].id]
    apply_prune(settings, plan)
    assert not (replays[0].path / "replay").exists() and (replays[0].path / "run.log").is_file()
    assert all((r.path / "replay" / "catalog.db").is_file() for r in replays[1:])


def test_the_run_that_is_ending_is_never_pruned_by_its_own_end(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"run_keep": 0})
    runs = [run for run, _, _ in _changing_runs(settings, LocalStorage(settings.local_storage_dir), 3)]
    plan = plan_prune(settings, 1, exclude=runs[0].id)
    assert [name for name, _ in plan.prune] == [runs[1].id]
    assert runs[0].id in plan.whole


def test_a_journal_written_from_many_threads_stays_whole_and_reverts_to_the_byte(tmp_path: Path) -> None:
    """`upgrade --jobs` publishes from several threads, and the journal must hold up on its own.

    A capture file is named by the entry's index, so two unsynchronized writers can take the same
    index and one prior state is lost: the revert then restores the wrong bytes to one of the two
    files. Many writers overwrite distinct files at once; every entry must have its own capture, the
    journal file must agree with the run's entries, and the revert must put back every byte.
    """
    settings = _settings(tmp_path)
    store = LocalStorage(settings.local_storage_dir)
    writers, rounds = 12, 15
    for w in range(writers):
        store.store_module(f"ns/m{w}/1.0.0", {f"f{r}.csv": f"old {w} {r}".encode() for r in range(rounds)})
    tree_before = _tree(store.root)
    start = threading.Barrier(writers)

    with maintenance_run(settings, "upgrade", "registry upgrade --apply --jobs 12") as run:
        storage = journaled(store)

        def write(w: int) -> None:
            start.wait()
            for r in range(rounds):
                storage.store_module(f"ns/m{w}/1.0.0", {f"f{r}.csv": f"new {w} {r}".encode()})

        threads = [threading.Thread(target=write, args=(w,)) for w in range(writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    journal = [json.loads(line) for line in (run.path / "journal.jsonl").read_text().splitlines()]
    assert len(journal) == len(run.entries) == writers * rounds
    captures = [e["before"] for e in journal]
    assert len(set(captures)) == len(captures), "two entries share one capture file"
    assert {e["op"] for e in journal} == {"overwrite"}

    with maintenance_run(settings, "revert-run", "registry revert-run"):
        revert_run(settings, run.id, journaled(store))
    assert _tree(store.root) == tree_before
