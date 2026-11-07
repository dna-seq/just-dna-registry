"""Every `registry` command is a maintenance run: logged, snapshotted before it acts, and revertible.

The commands are read off the CLI itself, deny by default: a command with no row here fails the test,
so a new command cannot ship without somebody stating how its changing path is exercised (or why it has
none). Each row runs against a fresh copy of one seeded catalog, and the oracle is the state itself:
`maintenance.db_digest` for the DB and a digest of every file *and directory* under the storage root.
A row that changed either must leave exactly one run carrying its log, a snapshot equal to the state
before it, and a record saying it changed; `revert-run` must then put the DB and the storage tree back
exactly, empty directories included. A row that changed nothing must leave nothing behind but the log
of a command whose report is the point (`maintenance.ALWAYS_LOG`).

The seed publishes for real (an enrich and a compile each), so it is built once per module and copied.
"""

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import typer
from click.testing import Result
from conftest import seed_into
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from just_dna_registry import cli, maintenance
from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect

NS = "just-dna-seq"
TEST_NS = "test-sandbox"
MOD = "coronary"
TEST_MOD = "test_probe"
#: Seeded without a compile (`seed_into`): two versions, so one can be removed and the module survives.
LEGACY = "legacy_panel"
ANTON_KEY = "mk_live_anton"
TESTER_KEY = "mk_live_tester"
BOB_KEY = "mk_live_bob"
CAROL_KEY = "mk_live_carol"

_YAML = """\
schema_version: "1.0"
module:
  name: {name}
  title: {title}
  description: d
  report_title: R
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,{weight},risk,het,CYP2C19,cyp2c19\n"
    "rs1801133,1,11796321,G,A,A/G,0.4,protective,het,MTHFR,folate\n"
)
_STUDIES = (
    "rsid,pmid,population,p_value,conclusion,study_design\n"
    "rs4244285,29165669,T,0.05,E,U\nrs1801133,29165669,T,0.05,E,U\n"
)


# ── The table: every command, deny by default ────────────────────────────────────────────────────────

#: The one command that is not a maintenance run, and why.
EXCLUDED: dict[str, str] = {
    "serve": "runs the API until stopped; its writes are requests, each under the request's own rules, "
             "and a run around it would call a day of traffic one command's change",
}

#: Commands with no path that changes the catalog DB or the storage tree, and why. Each still has a row,
#: which must change nothing.
REPORT_ONLY: dict[str, str] = {
    "list-members": "reads memberships",
    "list-org-members": "reads memberships",
    "list-backups": "lists snapshot files",
    "list-runs": "lists run directories",
    "export-keys": "writes the auth graph to stdout or a file outside the catalog",
    "backup": "writes a snapshot file beside the catalog, never into it",
    "warm-caches": "--apply provisions enricher snapshots over the network into the cache directories; "
                   "it touches neither the catalog DB nor storage, and pulling tens of GB is not a test",
    "replay-upgrade": "read-only on the real catalog by contract (it replays into a scratch copy)",
}


@dataclass(frozen=True)
class Box:
    """One row's private copy of the seeded catalog, and the directories the CLI is pointed at."""

    root: Path

    @property
    def db(self) -> Path:
        return self.root / "registry.db"

    @property
    def storage(self) -> Path:
        return self.root / "artifacts"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def inputs(self) -> Path:
        return self.root / "inputs"


@dataclass(frozen=True)
class Row:
    """One invocation. `argv` is formatted with `{root}`, `{inputs}` and whatever `setup` returns."""

    label: str
    argv: tuple[str, ...]
    changes: bool
    stdin: str | None = None
    setup: Callable[[Box], dict[str, str]] | None = None
    #: Exit codes this invocation may end with. Only `warm-caches --dry-run` widens it: it is a health
    #: check that exits 1 when a lane on this box needs provisioning, which is the box's state, not ours.
    exits: frozenset[int] = frozenset({0})

    @property
    def command(self) -> str:
        return self.argv[0]


def _drop_db(box: Box) -> dict[str, str]:
    """No catalog at all: the one state from which `init-db` changes something."""
    box.db.unlink()
    return {}


def _a_run_to_revert(box: Box) -> dict[str, str]:
    """A cheap changing run for the `revert-run` row to undo."""
    before = _run_names(box)
    result = _invoke(["feature", TEST_NS])
    assert result.exit_code == 0, result.output
    new = sorted(_run_names(box) - before)
    assert len(new) == 1, new
    return {"run": new[0]}


ROWS: tuple[Row, ...] = (
    Row("init-db/no-db", ("init-db",), True, setup=_drop_db),
    Row("init-db/existing", ("init-db",), False),
    Row("issue-key", ("issue-key", "erin", "-n", "erin-space"), True),
    Row("site-admin/grant", ("site-admin", "bob", "--grant"), True),
    Row("site-admin/show", ("site-admin", "bob"), False),
    Row("merge-accounts/apply", ("merge-accounts", "carol", "bob", "--apply", "--yes"), True),
    Row("merge-accounts/dry", ("merge-accounts", "carol", "bob"), False),
    Row("rename-account/apply", ("rename-account", "antonkulaga", "anton-renamed", "--apply", "--yes"), True),
    Row("rename-account/dry", ("rename-account", "antonkulaga", "anton-renamed"), False),
    Row("export-keys/stdout", ("export-keys",), False),
    Row("export-keys/file", ("export-keys", "--out", "{root}/auth-export.json"), False),
    Row("import-keys", ("import-keys", "{inputs}/import.json"), True),
    Row("reset-db", ("reset-db",), True, stdin="RESET\n"),
    Row("reset-db/wipe-keys", ("reset-db", "--wipe-keys"), True, stdin="RESET\n"),
    Row("add-member", ("add-member", NS, "carol", "--role", "admin"), True),
    Row("remove-member", ("remove-member", NS, "bob"), True),
    Row("list-members", ("list-members", NS), False),
    Row("create-org", ("create-org", "globex"), True),
    Row("add-org-member", ("add-org-member", "acme", "carol"), True),
    Row("remove-org-member", ("remove-org-member", "acme", "bob"), True),
    Row("list-org-members", ("list-org-members", "acme"), False),
    Row("set-funding", ("set-funding", "bob", "https://example.org/donate"), True),
    Row("remove-module", ("remove-module", NS, LEGACY, "--yes"), True),
    Row("remove-version", ("remove-version", NS, LEGACY, "1.0.0", "--yes"), True),
    Row("remove-namespace", ("remove-namespace", TEST_NS, "--yes"), True),
    Row("feature", ("feature", TEST_NS), True),
    Row("unfeature", ("unfeature", NS), True),
    Row("blacklist", ("blacklist", NS), True),
    Row("unblacklist", ("unblacklist", TEST_NS), True),
    Row("revalidate/set-flag", ("revalidate", "--set-flag"), True),
    Row("revalidate/report", ("revalidate",), False),
    Row("upgrade/apply", ("upgrade", "--apply", "--force", "-n", NS, "-m", MOD), True),
    # Every module at once on three workers: the journal of a parallel run reverts to the byte too.
    Row("upgrade/apply/jobs", ("upgrade", "--apply", "--force", "--jobs", "3"), True),
    Row("upgrade/dry", ("upgrade", "--dry-run"), False),
    Row("revoke-key", ("revoke-key", CAROL_KEY), True),
    Row("revoke-account", ("revoke-account", "carol", "--yes"), True),
    Row("warm-caches/dry", ("warm-caches", "--dry-run"), False, exits=frozenset({0, 1})),
    Row("rederive-signatures/apply", ("rederive-signatures", "--apply"), True),
    Row("rederive-signatures/dry", ("rederive-signatures", "--dry-run"), False),
    Row("backup", ("backup", "--reason", "enumeration"), False),
    Row("list-backups", ("list-backups",), False),
    Row("restore-backup", ("restore-backup", "{inputs}/earlier.db", "--yes"), True),
    Row("purge-test-data/apply", ("purge-test-data", "--apply", "--yes"), True),
    Row("purge-test-data/dry", ("purge-test-data",), False),
    Row("list-runs", ("list-runs",), False),
    Row("revert-run", ("revert-run", "{run}", "--yes"), True, setup=_a_run_to_revert),
    Row("replay-upgrade", ("replay-upgrade", "--offline", "-n", NS, "-m", MOD), False),
)


# ── Helpers ──────────────────────────────────────────────────────────────────────────────────────────


def _copy_db(source: Path, dest: Path) -> None:
    """A consistent single-file copy, whatever journal the source connection left open."""
    src = sqlite3.connect(source)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()


def _publish(client: TestClient, key: str, namespace: str, name: str, weight: str) -> None:
    resp = client.post(
        f"/api/v1/modules/{namespace}/{name}/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", ("module_spec.yaml", _YAML.format(name=name, title=name.title()).encode(), "text/yaml")),
            # Distinct data per module, or the second publish is `409 duplicate_content`.
            ("files", ("variants.csv", _VARIANTS.format(weight=weight).encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201, resp.text


def _invoke(argv: list[str], stdin: str | None = None) -> Result:
    cli.get_settings.cache_clear()
    try:
        return CliRunner().invoke(cli.app, argv, input=stdin)
    finally:
        cli.get_settings.cache_clear()


def _tree(root: Path) -> tuple[bool, dict[str, str], frozenset[str]]:
    """The storage root's existence, every file's digest by relative path, and every directory."""
    if not root.is_dir():
        return False, {}, frozenset()
    files = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file()
    }
    dirs = frozenset(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())
    return True, files, dirs


def _run_names(box: Box) -> set[str]:
    return {p.name for p in box.runs.iterdir() if p.is_dir()} if box.runs.is_dir() else set()


def _newest_run(box: Box) -> Path:
    names = _run_names(box)
    assert names, "no run directory at all"
    return box.runs / max(names)


def _changed_files(
    before: tuple[bool, dict[str, str], frozenset[str]], after: tuple[bool, dict[str, str], frozenset[str]]
) -> set[str]:
    _, old, _ = before
    _, new, _ = after
    return {path for path in old.keys() | new.keys() if old.get(path) != new.get(path)}


def _journal(run: Path) -> list[dict[str, object]]:
    path = run / maintenance.JOURNAL_FILE
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _record(run: Path) -> dict[str, object]:
    return json.loads((run / maintenance.RUN_FILE).read_text(encoding="utf-8"))


def _assert_log(run: Path) -> None:
    log = run / maintenance.LOG_FILE
    assert log.is_file(), f"{run.name}: no {maintenance.LOG_FILE}"
    text = log.read_text(encoding="utf-8")
    assert text.strip(), f"{run.name}: empty {maintenance.LOG_FILE}"
    assert text.splitlines()[0].startswith("# registry"), text.splitlines()[0]


# ── Fixtures ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A polygon catalog holding something for every changing row to change. Built once; copied per row."""
    work = tmp_path_factory.mktemp("maint-seed-work")
    settings = Settings(
        mode="test",
        db_path=work / "registry.db",
        storage_backend="local",
        local_storage_dir=work / "artifacts",
    )
    app = create_app(settings)
    repo: Repository = app.state.repo
    client = TestClient(app)

    anton = repo.create_account("antonkulaga")
    repo.add_namespace(NS, anton)
    repo.add_api_key(ANTON_KEY, anton)
    tester = repo.create_account("test-publisher")
    repo.add_namespace(TEST_NS, tester)
    repo.add_api_key(TESTER_KEY, tester)
    bob = repo.create_account("bob")
    repo.add_api_key(BOB_KEY, bob)
    repo.add_member(NS, bob, "member")
    carol = repo.create_account("carol")
    repo.add_api_key(CAROL_KEY, carol)
    acme = repo.create_account("acme")
    repo.set_account_type(acme, "org")
    repo.add_org_member(acme, anton, "owner")
    repo.add_org_member(acme, bob, "member")

    _publish(client, ANTON_KEY, NS, MOD, "-0.8")
    for version, created in (("1.0.0", "2026-01-01T00:00:00Z"), ("1.1.0", "2026-02-01T00:00:00Z")):
        seed_into(app, NS, LEGACY, version, genes=["APOE"], categories=["lipids"], created_at=created)
    repo.conn.commit()

    out = tmp_path_factory.mktemp("maint-seed")
    (out / "inputs").mkdir()
    # An earlier state of this same catalog, for `restore-backup` to change something by restoring.
    _copy_db(settings.db_path, out / "inputs" / "earlier.db")

    _publish(client, TESTER_KEY, TEST_NS, TEST_MOD, "-0.6")
    # Each of these is a state a changing row flips back; without it the row would write the value
    # already there and exercise nothing.
    assert repo.set_needs_upgrade(NS, MOD, "1.0.0", True)  # revalidate --set-flag clears it
    # rederive-signatures --apply writes it again. Stale rather than blank: `init_db` backfills a blank
    # one from the manifest, so every command that opens the catalog would "change" it.
    repo.conn.execute(
        "UPDATE versions SET content_hash = ? WHERE module_id = "
        "(SELECT id FROM modules WHERE namespace = ? AND name = ?)",
        ("sha256:" + "0" * 64, TEST_NS, TEST_MOD),
    )
    assert repo.set_namespace_flags(NS, featured=True)
    assert repo.set_namespace_flags(TEST_NS, blacklisted=True)
    template = repo.export_auth()["accounts"][0]
    repo.conn.commit()

    payload = {
        "accounts": [{**template, "id": 9001, "name": "dave", "type": "user", "install_id": None, "site_admin": 0}],
        "api_keys": [{"key": "mk_live_dave", "account_id": 9001}],
    }
    (out / "inputs" / "import.json").write_text(json.dumps(payload), encoding="utf-8")
    _copy_db(settings.db_path, out / "registry.db")
    shutil.copytree(settings.local_storage_dir, out / "artifacts")
    return out


@pytest.fixture
def box(seed_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    """A fresh copy of the seed, with the CLI pointed at it in polygon mode."""
    shutil.copytree(seed_dir, tmp_path / "box")
    made = Box(tmp_path / "box")
    monkeypatch.setenv("REGISTRY_MODE", "test")
    monkeypatch.setenv("REGISTRY_STORAGE_BACKEND", "local")
    monkeypatch.setenv("REGISTRY_DB_PATH", str(made.db))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(made.storage))
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(made.runs))
    # Beside the DB by default, which is inside the box but outside the storage tree; set anyway, so a
    # snapshot can never land in the tree the oracle digests.
    monkeypatch.setenv("REGISTRY_BACKUP_DIR", str(made.root / "backups"))
    return made


# ── The table is complete ────────────────────────────────────────────────────────────────────────────


def test_every_command_has_a_row_and_only_serve_is_excluded() -> None:
    commands = set(typer.main.get_command(cli.app).commands)  # type: ignore[attr-defined]
    # Floor before the set comparison: an enumeration that came back near-empty would make "every
    # command has a row" vacuous. Well under today's count.
    assert len(commands) >= 30, sorted(commands)
    assert "serve" in commands and "revert-run" in commands
    covered = {row.command for row in ROWS}
    assert commands - covered - EXCLUDED.keys() == set(), "commands with no row in this table"
    assert covered - commands == set(), "rows for commands the CLI does not have"
    assert EXCLUDED.keys() <= commands
    assert set(EXCLUDED) == set(maintenance.NOT_A_RUN)

    changing = {row.command for row in ROWS if row.changes}
    assert REPORT_ONLY.keys() <= commands
    assert changing & REPORT_ONLY.keys() == set(), "a report-only command has a changing row"
    assert commands - EXCLUDED.keys() - REPORT_ONLY.keys() - changing == set(), (
        "commands whose changing path no row exercises (add a changing row, or a REPORT_ONLY reason)"
    )
    labels = [row.label for row in ROWS]
    assert len(labels) == len(set(labels))


# ── Each row: logged, snapshotted before acting, reverted without remnants ──────────────────────────


@pytest.mark.parametrize("row", ROWS, ids=[row.label for row in ROWS])
def test_a_command_is_logged_snapshotted_and_revertible(box: Box, row: Row) -> None:
    places = {"root": str(box.root), "inputs": str(box.inputs)}
    if row.setup is not None:
        places |= row.setup(box)
    argv = [arg.format(**places) for arg in row.argv]

    db_before = maintenance.db_digest(box.db)
    tree_before = _tree(box.storage)
    runs_before = _run_names(box)

    result = _invoke(argv, row.stdin)
    assert result.exit_code in row.exits, (
        f"{row.label}: exit {result.exit_code}\n{result.output}\n{result.exception!r}"
    )

    db_after = maintenance.db_digest(box.db)
    tree_after = _tree(box.storage)
    new_runs = sorted(_run_names(box) - runs_before)
    changed = db_after != db_before or tree_after != tree_before

    if not row.changes:
        assert not changed, f"{row.label}: a report-only invocation changed the DB or storage"
        if result.exit_code != 0:
            # A run that did not end `ok` is kept whole, whatever it changed: its log says why.
            assert len(new_runs) == 1, f"{row.label}: {new_runs}"
            run = box.runs / new_runs[0]
            _assert_log(run)
            record = _record(run)
            assert record["changed"] is False
            assert str(record["outcome"]).startswith("failed"), record["outcome"]
        elif row.command in maintenance.ALWAYS_LOG:
            assert len(new_runs) == 1, f"{row.label}: {new_runs}"
            run = box.runs / new_runs[0]
            _assert_log(run)
            assert not (run / maintenance.SNAPSHOT_FILE).exists()
            assert _record(run)["changed"] is False
        else:
            assert new_runs == [], f"{row.label}: an unchanged run of a non-ALWAYS_LOG command was kept"
        return

    assert changed, f"{row.label}: changed neither the DB nor storage, so it does not exercise a changing path"
    assert len(new_runs) == 1, f"{row.label}: {new_runs}"
    run = box.runs / new_runs[0]
    assert run == _newest_run(box)
    _assert_log(run)
    record = _record(run)
    assert record["id"] == run.name
    assert record["command"] == row.command
    assert record["changed"] is True
    assert record["outcome"] == "ok"
    assert record["db_before"] == db_before and record["db_after"] == db_after
    snapshot = run / maintenance.SNAPSHOT_FILE
    if db_before is None:
        assert not snapshot.exists()
    else:
        assert maintenance.db_digest(snapshot) == db_before, f"{row.label}: snapshot is not the state before"
    touched = _changed_files(tree_before, tree_after)
    if touched:
        journaled = {f"{entry['key']}/{entry['name']}" for entry in _journal(run)}
        assert touched <= journaled, f"{row.label}: stored files changed but not journaled: {touched - journaled}"

    revert = _invoke(["revert-run", run.name, "--yes"])
    assert revert.exit_code == 0, f"{row.label}: revert exit {revert.exit_code}\n{revert.output}\n{revert.exception!r}"
    assert maintenance.db_digest(box.db) == db_before, f"{row.label}: DB not restored"
    present, files, dirs = _tree(box.storage)
    assert present == tree_before[0], f"{row.label}: storage root presence differs after revert"
    assert files == tree_before[1], f"{row.label}: stored files differ after revert"
    assert dirs == tree_before[2], f"{row.label}: directories differ after revert: {dirs ^ tree_before[2]}"
    reverter = _newest_run(box)
    assert reverter != run
    assert _record(run)["reverted_by"] == reverter.name


# ── The revert's own rules ───────────────────────────────────────────────────────────────────────────


def test_a_revert_is_itself_revertible(box: Box) -> None:
    db_before, tree_before = maintenance.db_digest(box.db), _tree(box.storage)
    assert _invoke(["remove-version", NS, LEGACY, "1.0.0", "--yes"]).exit_code == 0
    removal = _newest_run(box)
    db_removed, tree_removed = maintenance.db_digest(box.db), _tree(box.storage)
    assert (db_removed, tree_removed) != (db_before, tree_before)

    first = _invoke(["revert-run", removal.name, "--yes"])
    assert first.exit_code == 0, first.output
    revert = _newest_run(box)
    assert (maintenance.db_digest(box.db), _tree(box.storage)) == (db_before, tree_before)

    second = _invoke(["revert-run", revert.name, "--yes"])
    assert second.exit_code == 0, second.output
    assert (maintenance.db_digest(box.db), _tree(box.storage)) == (db_removed, tree_removed)
    assert _record(revert)["reverted_by"] == _newest_run(box).name
    # Undoing the revert puts the removal's change back, so the removal is no longer marked reverted.
    assert _record(removal)["reverted_by"] is None


def test_an_older_run_is_refused_while_a_newer_change_stands(box: Box) -> None:
    db_seed = maintenance.db_digest(box.db)
    assert _invoke(["feature", TEST_NS]).exit_code == 0
    older = _newest_run(box)
    assert _invoke(["set-funding", "bob", "https://example.org/donate"]).exit_code == 0
    newer = _newest_run(box)
    db_now = maintenance.db_digest(box.db)

    refused = _invoke(["revert-run", older.name, "--yes"])
    assert refused.exit_code == 1, refused.output
    assert newer.name in refused.output
    assert maintenance.db_digest(box.db) == db_now
    assert _record(older)["reverted_by"] is None

    # Newest first is the order that works.
    assert _invoke(["revert-run", newer.name, "--yes"]).exit_code == 0
    assert _invoke(["revert-run", older.name, "--yes"]).exit_code == 0
    assert maintenance.db_digest(box.db) == db_seed


def _write_outside_db(box: Box) -> None:
    """A write no run saw: what a live server's request looks like to the CLI."""
    conn = connect(box.db)
    try:
        Repository(conn).create_account("outsider")
        conn.commit()
    finally:
        conn.close()


def _write_outside_storage(box: Box) -> None:
    """Put back, by hand, a file the run removed."""
    target = box.storage / NS / LEGACY / "1.0.0" / "weights.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"written outside any run")


@pytest.mark.parametrize("move", [_write_outside_db, _write_outside_storage], ids=["db", "storage"])
def test_a_revert_is_refused_when_the_state_moved_since_the_run(
    box: Box, move: Callable[[Box], None]
) -> None:
    db_before, tree_before = maintenance.db_digest(box.db), _tree(box.storage)
    assert _invoke(["remove-version", NS, LEGACY, "1.0.0", "--yes"]).exit_code == 0
    run = _newest_run(box)
    move(box)
    moved = (maintenance.db_digest(box.db), _tree(box.storage))

    refused = _invoke(["revert-run", run.name, "--yes"])
    assert refused.exit_code == 1, refused.output
    assert "changed since" in refused.output
    assert (maintenance.db_digest(box.db), _tree(box.storage)) == moved
    assert _record(run)["reverted_by"] is None

    forced = _invoke(["revert-run", run.name, "--yes", "--force"])
    assert forced.exit_code == 0, forced.output
    # --force restores over the outside write: the state is the run's before, the outsider gone.
    assert (maintenance.db_digest(box.db), _tree(box.storage)) == (db_before, tree_before)
    assert _record(run)["reverted_by"] == _newest_run(box).name
