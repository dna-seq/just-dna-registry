"""`replay_upgrade`: run the upgrade sweep again over a scratch copy, to recover a lost run's report.

The sweep is the real one (`cli._upgrade_sweep`) and the publish under it is real, offline against
this box's snapshot. What the tests hold is the replay's promise: it names what the original run did
to each predecessor, it says what the lost terminal said about modules that got no successor, and the
real catalog and storage are exactly as they were.
"""

import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_rederive_sweep import _NAME, _NS, _STUDIES, _VARIANTS, _YAML, _as_0_7_table, _publish
from typer.testing import CliRunner

from just_dna_registry import cli
from just_dna_registry.config import Settings, get_settings
from just_dna_registry.maintenance import SNAPSHOT_FILE
from just_dna_registry.replay import (
    NOT_REPLAYED,
    NOT_REPUBLISHED,
    ONLINE_MARK,
    SAME,
    SAME_CONTENT,
    OverlayStorage,
    ReplayRefused,
    SweepLines,
    find_successors,
    original_online,
    replay_upgrade,
)
from just_dna_registry.services.enrich import EnrichOutcome, rederive_changelog
from just_dna_registry.services.publish import PublishError
from just_dna_registry.storage.base import StorageBackend, version_key
from just_dna_registry.storage.local import LocalStorage

# ── OverlayStorage ───────────────────────────────────────────────────────────────────────────────────


def _tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture
def overlay(tmp_path: Path) -> tuple[OverlayStorage, LocalStorage]:
    base = LocalStorage(tmp_path / "base")
    base.store_module("ns/mod/1.0.0", {"a.parquet": b"A", "logs/x.log": b"X"})
    base.store_module("ns/mod/1.0.1", {"b.parquet": b"B"})
    return OverlayStorage(base, LocalStorage(tmp_path / "scratch")), base


def test_the_overlay_is_a_storage_backend(overlay) -> None:
    assert isinstance(overlay[0], StorageBackend)
    assert overlay[0].file_url("ns/mod/1.0.0", "a.parquet") is None


def test_reads_fall_through_to_the_base(overlay) -> None:
    view, _ = overlay
    assert view.exists("ns/mod/1.0.0", "logs/x.log")
    assert view.read_file("ns/mod/1.0.0", "a.parquet") == b"A"
    assert not view.exists("ns/mod/1.0.0", "absent")


def test_writes_land_in_scratch_and_answer_first(overlay, tmp_path: Path) -> None:
    view, base = overlay
    before = _tree(tmp_path / "base")
    view.store_module("ns/mod/1.0.0", {"a.parquet": b"A2", "new.csv": b"N"})
    assert view.read_file("ns/mod/1.0.0", "a.parquet") == b"A2"
    assert view.read_file("ns/mod/1.0.0", "new.csv") == b"N"
    assert base.read_file("ns/mod/1.0.0", "a.parquet") == b"A"
    assert not base.exists("ns/mod/1.0.0", "new.csv")
    assert _tree(tmp_path / "base") == before


def test_a_removal_is_a_tombstone_never_forwarded(overlay, tmp_path: Path) -> None:
    view, _ = overlay
    before = _tree(tmp_path / "base")
    assert before, "the base must hold something for its untouched-ness to mean anything"
    view.remove_file("ns/mod/1.0.0", "a.parquet")
    assert not view.exists("ns/mod/1.0.0", "a.parquet")
    with pytest.raises(FileNotFoundError):
        view.read_file("ns/mod/1.0.0", "a.parquet")
    view.remove("ns/mod/1.0.1")
    assert view.list_files("ns/mod/1.0.1") == []
    assert not view.exists("ns/mod/1.0.1", "b.parquet")
    assert _tree(tmp_path / "base") == before
    # Storing again lifts the tombstone: the scratch copy answers.
    view.store_module("ns/mod/1.0.1", {"b.parquet": b"B2"})
    assert view.read_file("ns/mod/1.0.1", "b.parquet") == b"B2"
    assert _tree(tmp_path / "base") == before


def test_list_files_merges_both_minus_tombstones(overlay) -> None:
    view, base = overlay
    view.store_module("ns/mod/1.0.0", {"logs/y.log": b"Y"})
    view.remove_file("ns/mod/1.0.0", "a.parquet")
    assert base.list_files("ns/mod/1.0.0") == ["a.parquet", "logs/x.log"]
    assert view.list_files("ns/mod/1.0.0") == ["logs/x.log", "logs/y.log"]
    assert view.list_files("ns/mod") == ["1.0.0/logs/x.log", "1.0.0/logs/y.log", "1.0.1/b.parquet"]


# ── The online mark and the line parse ───────────────────────────────────────────────────────────────


def test_the_online_mark_is_what_a_re_derivation_writes() -> None:
    # The replay derives `--online` from this phrase; a reworded changelog must fail here, not there.
    assert ONLINE_MARK in rederive_changelog(EnrichOutcome(ran=True, offline=False))
    assert ONLINE_MARK not in rederive_changelog(EnrichOutcome(ran=True, offline=True))


def test_sweep_lines_attach_indented_detail_to_their_label() -> None:
    text = (
        "mode=test db=x\n"
        "✗ ns/a@1.0.0: rederive_drift_needs_reading\n"
        "    rs1 moved: the source names a different event\n"
        "    rs2 lost_allele\n"
        "✓ ns/b@1.0.0 → 1.0.1 (contract recompile)\n"
        "    digest sha256:aa… → sha256:bb…\n"
        "\n"
        "1 version(s) upgraded and re-published, 1 refused (above), 1 held\n"
        "… held ns/c@2.0.0: carries an indel, which offline 0.8 cannot left-align; needs --online\n"
    )
    lines = SweepLines.parse(text)
    assert set(lines.refused) == {"ns/a@1.0.0"} and len(lines.refused["ns/a@1.0.0"]) == 3
    assert set(lines.published) == {"ns/b@1.0.0"} and len(lines.published["ns/b@1.0.0"]) == 2
    assert lines.held == {"ns/c@2.0.0": [text.splitlines()[-1]]}


# ── The replay, end to end ───────────────────────────────────────────────────────────────────────────


def _upgrade_apply(settings: Settings, monkeypatch) -> str:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(settings.local_storage_dir))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["upgrade", "--apply"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    return result.output


def _db_dump_digest(path: Path) -> str:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()
    finally:
        conn.close()


def _replay(settings: Settings, workdir: Path, **kwargs) -> object:
    options = {"since": None, "compiler": None, "online": False, "namespace": None, "module": None}
    options.update(kwargs)
    return replay_upgrade(
        settings, cli._storage(settings), sweep=cli._upgrade_sweep, workdir=workdir, **options
    )


def _refusing(real):
    """`upgrade_version` refusing `coronary_two` with drift to read, and running for real otherwise."""

    def upgrade_version(**kwargs):
        if kwargs["name"] == "coronary_two":
            raise PublishError(
                "rederive_drift_needs_reading", errors=["rs1801133 moved: the source names a different event"]
            )
        return real(**kwargs)

    return upgrade_version


@pytest.fixture
def upgraded(client: TestClient, api_key: str, app, settings: Settings, monkeypatch) -> str:
    """A catalog after a real `registry upgrade --apply`: `coronary` got 1.0.1, `coronary_two` refused."""
    _publish(client, api_key, name=_NAME)
    _publish(client, api_key, name="coronary_two")
    _as_0_7_table(app, name=_NAME)
    _as_0_7_table(app, name="coronary_two")
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    monkeypatch.setattr(cli, "upgrade_version", _refusing(cli.upgrade_version))
    out = _upgrade_apply(settings, monkeypatch)
    assert "1 version(s) upgraded and re-published, 1 refused" in out, out
    assert app.state.repo.version_exists(_NS, _NAME, "1.0.1")
    assert not app.state.repo.version_exists(_NS, "coronary_two", "1.0.1")
    return out


def test_find_successors_reads_the_predecessor_and_filters(upgraded, app) -> None:
    found = find_successors(app.state.repo)
    assert [(s.name, s.version, s.predecessor) for s in found] == [(_NAME, "1.0.1", "1.0.0")]
    assert found[0].digest.startswith("sha256:") and found[0].files
    compiler = found[0].compiler_version
    assert compiler and compiler.startswith("just-dna-compiler "), compiler  # a name, then the version
    bare = compiler.split()[-1]
    assert find_successors(app.state.repo, compiler=bare[:3]) == found  # "0.8" as an operator types it
    assert find_successors(app.state.repo, compiler="0.0") == []
    assert find_successors(app.state.repo, since="9999") == []
    assert find_successors(app.state.repo, module="coronary_two") == []
    # An offline run leaves no proof of its switch, so the replay cannot default it.
    assert original_online(found) is None


def test_the_replay_reproduces_the_run_and_touches_nothing_real(
    upgraded, app, settings: Settings, capsys, tmp_path: Path
) -> None:
    real_db = settings.db_path
    db_bytes = hashlib.sha256(real_db.read_bytes()).hexdigest()
    db_dump = _db_dump_digest(real_db)
    storage_before = _tree(settings.local_storage_dir)
    assert len(storage_before) >= 4, storage_before
    capsys.readouterr()

    report = _replay(settings, tmp_path / "replay")
    out = capsys.readouterr().out

    # The replay ran the real sweep and printed its summary, same distribution as the original.
    assert "1 version(s) upgraded and re-published, 1 refused" in out
    [entry] = report.entries
    assert entry.original.predecessor == "1.0.0" and entry.original.version == "1.0.1"
    assert entry.replayed is not None and entry.replayed.version == "1.0.1"
    assert entry.status in {SAME, SAME_CONTENT}, (entry.status, entry.reason, entry.moved_files)
    if entry.status == SAME_CONTENT:  # the digest names bytes; the files that moved are named
        assert entry.moved_files
    assert f"{_NS}/{_NAME}@1.0.0 → 1.0.1: {entry.status}" in out
    # The refusal the original printed and lost is in the report with its detail.
    refused = report.sweep.refused[f"{_NS}/coronary_two@1.0.0"]
    assert refused[0].endswith("rederive_drift_needs_reading")
    assert "rs1801133 moved: the source names a different event" in refused[1]
    assert "refused in the replay, no successor in the catalog (1)" in out
    assert "rs1801133 moved" in out.split("── replay against the original run ──")[1]

    # The real catalog and storage are exactly as they were; the replay's writes are in its workdir.
    assert report.live_db_unchanged
    assert hashlib.sha256(real_db.read_bytes()).hexdigest() == db_bytes
    assert _db_dump_digest(real_db) == db_dump
    assert _tree(settings.local_storage_dir) == storage_before
    scratch = tmp_path / "replay" / "storage" / version_key(_NS, _NAME, "1.0.1")
    assert (scratch / "manifest.json").is_file()


def test_a_module_held_in_the_replay_is_named_with_the_reason(
    upgraded, settings: Settings, monkeypatch, capsys, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: "pulled from the old release")
    report = _replay(settings, tmp_path / "replay")
    out = capsys.readouterr().out
    [entry] = report.entries
    assert entry.status == NOT_REPUBLISHED and entry.replayed is None
    assert entry.reason == "held: snapshot_not_current"
    assert entry.lines[1:] == ["    pulled from the old release"]
    summary = out.split("── replay against the original run ──")[1]
    assert (
        f"{_NS}/{_NAME}@1.0.0 → 1.0.1: {NOT_REPUBLISHED} — held: snapshot_not_current\n"
        "        pulled from the old release\n"
    ) in summary
    assert f"  … held {_NS}/coronary_two@1.0.0: snapshot_not_current\n      pulled from the old release" in summary


def test_only_a_modules_latest_successor_is_replayed(
    upgraded, settings: Settings, client: TestClient, api_key: str, tmp_path: Path
) -> None:
    # A version published by hand after the automated one: removing the successor would not make its
    # predecessor latest, so the replay says it cannot rather than replaying something else.
    resp = client.post(
        f"/api/v1/modules/{_NS}/{_NAME}/versions",
        data={"version": "1.0.2"},
        files=[
            ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    report = _replay(settings, tmp_path / "replay")
    [entry] = report.entries
    assert entry.original.version == "1.0.1"
    assert entry.status == NOT_REPLAYED and "1.0.2 follows it" in entry.reason


def test_the_replay_refuses_what_it_cannot_do_faithfully(upgraded, settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(ReplayRefused, match="--online or --offline"):
        _replay(settings, tmp_path / "a", online=None)
    busy = tmp_path / "b"
    busy.mkdir()
    (busy / "left-over").write_text("x")
    with pytest.raises(ReplayRefused, match="not empty"):
        _replay(settings, busy)
    with pytest.raises(ReplayRefused, match="no registry database"):
        _replay(settings.model_copy(update={"db_path": tmp_path / "nope.db"}), tmp_path / "c")


def test_the_command_replays_into_its_own_folder_and_logs_the_report(
    upgraded, settings: Settings, monkeypatch
) -> None:
    """`registry replay-upgrade` as an operator runs it: its report in a run log, the live catalog untouched."""
    db_dump = _db_dump_digest(settings.db_path)
    monkeypatch.setenv("REGISTRY_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(settings.local_storage_dir))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["replay-upgrade", "--offline", "--compiler", "0"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert "1 version(s) upgraded and re-published, 1 refused" in result.output
    (run,) = (settings.db_path.resolve().parent / "runs").glob("*-replay-upgrade")
    body = (run / "run.log").read_text()
    assert "── replay against the original run ──" in body and "rs1801133 moved" in body
    assert (run / "replay" / "catalog.db").is_file()
    assert not (run / SNAPSHOT_FILE).exists(), "the replay changed nothing live, so no snapshot is kept"
    assert _db_dump_digest(settings.db_path) == db_dump
