"""Admin ops (0.9.0): export/import the auth graph (accounts + API keys + namespaces + members),
and reset the catalog while keeping the keys. `reset-db` is gated behind a typed RESET confirmation.
The Ed25519 signing key is a separate PEM file (not in the DB) — untouched by any of this."""

import os
import re
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from just_dna_registry.cli import app
from just_dna_registry.config import get_settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db


def _seed(seed) -> None:
    seed("just-dna-seq", "coronary", "1.0.0", genes=["LPA"], categories=["c"],
         created_at="2025-01-01T00:00:00Z")


def test_export_auth_captures_the_graph(repo: Repository, seed, api_key: str) -> None:
    _seed(seed)
    dump = repo.export_auth()
    assert any(a["name"] == "antonkulaga" for a in dump["accounts"])
    assert any(k["key"] == "mk_live_testkey" for k in dump["api_keys"])
    assert any(n["name"] == "just-dna-seq" for n in dump["namespaces"])
    assert any(m["role"] == "owner" for m in dump["members"])


def test_reset_keeps_keys_and_wipes_catalog(repo: Repository, seed, api_key: str) -> None:
    _seed(seed)
    assert repo.search_modules()[1] > 0  # a module is indexed
    repo.reset_catalog(keep_auth=True)
    assert repo.search_modules()[1] == 0                              # catalog gone
    assert repo.account_for_key("mk_live_testkey") is not None        # key kept
    acct = repo.account_for_key("mk_live_testkey")
    assert "just-dna-seq" in repo.namespaces_for_account(int(acct["id"]))  # ownership kept


def test_reset_wipe_keys_removes_accounts(repo: Repository, seed, api_key: str) -> None:
    _seed(seed)
    repo.reset_catalog(keep_auth=False)
    assert repo.account_for_key("mk_live_testkey") is None


def test_export_import_roundtrip_to_fresh_db(
    repo: Repository, seed, api_key: str, tmp_path: Path
) -> None:
    _seed(seed)
    dump = repo.export_auth()
    conn2 = connect(tmp_path / "restored.db")
    init_db(conn2)
    repo2 = Repository(conn2)
    counts = repo2.import_auth(dump)
    assert counts["accounts"] >= 1 and counts["api_keys"] >= 1
    # The key + its namespace ownership are restored (auth only — no modules carried over).
    acct = repo2.account_for_key("mk_live_testkey")
    assert acct is not None
    assert "just-dna-seq" in repo2.namespaces_for_account(int(acct["id"]))
    assert repo2.search_modules()[1] == 0


def test_export_keys_refuses_missing_db(tmp_path: Path, monkeypatch) -> None:
    # A relative/wrong db_path must NOT silently create an empty DB and crash on `no such table`.
    missing = tmp_path / "nope.db"
    monkeypatch.setenv("REGISTRY_DB_PATH", str(missing))
    monkeypatch.setenv("REGISTRY_STORAGE_BACKEND", "local")
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(tmp_path / "art"))
    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["export-keys"])
    assert result.exit_code != 0
    assert not missing.exists()  # refused before creating a stray empty DB
    get_settings.cache_clear()


def test_export_keys_migrates_a_stale_pre_0_9_db(tmp_path: Path, monkeypatch) -> None:
    # A real (pre-0.9) DB lacks funding_url etc.; export-keys must run the additive migration first,
    # not crash with `no such column`. Simulate the minimal legacy accounts table.
    db = tmp_path / "old.db"
    conn = connect(db)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO accounts(name) VALUES ('erik')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("REGISTRY_DB_PATH", str(db))
    monkeypatch.setenv("REGISTRY_STORAGE_BACKEND", "local")
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(tmp_path / "art"))
    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["export-keys"])
    assert result.exit_code == 0, result.output
    assert "erik" in result.stdout  # exported after the in-place migration added the new columns
    get_settings.cache_clear()


def test_reset_db_cli_requires_typed_confirmation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("REGISTRY_STORAGE_BACKEND", "local")
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(tmp_path / "art"))
    get_settings.cache_clear()
    runner = CliRunner()

    aborted = runner.invoke(app, ["reset-db"], input="nope\n")
    assert aborted.exit_code != 0  # wrong text → aborts

    ok = runner.invoke(app, ["reset-db"], input="RESET\n")
    assert ok.exit_code == 0 and "catalog reset" in ok.stdout
    get_settings.cache_clear()  # don't leak the temp settings to other tests


def test_python_m_registers_every_command_the_console_script_does() -> None:
    """`python -m just_dna_registry.cli` must expose the same commands as the `registry` script.

    The module executes top to bottom under `-m`, so a `if __name__ == "__main__": app()` guard
    placed above any `@app.command` calls `app()` before those commands are registered. The guard
    sat above the 0.11 operator block and cost six of them on that entry point only — `warm-caches`,
    `backup`, `list-backups`, `restore-backup`, `purge-test-data` and `rederive-signatures` —
    while the console script, which imports the module and never trips the guard, listed all of
    them. So `--help` was simultaneously right and wrong depending on how you started it, and the
    missing one that matters is `backup`: every destructive ops command is documented as snapshotting
    first.

    An import-based check cannot see this — importing the module runs every decorator regardless of
    where the guard sits — so both entry points are driven as subprocesses.
    """
    def commands(argv: list[str]) -> set[str]:
        out = subprocess.run(
            argv + ["--help"],
            capture_output=True,
            text=True,
            env={**os.environ, "COLUMNS": "200", "NO_COLOR": "1"},
            check=True,
        ).stdout
        # Typer frames the command table; a row starts with the name in the first column.
        return {
            m.group(1)
            for line in out.splitlines()
            if (m := re.match(r"^\W*\b([a-z][a-z0-9-]{2,})\b\s{2,}\S", line))
        }

    module = commands([sys.executable, "-m", "just_dna_registry.cli"])
    # `info.name` is None where a command was registered as a bare `@app.command()`, so fall back
    # to the callback name the way Typer renders it. Filtering the Nones out instead is what made a
    # first version of this test report 24 of 31 and blame the CLI.
    registered = {
        info.name or (info.callback.__name__.replace("_", "-") if info.callback else "")
        for info in app.registered_commands
    } - {""}

    # Floor first: an empty or barely-populated parse makes the comparison below vacuous.
    assert len(registered) >= 25, f"only {len(registered)} commands registered — CLI broken"
    assert len(module) >= 25, f"parsed only {len(module)} from -m help — parser broken, not the CLI"

    missing = registered - module
    assert not missing, f"`python -m` is missing registered commands: {sorted(missing)}"
    # The six the misplaced guard actually cost, named so a regression says which.
    for late in ("warm-caches", "backup", "list-backups", "restore-backup", "purge-test-data"):
        assert late in module, f"{late} not exposed under `python -m`"
