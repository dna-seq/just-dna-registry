"""Maintenance runs: every `registry` command is logged, snapshotted before it acts, and revertible.

**Why it is one mechanism and not a habit per command.** Through 0.28.0 each destructive command
called `_guard` for a DB snapshot, and the one that mints immutable PATCHes (`upgrade --apply`) did not,
nor did a single command keep a log: the polygon's first 0.8 sweep ran with no snapshot and its output
went with the terminal. A snapshot also covered the index only, while `upgrade` writes stored files,
`remove-*` deletes them and `rename-account` overwrites manifests in place, so an undo left the storage
half behind. Opening the run in the CLI's dispatch (`cli._MaintenanceGroup`) makes the three properties
a fact of running a command, which a new command inherits without doing anything.

A run is a directory `<run root>/<run id>/` (the root is `REGISTRY_RUN_DIR`, else `runs/` beside the DB):

- `run.log`: everything the command printed, colour stripped, and log records at INFO and above.
- `db.sqlite`: the catalog as it was before the command (sqlite's backup API, consistent with a live
  server writing beside it); absent when there was no DB.
- `journal.jsonl` + `storage/`: every stored file the command added, overwrote or removed, with the
  bytes it had before, captured before the write (`JournaledStorage`).
- `run.json`: the invocation, outcome, and the DB digest before and after.

A run that changed nothing and succeeded is deleted at the end, except for the commands in
`ALWAYS_LOG`, whose report is the point (it keeps its log and drops the snapshot).

`revert_run` undoes the journal in reverse and puts the snapshot back, then reads both back. It
reverts the newest changing run only, and refuses when the DB or a journaled file moved since the run
(a server's write, another command), because restoring a snapshot over those would destroy them. The
revert is a run of its own, so it is revertible too.

The DB is compared by `db_digest`, over sqlite's logical dump rather than the file's bytes, so a page
moved by a no-op migration is not a change and a restored snapshot compares equal to its source.
"""

import hashlib
import io
import json
import logging
import re
import shutil
import sqlite3
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import click

from just_dna_registry.config import Settings
from just_dna_registry.logging_setup import NOISY_LOGGERS
from just_dna_registry.storage.base import StorageBackend

RUN_DIRNAME = "runs"
RUN_FILE = "run.json"
LOG_FILE = "run.log"
SNAPSHOT_FILE = "db.sqlite"
JOURNAL_FILE = "journal.jsonl"
CAPTURE_DIR = "storage"

#: Commands whose run keeps its log even when it changed nothing: their report is what an operator
#: reads next (the held modules of a dry sweep, a merge plan), so losing it is the defect this module
#: exists to end.
ALWAYS_LOG: frozenset[str] = frozenset({
    "upgrade", "revalidate", "replay-upgrade", "rederive-signatures", "purge-test-data",
    "merge-accounts", "rename-account", "warm-caches", "revert-run",
})

#: Commands that are not maintenance runs. `serve` runs the API until stopped; its writes are
#: requests, each answered by the request's own rules, and a run around it would snapshot once and
#: then call a day of traffic "the command's change".
NOT_A_RUN: frozenset[str] = frozenset({"serve"})


class RevertRefused(Exception):
    """A revert that would destroy something the run did not write, or that cannot be done."""


def run_root(settings: Settings) -> Path:
    """Where runs live: `REGISTRY_RUN_DIR`, else `runs/` beside the DB."""
    return settings.run_dir or (settings.db_path.resolve().parent / RUN_DIRNAME)


def db_digest(path: Path) -> str | None:
    """sha256 over the DB's logical dump, or `None` when there is no DB. The oracle for "as it was"."""
    path = Path(path)
    if not path.is_file():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        digest = hashlib.sha256()
        for line in conn.iterdump():
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()
    finally:
        conn.close()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy_db(source: Path, dest: Path) -> None:
    """Copy a catalog with sqlite's backup API, which reads a consistent state under a live writer."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()


_API_KEY = re.compile(r"\bmk_(live|test)_[A-Za-z0-9_-]+")


def redact(text: str) -> str:
    """A run log outlives the terminal and sits beside the catalog, so an API key never enters it."""
    return _API_KEY.sub(lambda m: f"mk_{m.group(1)}_…(redacted)", text)


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def _stamp(precise: bool = False) -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y%m%dT%H%M%S.%fZ") if precise else now.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Tee(io.TextIOBase):
    """Writes to the live stream as it was, and to the log without colour codes.

    Outlives the run on purpose: anything that captured `sys.stdout` while the run held it keeps this
    object, and logging flushes every handler at interpreter exit, so the log is detached at the end
    and the tee passes through to the live stream alone.
    """

    def __init__(self, live: TextIO, log: TextIO) -> None:
        self._live: TextIO = live
        self._log: TextIO | None = log

    def detach_log(self) -> None:
        self._log = None

    def write(self, text: str) -> int:
        self._live.write(text)
        if self._log is not None:
            self._log.write(redact(click.unstyle(text)))
        return len(text)

    def flush(self) -> None:
        self._live.flush()
        if self._log is not None:
            self._log.flush()

    def isatty(self) -> bool:
        return self._live.isatty()

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self._live, "encoding", None) or "utf-8"


@dataclass
class Run:
    """One command's run: where it lives and what it has journaled so far."""

    id: str
    path: Path
    command: str
    invocation: str
    db_path: Path
    entries: list[dict[str, Any]] = field(default_factory=list)
    #: Fields the command adds to `run.json` (a revert names the run it reverted).
    extra: dict[str, Any] = field(default_factory=dict)

    def record(self, op: str, key: str, name: str, *, before: bytes | None, after: bytes | None) -> None:
        """Journal one stored file, capturing its prior bytes, before the write that changes it."""
        captured: str | None = None
        if before is not None:
            captured = f"{CAPTURE_DIR}/{len(self.entries):06d}"
            target = self.path / captured
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(before)
        entry = {
            "op": op, "key": key, "name": name, "before": captured,
            "after_sha256": _sha256(after) if after is not None else None,
        }
        self.entries.append(entry)
        with (self.path / JOURNAL_FILE).open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(entry) + "\n")


_ACTIVE: list[Run] = []


def active_run() -> Run | None:
    """The innermost run in this process, or `None` outside the CLI."""
    return _ACTIVE[-1] if _ACTIVE else None


class JournaledStorage:
    """A storage backend whose every write and removal is journaled, prior bytes first."""

    def __init__(self, inner: StorageBackend, run: Run) -> None:
        self.inner = inner
        self._run = run

    def store_module(self, key: str, files: Mapping[str, bytes]) -> None:
        for name, data in files.items():
            if self.inner.exists(key, name):
                self._run.record("overwrite", key, name, before=self.inner.read_file(key, name), after=data)
            else:
                self._run.record("add", key, name, before=None, after=data)
        self.inner.store_module(key, files)

    def remove(self, key: str) -> None:
        for name in self.inner.list_files(key):
            self._run.record("remove", key, name, before=self.inner.read_file(key, name), after=None)
        self.inner.remove(key)

    def remove_file(self, key: str, name: str) -> None:
        if self.inner.exists(key, name):
            self._run.record("remove", key, name, before=self.inner.read_file(key, name), after=None)
        self.inner.remove_file(key, name)

    def exists(self, key: str, name: str) -> bool:
        return self.inner.exists(key, name)

    def read_file(self, key: str, name: str) -> bytes:
        return self.inner.read_file(key, name)

    def file_url(self, key: str, name: str) -> str | None:
        return self.inner.file_url(key, name)

    def list_files(self, key: str) -> list[str]:
        return self.inner.list_files(key)


def journaled(storage: StorageBackend) -> StorageBackend:
    """`storage` journaled by the active run, or as it is outside one."""
    run = active_run()
    return JournaledStorage(storage, run) if run is not None else storage


def _write_record(run_path: Path, record: dict[str, Any]) -> None:
    (run_path / RUN_FILE).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def read_record(run_path: Path) -> dict[str, Any]:
    return json.loads((run_path / RUN_FILE).read_text(encoding="utf-8"))


def list_runs(settings: Settings) -> list[Path]:
    """Every run directory that carries a record, oldest first (run ids sort by start time)."""
    root = run_root(settings)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / RUN_FILE).is_file())


@contextmanager
def maintenance_run(settings: Settings, command: str, invocation: str) -> Iterator[Run]:
    """Open a run around one command: snapshot first, log throughout, record and prune at the end."""
    root = run_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    run_id = f"{_stamp(precise=True)}-{command}"
    path = root / run_id
    serial = 1
    while path.exists():
        serial += 1
        path = root / f"{run_id}-{serial}"
    path.mkdir()
    db_path = settings.db_path.resolve()
    before = db_digest(db_path)
    if before is not None:
        _copy_db(db_path, path / SNAPSHOT_FILE)
    run = Run(id=path.name, path=path, command=command, invocation=invocation, db_path=db_path)
    record: dict[str, Any] = {
        "id": run.id, "command": command, "invocation": invocation, "started": _stamp(),
        "ended": None, "outcome": None, "changed": None, "db_before": before, "db_after": None,
        "reverted_by": None,
    }
    _write_record(path, record)

    live_out, live_err = sys.stdout, sys.stderr
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    log = (path / LOG_FILE).open("x", encoding="utf-8")
    log.write(f"# {invocation}\n# started {record['started']}\n")
    handler = logging.StreamHandler(log)
    handler.setFormatter(_RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
    handler.setLevel(logging.INFO)
    # With no handler on the root a WARNING reached the terminal through `logging.lastResort`; adding
    # ours would silence that, so the terminal gets a handler of its own at the same level.
    console = logging.StreamHandler(live_err) if not root_logger.handlers else None
    if console is not None:
        console.setLevel(logging.WARNING)
        root_logger.addHandler(console)
    root_logger.addHandler(handler)
    root_logger.setLevel(min(previous_level or logging.WARNING, logging.INFO))
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    tees = (_Tee(live_out, log), _Tee(live_err, log))
    _ACTIVE.append(run)
    outcome = "ok"
    try:
        with redirect_stdout(tees[0]), redirect_stderr(tees[1]):
            click.echo(f"run: {path}", err=True)  # stderr: stdout stays the command's own
            yield run
    except BaseException as exc:
        code = getattr(exc, "exit_code", None)
        if code != 0:
            outcome = f"failed: {type(exc).__name__}" + (f" (exit {code})" if code is not None else "")
        raise
    finally:
        _ACTIVE.remove(run)
        for tee in tees:
            tee.detach_log()
        root_logger.removeHandler(handler)
        if console is not None:
            root_logger.removeHandler(console)
        root_logger.setLevel(previous_level)
        after = db_digest(db_path)
        changed = after != before or bool(run.entries)
        record.update(run.extra)
        record.update(ended=_stamp(), outcome=outcome, changed=changed, db_after=after)
        log.write(f"# {outcome} {record['ended']}{'' if changed else ' (nothing changed)'}\n")
        log.close()
        _write_record(path, record)
        if not changed:
            # Nothing to revert, so no snapshot to keep. A failure keeps its log: it says why.
            (path / SNAPSHOT_FILE).unlink(missing_ok=True)
            (path / JOURNAL_FILE).unlink(missing_ok=True)
            if outcome == "ok" and command not in ALWAYS_LOG:
                shutil.rmtree(path, ignore_errors=True)
                path = None  # type: ignore[assignment]
        if path is not None:
            click.echo(f"run: {path}", file=live_err)


@dataclass(frozen=True)
class RevertReport:
    """What a revert put back."""

    run_id: str
    files_restored: int
    files_removed: int
    db_restored: bool


def _storage_state(storage: StorageBackend, key: str, name: str) -> str | None:
    return _sha256(storage.read_file(key, name)) if storage.exists(key, name) else None


def revert_run(settings: Settings, run_id: str, storage: StorageBackend, *, force: bool = False) -> RevertReport:
    """Undo one run: its storage journal in reverse, then its DB snapshot; read both back.

    `storage` is the backend as the CLI builds it (journaled by the revert's own run, so the revert
    is revertible). Refused when a later changing run has not been reverted, or when the DB or a
    journaled file is no longer what the run left, unless `force`.
    """
    runs = list_runs(settings)
    path = run_root(settings) / run_id
    if path not in runs:
        raise RevertRefused(f"no run {run_id} under {run_root(settings)}")
    record = read_record(path)
    if record.get("reverted_by"):
        raise RevertRefused(f"run {run_id} was already reverted by {record['reverted_by']}")
    if not record.get("changed"):
        raise RevertRefused(f"run {run_id} changed nothing; there is nothing to revert")
    current = active_run()
    records = {p.name: read_record(p) for p in runs if p.name > run_id}
    # A revert of a newer run cancels with it: walking back newest first passes over both.
    cancelled = {
        name for name, rec in records.items()
        if rec.get("reverts") in records and records[rec["reverts"]].get("reverted_by") == name
    }
    later = [
        name for name, rec in records.items()
        if (current is None or name != current.id) and name not in cancelled
        and rec.get("changed") and not rec.get("reverted_by")
    ]
    if later and not force:
        raise RevertRefused(
            f"newer run(s) changed the catalog after {run_id} and are not reverted: {', '.join(later)}. "
            "Revert them first, newest first (or --force to restore over them)."
        )
    entries = [
        json.loads(line)
        for line in (path / JOURNAL_FILE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if (path / JOURNAL_FILE).is_file() else []
    if not force:
        moved = []
        if db_digest(settings.db_path.resolve()) != record["db_after"]:
            moved.append("the catalog DB")
        # The last write to each file is the state the run left it in.
        left: dict[tuple[str, str], str | None] = {}
        for entry in entries:
            left[(entry["key"], entry["name"])] = entry["after_sha256"]
        moved += [
            f"{key}/{name}" for (key, name), digest in left.items()
            if _storage_state(storage, key, name) != digest
        ]
        if moved:
            raise RevertRefused(
                f"changed since run {run_id} ended: {', '.join(moved[:10])}"
                + (f" … ({len(moved)} total)" if len(moved) > 10 else "")
                + ". Restoring would destroy those changes (--force to do it anyway)."
            )

    restored = removed = 0
    for entry in reversed(entries):
        key, name = entry["key"], entry["name"]
        if entry["before"] is None:
            storage.remove_file(key, name)
            removed += 1
        else:
            storage.store_module(key, {name: (path / entry["before"]).read_bytes()})
            restored += 1

    db_path = settings.db_path.resolve()
    snapshot = path / SNAPSHOT_FILE
    if record["db_before"] is None:
        db_path.unlink(missing_ok=True)
    else:
        source = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        live = sqlite3.connect(db_path)
        try:
            source.backup(live)
        finally:
            live.close()
            source.close()

    # Read back: the DB and every journaled file as they were before the run.
    if db_digest(db_path) != record["db_before"]:
        raise RevertRefused(f"the catalog DB does not match run {run_id}'s snapshot after restoring it")
    first: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        first.setdefault((entry["key"], entry["name"]), entry)
    wrong = []
    for (key, name), entry in first.items():
        expected = _sha256((path / entry["before"]).read_bytes()) if entry["before"] else None
        if _storage_state(storage, key, name) != expected:
            wrong.append(f"{key}/{name}")
    if wrong:
        raise RevertRefused(f"stored files not restored: {', '.join(wrong[:10])}")

    record["reverted_by"] = current.id if current is not None else "(outside a run)"
    _write_record(path, record)
    if current is not None:
        current.extra["reverts"] = run_id
    # Undoing a revert puts its target's change back, so the target is live again and revertible.
    target = record.get("reverts")
    if target and (run_root(settings) / target / RUN_FILE).is_file():
        undone = read_record(run_root(settings) / target)
        undone["reverted_by"] = None
        _write_record(run_root(settings) / target, undone)
    return RevertReport(run_id, restored, removed, record["db_before"] is not None)
