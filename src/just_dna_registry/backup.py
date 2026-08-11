"""
Point-in-time snapshots of the catalog DB, taken before anything destructive.

**Scope is the DB, deliberately, and artifacts are not in it.** The catalog is a *projection* of each
version's `manifest.json`, but the manifests live in storage alongside multi-hundred-megabyte parquet
sets — copying those on every `remove-module` would make the guard so slow an operator would reach for
`--no-backup` as a habit, which is worse than no guard. So a snapshot restores the *index*: accounts,
keys, namespaces, memberships, versions and their facets. Artifacts are content-addressed under
`{namespace}/{name}/{version}` and are only ever removed by an explicit `storage.remove`, so a restore
after an accidental DB wipe finds its bytes still there.

What this does **not** protect against is the pair together: `purge-test-data --apply` removes rows
*and* artifact bytes, and restoring the DB afterwards gives you rows pointing at storage keys that no
longer exist. That is why the purge prints its storage keys before touching them, and why the artifact
side of a real disaster needs the storage backend's own versioning (HF revisions, S3 versioning) rather
than anything here.

Uses SQLite's own online-backup API rather than a file copy: it is atomic against a live writer, so a
snapshot taken while the server is up is still a consistent DB rather than a torn page.
"""

import logging
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from just_dna_registry.config import Settings
from just_dna_registry.db.schema import connect

logger = logging.getLogger("registry.backup")

#: Kept next to the DB rather than under a temp dir, because a snapshot an operator cannot find after
#: the shell closes is not a backup. Overridable via `REGISTRY_BACKUP_DIR`.
BACKUP_DIRNAME = "backups"

#: `registry-00001-20260811T183000Z-purge-test-data.db` — a rolling index, then when, then before what.
#: Zero-padded to five so the sequence sorts lexically for the ten thousand snapshots before it does not.
_NAME_RE = re.compile(r"^registry-(\d+)-")
_INDEX_WIDTH = 5


def backup_dir(settings: Settings) -> Path:
    """Where snapshots go: `REGISTRY_BACKUP_DIR`, else `backups/` beside the DB file."""
    return settings.backup_dir or (settings.db_path.resolve().parent / BACKUP_DIRNAME)


def _stamp() -> str:
    """UTC, second resolution, filename-safe and lexically sortable."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def next_index(target_dir: Path) -> int:
    """One past the highest index present — **never** a reused or recycled number.

    Taking a backup is the one action here that must be safe, so the sequence only ever counts up: it
    is not a ring buffer, nothing is rotated out, and snapshot 3 is still snapshot 3 after snapshot 8
    exists. That means they accumulate, which is the intended trade — a full disk is an operator's
    problem to notice, where an overwritten snapshot is a silent loss of the only copy of a state
    somebody deliberately preserved. Pruning is a separate, explicit act.

    Derived from the filenames rather than from a counter file: a counter that drifts from what is on
    disk (restored dir, hand-copied snapshot, half-finished migration) would start handing out numbers
    that already exist, and the whole point is that they never collide.
    """
    highest = 0
    if target_dir.is_dir():
        for path in target_dir.glob("registry-*.db"):
            match = _NAME_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def create_backup(settings: Settings, *, reason: str) -> Optional[Path]:
    """Snapshot the catalog DB and return the file, or `None` when there is no DB yet.

    `reason` goes in the filename, so `ls` alone tells an operator what a snapshot was taken ahead of
    — the difference between "before I purged test data" and "before I reset the DB" is exactly what
    you need at 3am and exactly what a bare timestamp does not carry.

    A missing DB is `None` rather than an error: `init-db` and a first `reset-db` are legitimately
    called with nothing to snapshot, and raising there would make the guard the thing that breaks a
    fresh install.
    """
    source = settings.db_path
    if not source.exists() or source.stat().st_size == 0:
        return None

    target_dir = backup_dir(settings)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_reason = "".join(c if c.isalnum() or c in "-_" else "-" for c in reason).strip("-")

    # Belt and braces on the one guarantee this module owes: never clobber an existing snapshot.
    # `next_index` already skips every number in use, so the loop is for the case it cannot see — two
    # operators running a destructive command in the same second, where both computed the same index
    # before either wrote. Bounded rather than `while True`: if something is wrong enough that a
    # thousand consecutive names are taken, failing is better than spinning.
    index = next_index(target_dir)
    for candidate in range(index, index + 1000):
        target = target_dir / f"registry-{candidate:0{_INDEX_WIDTH}d}-{_stamp()}-{safe_reason}.db"
        if not target.exists():
            break
    else:
        raise RuntimeError(f"could not find a free snapshot name in {target_dir} from index {index}")

    # `connect()` rather than `sqlite3.connect` so the source is opened exactly as the app opens it.
    # The destination is a plain handle: it is a file we are creating, not a catalog we are serving.
    src = connect(source)
    try:
        dest = sqlite3.connect(target)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()

    logger.info("catalog snapshot written to %s (before: %s)", target, reason)
    return target


def restore_backup(settings: Settings, snapshot: Path) -> Path:
    """Replace the live DB with `snapshot`, after snapshotting the DB being replaced.

    The pre-restore snapshot is not ceremony: restoring the wrong file is the most likely mistake in
    this whole module, and without it that mistake is unrecoverable. Copied rather than moved so the
    snapshot stays where it was and can be restored again.
    """
    snapshot = Path(snapshot)
    if not snapshot.is_file():
        raise FileNotFoundError(f"no such snapshot: {snapshot}")
    # Verify it is a readable catalog before overwriting anything with it.
    probe = sqlite3.connect(snapshot)
    try:
        probe.execute("SELECT COUNT(*) FROM versions").fetchone()
    finally:
        probe.close()

    create_backup(settings, reason="restore")
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot, settings.db_path)
    logger.info("catalog restored from %s", snapshot)
    return settings.db_path


def list_backups(settings: Settings) -> list[Path]:
    """Snapshots, newest first — ordered by the rolling index, not by mtime.

    The index is the authority on age because it is what the sequence guarantees: a snapshot copied
    between hosts or restored from an archive keeps its number and loses its mtime.
    """
    target_dir = backup_dir(settings)
    if not target_dir.is_dir():
        return []
    found = [p for p in target_dir.glob("registry-*.db") if _NAME_RE.match(p.name)]
    return sorted(found, key=lambda p: int(_NAME_RE.match(p.name).group(1)), reverse=True)
