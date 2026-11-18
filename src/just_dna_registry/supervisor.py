"""`registry supervise` (0.34): run the server as a child, and move it to another release on request.

The API side is `services/deploy.py`, which explains why the work is split: the server writes a request into
the deploy folder, and this process, which outlives the server, carries it out. One move:

1. **prepare** with the server still serving: on a clone, refuse tracked changes, `git fetch --tags origin`
   and find the tag `vX.Y.Z`; on a PyPI install, ask PyPI for the version. A failure here is `refused` and
   touches nothing.
2. **stop** the server (SIGTERM, so open requests finish, for up to `deploy_stop_seconds`; then SIGKILL).
3. **apply**: `git checkout --detach vX.Y.Z` or `uv add --no-sync 'just-dna-registry[server]==X.Y.Z'`, then
   `uv sync --inexact` (extras from `REGISTRY_DEPLOY_EXTRAS`).
4. **start** and **check**: `/health` must answer `status: ok` with the target's version within
   `deploy_health_seconds`.
5. Anything failing after step 2 **rolls back** to the commit or version recorded at step 1, checked the same
   way. `rolled_back` means the box serves what it served before; `failed` means even that did not come up,
   and the shell is needed after all.

The source is read off the folder the supervisor runs in (`detect_source`): a git clone of this package, or a
uv project that depends on it. A clone cannot become a PyPI install by request; that switch is a new folder,
set up once by hand (docs/UPGRADE.md).

**The supervisor's own code moves at its own next start, not with the server's.** It has imported what it
runs before the move; `GET /admin/deploy` names its version beside the server's.

A child that exits on its own is started again after `RESTART_BACKOFF_SECONDS`, and logged; that is the
supervisor being a supervisor, not a deploy.
"""

import logging
import os
import signal
import subprocess
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from just_dna_registry import __version__
from just_dna_registry.config import Settings
from just_dna_registry.services.deploy import (
    HEARTBEAT_FILE,
    HISTORY_KEEP,
    PACKAGE,
    REQUEST_FILE,
    STATE_FILE,
    Point,
    deploy_root,
    read_request,
    read_state,
    runs_in_progress,
    stamp,
    write_json,
)

log = logging.getLogger("just_dna_registry.supervisor")

RESTART_BACKOFF_SECONDS = 5.0
#: A failing step's output kept in the supervisor's own log, never in the served record (it holds paths).
OUTPUT_TAIL_LINES = 20

Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


def run_command(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


class StepFailed(Exception):
    """One step of a move failed; the message is served, so it names commands and versions, never paths."""


def _checked(runner: Runner, argv: list[str], cwd: Path, what: str) -> str:
    result = runner(argv, cwd)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout or "").splitlines()[-OUTPUT_TAIL_LINES:])
        log.error("%s exited %s:\n%s", what, result.returncode, tail)
        raise StepFailed(f"{what} exited {result.returncode}")
    return result.stdout


class Source(Protocol):
    kind: str

    def current(self) -> Point: ...

    def prepare(self, version: str) -> None: ...

    def apply(self, version: str) -> None: ...

    def restore(self, point: Point) -> None: ...


def _pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sync_argv(extras: str) -> list[str]:
    argv = ["uv", "sync", "--inexact"]
    for extra in extras.split():
        argv += ["--extra", extra]
    return argv


@dataclass
class GitSource:
    """A clone of this package: a move checks out a release tag."""

    root: Path
    extras: str
    runner: Runner = run_command
    kind: str = "git"

    def current(self) -> Point:
        version = (_pyproject(self.root).get("project") or {}).get("version")
        revision = _checked(self.runner, ["git", "rev-parse", "HEAD"], self.root, "git rev-parse").strip()
        return Point(version=version, revision=revision)

    def prepare(self, version: str) -> None:
        dirty = _checked(
            self.runner, ["git", "status", "--porcelain", "--untracked-files=no"], self.root, "git status"
        )
        if dirty.strip():
            raise StepFailed("the clone has uncommitted changes to tracked files; commit or discard them first")
        _checked(self.runner, ["git", "fetch", "--tags", "--quiet", "origin"], self.root, "git fetch")
        probe = self.runner(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/v{version}^{{commit}}"], self.root)
        if probe.returncode != 0:
            raise StepFailed(f"no tag v{version} on origin")

    def apply(self, version: str) -> None:
        self._checkout(f"v{version}")

    def restore(self, point: Point) -> None:
        if point.revision is None:
            raise StepFailed("no commit was recorded to return to")
        self._checkout(point.revision)

    def _checkout(self, ref: str) -> None:
        _checked(self.runner, ["git", "checkout", "--detach", "--quiet", ref], self.root, "git checkout")
        _checked(self.runner, sync_argv(self.extras), self.root, "uv sync")


def pypi_has(version: str) -> bool:
    """Whether PyPI publishes `version` of this package."""
    response = httpx.get(f"https://pypi.org/pypi/{PACKAGE}/{version}/json", timeout=30, follow_redirects=True)
    return response.status_code == 200


@dataclass
class PypiSource:
    """A uv project depending on this package: a move pins another published version."""

    root: Path
    extras: str
    runner: Runner = run_command
    exists: Callable[[str], bool] = pypi_has
    kind: str = "pypi"

    def current(self) -> Point:
        lock = self.root / "uv.lock"
        if lock.is_file():
            for package in tomllib.loads(lock.read_text(encoding="utf-8")).get("package", []):
                if package.get("name") == PACKAGE:
                    return Point(version=package.get("version"))
        return Point(version=None)

    def prepare(self, version: str) -> None:
        try:
            found = self.exists(version)
        except httpx.HTTPError as exc:
            raise StepFailed(f"PyPI could not be asked about {version}: {type(exc).__name__}") from exc
        if not found:
            raise StepFailed(f"{version} is not on PyPI")

    def apply(self, version: str) -> None:
        extras = ",".join(self.extras.split())
        requirement = f"{PACKAGE}[{extras}]=={version}" if extras else f"{PACKAGE}=={version}"
        _checked(self.runner, ["uv", "add", "--no-sync", requirement], self.root, "uv add")
        _checked(self.runner, ["uv", "sync", "--inexact"], self.root, "uv sync")

    def restore(self, point: Point) -> None:
        if point.version is None:
            raise StepFailed("no version was recorded to return to")
        self.apply(point.version)


def detect_source(root: Path, extras: str) -> GitSource | PypiSource | None:
    """A clone of this package, a uv project depending on it, or neither."""
    project = _pyproject(root).get("project") or {}
    if project.get("name") == PACKAGE:
        return GitSource(root, extras) if (root / ".git").exists() else None
    dependencies = project.get("dependencies") or []
    if any(str(dep).replace("_", "-").startswith(PACKAGE) for dep in dependencies):
        return PypiSource(root, extras)
    return None


def fetch_health(url: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(url, timeout=5)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    return response.json()


@dataclass
class Supervisor:
    settings: Settings
    root: Path
    source: GitSource | PypiSource
    child_argv: list[str]
    health_url: str
    health: Callable[[str], dict[str, Any] | None] = fetch_health
    poll_seconds: float = 1.0
    child: subprocess.Popen[bytes] | None = field(default=None, init=False)
    _next_restart: float = field(default=0.0, init=False)

    @property
    def folder(self) -> Path:
        return deploy_root(self.settings)

    # ── the child ────────────────────────────────────────────────────────────────────────────────

    def start_child(self) -> None:
        log.info("starting the server: %s", " ".join(self.child_argv))
        self.child = subprocess.Popen(self.child_argv, cwd=self.root)

    def child_running(self) -> bool:
        return self.child is not None and self.child.poll() is None

    def stop_child(self) -> None:
        if not self.child_running():
            return
        assert self.child is not None
        self.child.send_signal(signal.SIGTERM)
        try:
            self.child.wait(timeout=self.settings.deploy_stop_seconds)
        except subprocess.TimeoutExpired:
            log.warning("the server did not stop in %ss; killing it", self.settings.deploy_stop_seconds)
            self.child.kill()
            self.child.wait()

    def wait_healthy(self, version: str | None) -> str | None:
        """`None` once `/health` says `ok` and `version`; else why not, when time ran out."""
        deadline = time.monotonic() + self.settings.deploy_health_seconds
        seen = "no answer"
        while time.monotonic() < deadline:
            if not self.child_running():
                code = self.child.returncode if self.child is not None else None
                return f"the server exited ({code}) before answering /health"
            body = self.health(self.health_url)
            if body is not None:
                seen = f"status {body.get('status')!r}, version {body.get('version')!r}"
                if body.get("status") == "ok" and (version is None or body.get("version") == version):
                    return None
            time.sleep(min(1.0, self.poll_seconds))
        return f"/health did not answer ok with {version} in {self.settings.deploy_health_seconds}s ({seen})"

    # ── the record ───────────────────────────────────────────────────────────────────────────────

    def heartbeat(self) -> None:
        write_json(self.folder / HEARTBEAT_FILE, {
            "at": stamp(), "pid": os.getpid(), "version": __version__, "source": self.source.kind,
        })

    def _save(self, state: dict[str, Any]) -> None:
        write_json(self.folder / STATE_FILE, state)

    def _progress(self, record: dict[str, Any], phase: str) -> None:
        record["phase"] = phase
        state = read_state(self.settings)
        state["last"] = record
        self._save(state)
        log.info("deploy %s to %s: %s", record["id"], record["version"], phase)

    def _finish(self, record: dict[str, Any], outcome: str, **points: Point) -> None:
        record.update(phase="done", outcome=outcome, ended=stamp())
        state = read_state(self.settings)
        for key, point in points.items():
            state[key] = point.to_json()
        state["last"] = record
        state["history"] = [record, *(state.get("history") or [])][:HISTORY_KEEP]
        self._save(state)
        log.info("deploy %s to %s: %s", record["id"], record["version"], outcome)

    def recover(self) -> None:
        """A supervisor that died mid-move left `last` without an outcome: say so, once."""
        state = read_state(self.settings)
        last = state.get("last")
        if last and last.get("outcome") is None:
            last["detail"] = f"the supervisor stopped during {last.get('phase')}"
            self._finish(last, "interrupted")
        try:
            state = read_state(self.settings)
            state["current"] = self.source.current().to_json()
            self._save(state)
        except StepFailed as exc:
            log.warning("could not read what this folder runs: %s", exc)

    # ── one move ─────────────────────────────────────────────────────────────────────────────────

    def handle(self, request: dict[str, Any]) -> None:
        (self.folder / REQUEST_FILE).unlink(missing_ok=True)
        record = dict(request, started=stamp())
        version = str(record["version"])
        self._progress(record, "preparing")
        try:
            self.source.prepare(version)
            before = self.source.current()
        except StepFailed as exc:
            record["detail"] = str(exc)
            self._finish(record, "refused")
            return
        busy = runs_in_progress(self.settings)
        if busy:
            record["detail"] = f"a maintenance run started meanwhile: {', '.join(busy)}"
            self._finish(record, "refused")
            return

        self._progress(record, "stopping")
        self.stop_child()
        failure: str | None
        try:
            self._progress(record, "applying")
            self.source.apply(version)
            self._progress(record, "checking")
            self.start_child()
            failure = self.wait_healthy(version)
        except StepFailed as exc:
            failure = str(exc)
        if failure is None:
            self._finish(record, "deployed", previous=before, current=self.source.current())
            return

        record["detail"] = failure
        self._progress(record, "rolling_back")
        self.stop_child()
        try:
            self.source.restore(before)
            self.start_child()
            again = self.wait_healthy(before.version)
        except StepFailed as exc:
            again = str(exc)
        if again is None:
            self._finish(record, "rolled_back", current=before)
            return
        record["detail"] = f"{failure}; restoring {before.version} failed too: {again}"
        if not self.child_running():
            self.start_child()
        self._finish(record, "failed")

    # ── the loop ─────────────────────────────────────────────────────────────────────────────────

    def step(self) -> None:
        """One turn: heartbeat, a waiting request, or a server that exited on its own."""
        self.heartbeat()
        request = read_request(self.settings)
        if request is not None:
            self.handle(request)
            return
        if not self.child_running() and time.monotonic() >= self._next_restart:
            if self.child is not None:
                log.warning("the server exited (%s); starting it again", self.child.returncode)
            self.start_child()
            self._next_restart = time.monotonic() + RESTART_BACKOFF_SECONDS

    def run(self) -> None:
        stopping = False

        def stop(signum: int, _frame: object) -> None:
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.recover()
        try:
            while not stopping:
                self.step()
                time.sleep(self.poll_seconds)
        finally:
            self.stop_child()
            (self.folder / HEARTBEAT_FILE).unlink(missing_ok=True)


def child_argv(host: str, port: int, mode: str | None) -> list[str]:
    argv = ["uv", "run", "--no-sync", "registry", "serve", "--host", host, "--port", str(port)]
    if mode:
        argv += ["--mode", mode]
    return argv


def health_url(host: str, port: int) -> str:
    local = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    return f"http://{local}:{port}/health"

