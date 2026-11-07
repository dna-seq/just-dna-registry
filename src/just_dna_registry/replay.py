"""Replay a `registry upgrade --apply` over a scratch copy of the catalog, to recover its lost report.

**Why this exists.** The polygon's first format-0.8 sweep ran with its output going to a terminal that
is gone: which modules were held, which refused with drift a person has to read, and what each
re-derivation said. The successors it published are in the catalog, and their predecessors are
untouched (a published version is immutable), so the run can be performed again from the same
starting point: copy the catalog, remove the successors from the *copy* so each predecessor is latest
again, and run the very same sweep (`cli._upgrade_sweep`) over the copy and a storage overlay. Its
output is the log the lost run would have written, and its successors can be compared with the ones
the real run published.

**Nothing reaches the real catalog or storage.** The live DB is opened read-only (`mode=ro`) and only
as the source of sqlite's backup API; `init_db` never runs on it. Every write and removal the sweep
makes lands in `OverlayStorage`'s scratch directory, and a removal of a file the real storage holds
is a tombstone in memory, never forwarded.

**What a replay cannot reproduce faithfully**, said here so a reader of the report does not have to
infer it. An online re-derivation asks live sources again, which may answer differently today. The
enricher's snapshots are today's, not the run's, if they moved in between. And `artifact.digest` names
bytes: a module that authors no `sources.csv` gets one stamped with `fetched_at` at second resolution,
so two compiles of identical inputs can differ in digest while `content_signature` agrees. The report
therefore names the files that moved rather than calling a digest difference a different module.
"""

import hashlib
import io
import json
import re
import sqlite3
import sys
from collections.abc import Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TextIO

import click
import typer

from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.services.upgrade import is_latest_version
from just_dna_registry.storage.base import StorageBackend, version_key
from just_dna_registry.storage.local import LocalStorage

#: How `services.upgrade._upgrade_changelog` opens every automated successor's changelog.
AUTOMATED_PREFIX = "Automated upgrade of "
#: What `services.enrich.rederive_changelog` writes for a re-derivation that went online. The sweep
#: only goes online for a module carrying an indel *and* only under `--online`, so one successor
#: saying so proves the original run had the flag; none saying so proves nothing.
ONLINE_MARK = "re-derived (online)"
_PREDECESSOR_RE = re.compile(r"^" + re.escape(AUTOMATED_PREFIX) + r"([^\s:]+)")
#: A sweep line about one version: `✓ <label> → …`, `✗ <label>: …`, `… held <label>: …`.
_SWEEP_LINE_RE = re.compile(r"^(?P<kind>✓|✗|… held) (?P<label>[^\s@/]+/[^\s@/]+@[^\s:]+)(?::| →)")

SAME = "same"
SAME_CONTENT = "same content"
DIFFERS = "differs"
NOT_REPUBLISHED = "not re-published"
NOT_REPLAYED = "not replayed"

#: Settings that place files beside the DB unless set. Each is pointed into the workdir, so a sweep
#: that snapshots or logs does it to the copy's side and never into an operator's configured dir.
_SCRATCH_DIRS = ("backup_dir", "run_dir", "run_log_dir")


class ReplayRefused(Exception):
    """A replay that cannot start: no live DB, a workdir already in use, or an unknown `--online`."""


class Sweep(Protocol):
    """`cli._upgrade_sweep`'s signature, which the replay calls exactly as `registry upgrade` does."""

    def __call__(
        self,
        settings: Settings,
        repo: Repository,
        storage: StorageBackend,
        *,
        namespace: str | None,
        module: str | None,
        apply: bool,
        force: bool,
        trim: bool,
        limit: int,
        online: bool,
        accept_drift: bool,
    ) -> None: ...


# ── The overlay ──────────────────────────────────────────────────────────────────────────────────────


class OverlayStorage:
    """Reads from `scratch` then `base`; writes and removals go to `scratch` only.

    A removal of a file `base` holds is a tombstone: it hides the file from this overlay and is never
    forwarded. Storing the file again lifts the tombstone, since the scratch copy then answers first.
    """

    def __init__(self, base: StorageBackend, scratch: LocalStorage) -> None:
        self.base = base
        self.scratch = scratch
        self._tombstones: set[str] = set()

    @staticmethod
    def _path(key: str, name: str) -> str:
        return f"{key.strip('/')}/{name}"

    def store_module(self, key: str, files: Mapping[str, bytes]) -> None:
        self.scratch.store_module(key, files)
        for name in files:
            self._tombstones.discard(self._path(key, name))

    def exists(self, key: str, name: str) -> bool:
        if self.scratch.exists(key, name):
            return True
        return self._path(key, name) not in self._tombstones and self.base.exists(key, name)

    def read_file(self, key: str, name: str) -> bytes:
        if self.scratch.exists(key, name):
            return self.scratch.read_file(key, name)
        if self._path(key, name) in self._tombstones:
            raise FileNotFoundError(self._path(key, name))
        return self.base.read_file(key, name)

    def file_url(self, key: str, name: str) -> str | None:
        # A URL into the base would serve bytes this overlay may have replaced or removed.
        return None

    def list_files(self, key: str) -> list[str]:
        visible = {
            name for name in self.base.list_files(key) if self._path(key, name) not in self._tombstones
        }
        return sorted(visible | set(self.scratch.list_files(key)))

    def remove_file(self, key: str, name: str) -> None:
        self.scratch.remove_file(key, name)
        self._tombstones.add(self._path(key, name))

    def remove(self, key: str) -> None:
        for name in self.base.list_files(key):
            self._tombstones.add(self._path(key, name))
        self.scratch.remove(key)


# ── Finding what the original run published ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Successor:
    """A version an automated upgrade published, read off the catalog."""

    namespace: str
    name: str
    version: str
    predecessor: str
    created_at: str
    compiler_version: str | None
    digest: str
    content_signature: str | None
    #: `artifact.files[]` as name → sha256, so a digest difference can name the files that moved.
    files: dict[str, str]
    changelog: str

    @property
    def label(self) -> str:
        return f"{self.namespace}/{self.name}@{self.version}"

    @property
    def predecessor_label(self) -> str:
        return f"{self.namespace}/{self.name}@{self.predecessor}"


def _successor(row: sqlite3.Row) -> Successor | None:
    match = _PREDECESSOR_RE.match(row["changelog"])
    if match is None:
        return None
    manifest: dict[str, Any] = json.loads(row["manifest_json"])
    artifact = manifest.get("artifact") or {}
    return Successor(
        namespace=row["namespace"],
        name=row["name"],
        version=row["version"],
        predecessor=match.group(1),
        created_at=row["created_at"],
        compiler_version=(manifest.get("compilation") or {}).get("compiler_version"),
        digest=artifact.get("digest", row["digest"]),
        content_signature=manifest.get("content_signature"),
        files={entry["name"]: entry["sha256"] for entry in artifact.get("files", [])},
        changelog=row["changelog"],
    )


def _bare_version(stamp: str | None) -> str:
    """`"just-dna-compiler 0.8.0"` → `"0.8.0"`: the stamp is a name and a version, and `--compiler 0.8`
    names the version. The last token, as `services.upgrade.stamped_compiler_version` reads it."""
    return stamp.split()[-1] if stamp and stamp.split() else ""


def find_successors(
    repo: Repository,
    *,
    since: str | None = None,
    compiler: str | None = None,
    namespace: str | None = None,
    module: str | None = None,
) -> list[Successor]:
    """Every version an automated upgrade published, oldest first.

    `since` keeps versions created at or after it (an ISO prefix such as `2026-11-01` works, the
    column is ISO-8601 text); `compiler` keeps those whose `compilation.compiler_version` starts with
    it, so `0.8` selects the 0.8 cut's successors and leaves an earlier cut's out.
    """
    sql = (
        "SELECT m.namespace, m.name, v.version, v.digest, v.changelog, v.created_at, v.manifest_json "
        "FROM versions v JOIN modules m ON m.id = v.module_id WHERE substr(v.changelog, 1, ?) = ?"
    )
    params: list[Any] = [len(AUTOMATED_PREFIX), AUTOMATED_PREFIX]
    if namespace is not None:
        sql += " AND m.namespace = ?"
        params.append(namespace)
    if module is not None:
        sql += " AND m.name = ?"
        params.append(module)
    if since is not None:
        sql += " AND v.created_at >= ?"
        params.append(since)
    sql += " ORDER BY v.created_at, m.namespace, m.name, v.version"
    found = [_successor(row) for row in repo.conn.execute(sql, params).fetchall()]
    return [
        s for s in found
        if s is not None
        and (compiler is None or _bare_version(s.compiler_version).startswith(compiler))
    ]


def original_online(successors: list[Successor]) -> bool | None:
    """`True` when a successor proves the original run went online, else `None`: cannot say.

    Never `False`: a run with `--online` over a catalog with no published indel module leaves no trace
    of the flag, so the absence of the mark is not evidence of its absence.
    """
    return True if any(ONLINE_MARK in s.changelog for s in successors) else None


# ── Reading the sweep's output ───────────────────────────────────────────────────────────────────────


class _Capture(io.TextIOBase):
    """Passes writes through to the live stream and keeps a colourless copy."""

    def __init__(self, live: TextIO) -> None:
        self._live = live
        self.buffer_text = io.StringIO()

    def write(self, text: str) -> int:
        self._live.write(text)
        self.buffer_text.write(click.unstyle(text))
        return len(text)

    def flush(self) -> None:
        self._live.flush()

    def isatty(self) -> bool:
        return self._live.isatty()

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self._live, "encoding", None) or "utf-8"


@dataclass
class SweepLines:
    """What the sweep printed about each version, keyed by its `ns/name@version` label.

    Read from the printed lines because `_upgrade_sweep` returns nothing; each line is anchored on the
    label the sweep itself prints, and an indented line belongs to the label line above it (a refusal's
    drift list, a publish's digest line).
    """

    published: dict[str, list[str]] = field(default_factory=dict)
    refused: dict[str, list[str]] = field(default_factory=dict)
    held: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "SweepLines":
        parsed = cls()
        buckets = {"✓": parsed.published, "✗": parsed.refused, "… held": parsed.held}
        current: list[str] | None = None
        for line in text.splitlines():
            match = _SWEEP_LINE_RE.match(line)
            if match is not None:
                current = buckets[match.group("kind")].setdefault(match.group("label"), [])
                current.append(line)
            elif current is not None and line.startswith("    "):
                current.append(line)
            else:
                current = None
        return parsed

    def about(self, label: str) -> list[str]:
        return [*self.published.get(label, []), *self.refused.get(label, []), *self.held.get(label, [])]


# ── The replay ───────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReplayEntry:
    """One successor the original run published, and what the replay made of its predecessor."""

    original: Successor
    status: str
    replayed: Successor | None = None
    #: `artifact.files[]` names whose bytes differ between the two, or that only one of them has.
    moved_files: list[str] = field(default_factory=list)
    reason: str = ""
    #: Every line the replayed sweep printed about the predecessor.
    lines: list[str] = field(default_factory=list)


@dataclass
class ReplayReport:
    workdir: Path
    catalog: Path
    online: bool
    entries: list[ReplayEntry]
    #: The replay's own outcome per predecessor label, including modules with no successor in the
    #: catalog: those are the ones the original run held or refused, the information it lost.
    sweep: SweepLines
    live_db_unchanged: bool

    @property
    def found(self) -> int:
        return len(self.entries)

    @property
    def republished(self) -> int:
        return sum(1 for e in self.entries if e.replayed is not None)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_live_db(source: Path, dest: Path) -> None:
    """sqlite's backup API from a read-only connection: nothing is ever written to `source`."""
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()


def _moved(original: Successor, replayed: Successor) -> list[str]:
    names = set(original.files) | set(replayed.files)
    return sorted(n for n in names if original.files.get(n) != replayed.files.get(n))


def _compare(original: Successor, replayed: Successor, lines: list[str]) -> ReplayEntry:
    if replayed.digest == original.digest:
        status, reason = SAME, ""
    elif replayed.content_signature is not None and replayed.content_signature == original.content_signature:
        status = SAME_CONTENT
        reason = "content_signature agrees; the digest moved with the bytes of the files named"
    else:
        status = DIFFERS
        reason = "content_signature differs: the replay derived different data"
    return ReplayEntry(original, status, replayed, _moved(original, replayed), reason, lines)


def _not_republished(original: Successor, sweep: SweepLines) -> ReplayEntry:
    label = original.predecessor_label
    lines = sweep.about(label)
    if label in sweep.held:
        reason = "held: " + sweep.held[label][0].split(": ", 1)[-1]
    elif label in sweep.refused:
        reason = "refused: " + sweep.refused[label][0].split(": ", 1)[-1]
    else:
        reason = "the sweep printed nothing for it: it found no gap to act on"
    return ReplayEntry(original, NOT_REPUBLISHED, None, [], reason, lines)


def replay_upgrade(
    settings: Settings,
    storage: StorageBackend,
    *,
    sweep: Sweep,
    since: str | None,
    compiler: str | None,
    online: bool | None,
    namespace: str | None,
    module: str | None,
    workdir: Path,
) -> ReplayReport:
    """Run the upgrade sweep again from the predecessors of the successors it published, on a copy.

    `online=None` takes the original run's switch where a successor proves it (`original_online`) and
    refuses otherwise, because a replay under the other switch holds or publishes different modules
    and would report a difference that is the replay's, not the run's.
    """
    live = settings.db_path
    if not live.is_file():
        raise ReplayRefused(f"no registry database at {live.resolve()}")
    workdir = Path(workdir)
    if workdir.exists() and any(workdir.iterdir()):
        # A scratch tree from an earlier replay would answer reads the real storage should.
        raise ReplayRefused(f"{workdir} is not empty; a replay needs a fresh workdir")
    workdir.mkdir(parents=True, exist_ok=True)
    before_bytes = _file_sha256(live)

    copy = workdir / "catalog.db"
    _copy_live_db(live, copy)
    conn = connect(copy)
    init_db(conn)
    repo = Repository(conn)
    overlay = OverlayStorage(storage, LocalStorage(workdir / "storage"))

    successors = find_successors(
        repo, since=since, compiler=compiler, namespace=namespace, module=module
    )
    if online is None:
        online = original_online(successors)
        if online is None:
            raise ReplayRefused(
                "no successor says whether the original run used --online; pass --online or --offline"
            )

    entries: dict[str, ReplayEntry] = {}
    targets: list[Successor] = []
    for s in successors:
        latest = repo.get_module_row(s.namespace, s.name)["latest_version"]
        if s.version != latest:
            entries[s.label] = ReplayEntry(
                s, NOT_REPLAYED,
                reason=f"{latest} follows it; only a module's latest version can be replayed",
            )
            continue
        repo.delete_version(s.namespace, s.name, s.version)
        # Same version number comes back from `_next_free_patch`, so the real files under that key
        # must not show through the overlay beneath the replay's own.
        overlay.remove(version_key(s.namespace, s.name, s.version))
        if not is_latest_version(repo, s.namespace, s.name, s.predecessor):
            now = repo.get_module_row(s.namespace, s.name)["latest_version"]
            entries[s.label] = ReplayEntry(
                s, NOT_REPLAYED,
                reason=f"its predecessor {s.predecessor} is not latest once it is removed ({now} is)",
            )
            continue
        targets.append(s)
    present = {
        (r["namespace"], r["name"], r["version"]) for r in repo.list_all_versions(namespace)
    }

    scratch_settings = settings.model_copy(update={
        "db_path": copy,
        "local_storage_dir": workdir / "storage",
        **{key: workdir / key for key in _SCRATCH_DIRS if key in Settings.model_fields},
    })
    typer.echo(
        f"replay: {len(successors)} automated successor(s) found, {len(targets)} replayed from their "
        f"predecessors on a scratch copy ({copy}); {'online' if online else 'offline'} as the original"
    )
    capture = _Capture(sys.stdout)
    with redirect_stdout(capture):
        sweep(
            scratch_settings, repo, overlay,
            namespace=namespace, module=module, apply=True, force=False, trim=False, limit=0,
            online=online, accept_drift=False,
        )
    lines = SweepLines.parse(capture.buffer_text.getvalue())

    replayed = {
        (s.namespace, s.name, s.predecessor): s
        for s in find_successors(repo, namespace=namespace, module=module)
        if (s.namespace, s.name, s.version) not in present
    }
    for s in targets:
        again = replayed.get((s.namespace, s.name, s.predecessor))
        entries[s.label] = (
            _compare(s, again, lines.about(s.predecessor_label)) if again is not None
            else _not_republished(s, lines)
        )
    conn.close()

    report = ReplayReport(
        workdir=workdir,
        catalog=copy,
        online=online,
        entries=[entries[s.label] for s in successors],
        sweep=lines,
        live_db_unchanged=_file_sha256(live) == before_bytes,
    )
    print_summary(report)
    return report


def print_summary(report: ReplayReport) -> None:
    """The comparison block: the original run's successors against what the replay did."""
    entries = report.entries
    counts = {status: sum(1 for e in entries if e.status == status)
              for status in (SAME, SAME_CONTENT, DIFFERS, NOT_REPUBLISHED, NOT_REPLAYED)}
    typer.echo("\n── replay against the original run ──")
    typer.echo(
        f"successors in the catalog: {report.found}; re-published by the replay: {report.republished} "
        f"(digest same {counts[SAME]}, same content {counts[SAME_CONTENT]}, differs {counts[DIFFERS]}); "
        f"not re-published {counts[NOT_REPUBLISHED]}; not replayed {counts[NOT_REPLAYED]}"
    )
    for e in entries:
        head = f"  {e.original.predecessor_label} → {e.original.version}: {e.status}"
        if e.replayed is not None and e.replayed.version != e.original.version:
            head += f" (replayed as {e.replayed.version})"
        typer.echo(head + (f" — {e.reason}" if e.reason else ""))
        if e.moved_files:
            typer.echo(f"      moved: {', '.join(e.moved_files)}")
    originals = {e.original.predecessor_label for e in entries}
    refused = {label: block for label, block in report.sweep.refused.items() if label not in originals}
    held = {label: block for label, block in report.sweep.held.items() if label not in originals}
    if refused:
        typer.echo(f"\nrefused in the replay, no successor in the catalog ({len(refused)}):")
        for block in refused.values():
            for line in block:
                typer.echo(f"  {line}")
    if held:
        typer.echo(f"\nheld in the replay, no successor in the catalog ({len(held)}):")
        for block in held.values():
            for line in block:
                typer.echo(f"  {line}")
    if report.online:
        typer.secho(
            "online: live sources were asked again today and may answer differently than on the day "
            "of the original run; a difference here can be theirs.",
            fg=typer.colors.YELLOW,
        )
    if report.live_db_unchanged:
        typer.echo(f"live DB byte-identical before and after; scratch: {report.workdir}")
    else:
        typer.secho(
            "live DB bytes changed during the replay. The replay opened it read-only, so this is "
            "another writer (a running server counts downloads); check before trusting the copy.",
            fg=typer.colors.YELLOW,
        )
