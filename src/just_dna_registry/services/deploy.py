"""Moving the running server to another release over the API (0.34): the files the two sides share.

The person, 2026-11-18: "build the upgrade procedure so that you'd be able to rewind git deployments or run
server from pypi with an admin API call from here. Less ssh logins for me (maintenance only)".

A process cannot replace its own code and come back, so the work is split in two. `registry supervise`
(`just_dna_registry.supervisor`) runs the server as its child and outlives it; the server's
`POST /admin/deploy` only writes a request into this folder, and `GET /admin/deploy` reads what the
supervisor recorded. Nothing here starts, stops or installs anything.

Four rules keep a deploy from costing the ssh login it exists to save:

- **Only a release moves.** A target is a plain `X.Y.Z` (or `previous`): a git tag `vX.Y.Z` on a clone, the
  published version on a PyPI install. Never a branch or a commit a site admin typed.
- **Never below `DEPLOY_FLOOR`**, the first release that carries the supervisor's counterpart: a rewind
  there would remove the route back, and the next move would need the shell again.
- **Not while the box is busy**: a maintenance run still going (its `run.json` names a live `pid`), or a
  publish holding or queued on the enrichment gate. The run shares the venv the move replaces.
- **A move that does not come up is undone by the supervisor**, which reads `/health` for `status: ok` and
  the target's version, and otherwise restores what ran before.

Off unless `REGISTRY_DEPLOY` is set: a site-admin key that can call this can swap the running code, which
is more than yanking (CLAUDE.md, *A site admin is an elevated role*).
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from just_dna_registry.config import Settings
from just_dna_registry.maintenance import list_runs, read_record

DEPLOY_DIRNAME = "deploy"
REQUEST_FILE = "request.json"
STATE_FILE = "state.json"
HEARTBEAT_FILE = "supervisor.json"
PACKAGE = "just-dna-registry"
#: The first release `registry supervise` and `POST /admin/deploy` exist in.
DEPLOY_FLOOR = "0.34.0"
#: A supervisor whose heartbeat is older than this is taken as gone.
HEARTBEAT_FRESH_SECONDS = 30
#: How many finished deploys `state.json` keeps.
HISTORY_KEEP = 20
PREVIOUS = "previous"
_RELEASE = re.compile(r"^\d+\.\d+\.\d+$")


class DeployRefused(Exception):
    """A request the API turns away before writing it; `code` is the response's `detail`."""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Point:
    """What a box ran: a release and, on a clone, the commit."""

    version: str | None
    revision: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"version": self.version, "revision": self.revision}

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "Point | None":
        if not data:
            return None
        return cls(version=data.get("version"), revision=data.get("revision"))


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def deploy_root(settings: Settings) -> Path:
    """`REGISTRY_DEPLOY_DIR`, else `deploy/` beside the DB."""
    return settings.deploy_dir or (settings.db_path.resolve().parent / DEPLOY_DIRNAME)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Whole or absent: written beside, then renamed over, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}.partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_state(settings: Settings) -> dict[str, Any]:
    return read_json(deploy_root(settings) / STATE_FILE) or {}


def read_request(settings: Settings) -> dict[str, Any] | None:
    return read_json(deploy_root(settings) / REQUEST_FILE)


def read_heartbeat(settings: Settings) -> dict[str, Any] | None:
    return read_json(deploy_root(settings) / HEARTBEAT_FILE)


def supervised(settings: Settings, *, now: datetime | None = None) -> bool:
    """Whether a supervisor wrote its heartbeat within `HEARTBEAT_FRESH_SECONDS`."""
    beat = read_heartbeat(settings)
    if not beat or not beat.get("at"):
        return False
    age = ((now or datetime.now(UTC)) - datetime.fromisoformat(beat["at"])).total_seconds()
    return age <= HEARTBEAT_FRESH_SECONDS


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def runs_in_progress(settings: Settings) -> list[str]:
    """Maintenance runs whose record has no end and whose process is alive (0.34 records `pid`).

    A record with no `pid` predates 0.34 and is not counted: a run that never ended there was killed,
    and counting it would refuse every deploy for good."""
    busy: list[str] = []
    for path in list_runs(settings):
        record = read_record(path)
        pid = record.get("pid")
        if record.get("ended") is None and isinstance(pid, int) and pid_alive(pid):
            busy.append(record["id"])
    return busy


def release_tuple(text: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def parse_target(text: str) -> tuple[int, int, int]:
    """A release this box may move to: plain `X.Y.Z`, not below `DEPLOY_FLOOR`."""
    if not _RELEASE.match(text):
        raise DeployRefused(
            "invalid_version", f"a deploy target is a release, X.Y.Z (or {PREVIOUS!r}); got {text!r}", status=422
        )
    version = release_tuple(text)
    if version < release_tuple(DEPLOY_FLOOR):
        raise DeployRefused(
            "below_deploy_floor",
            f"{text} predates {DEPLOY_FLOOR}, the first release with the deploy route; moving there would "
            "leave no way back but the shell",
            status=422,
        )
    return version


def request_deploy(
    settings: Settings,
    target: str,
    *,
    requested_by: str,
    running: str,
    gate_occupancy: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Check a request and leave it for the supervisor; returns the record `GET /admin/deploy` shows.

    `running` is the version this process serves; `gate_occupancy` the enrichment gate's
    (`EnrichmentGate.occupancy`), whose active or queued permits are publishes a restart would cut."""
    if not settings.deploy:
        raise DeployRefused("deploy_not_enabled", "this box does not take deploys over the API (REGISTRY_DEPLOY is off)")
    if not supervised(settings):
        raise DeployRefused(
            "not_supervised", "no supervisor is running here (start the server with `registry supervise`)"
        )
    state = read_state(settings)
    if read_request(settings) is not None or (state.get("last") or {}).get("outcome", "") is None:
        raise DeployRefused("deploy_in_progress", "a deploy is already waiting or running")
    version = target
    if target == PREVIOUS:
        previous = Point.from_json(state.get("previous"))
        if previous is None or previous.version is None:
            raise DeployRefused("no_previous", "nothing has been recorded as running before this release")
        version = previous.version
    parse_target(version)
    if version == running:
        raise DeployRefused("already_running", f"this box already serves {running}")
    busy = runs_in_progress(settings)
    if busy:
        raise DeployRefused("maintenance_run_in_progress", f"a maintenance run is still going: {', '.join(busy)}")
    if gate_occupancy and (gate_occupancy.get("active", 0) or gate_occupancy.get("queued", 0)):
        raise DeployRefused("server_busy", "a publish holds or waits for the enrichment gate; try again after it")
    record = {
        "id": uuid4().hex[:12],
        "version": version,
        "requested_by": requested_by,
        "requested_at": stamp(),
        "phase": "pending",
        "outcome": None,
        "detail": None,
        "started": None,
        "ended": None,
        "from_version": running,
        "from_revision": (Point.from_json(state.get("current")) or Point(None)).revision,
    }
    write_json(deploy_root(settings) / REQUEST_FILE, record)
    return record


def deploy_status(settings: Settings, *, running: str) -> dict[str, Any]:
    """Everything `GET /admin/deploy` serves: no path, only versions, commits and outcomes."""
    state = read_state(settings)
    beat = read_heartbeat(settings) or {}
    return {
        "enabled": settings.deploy,
        "supervised": supervised(settings),
        "source": beat.get("source"),
        "supervisor_version": beat.get("version"),
        "running": running,
        "floor": DEPLOY_FLOOR,
        "current": state.get("current"),
        "previous": state.get("previous"),
        "pending": read_request(settings),
        "last": state.get("last"),
        "history": list(state.get("history") or []),
        "busy": runs_in_progress(settings),
    }
