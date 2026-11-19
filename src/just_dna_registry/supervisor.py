"""`registry supervise` (0.34): run the server as a child, and move it to another release on request.

The API side is `services/deploy.py`, which explains why the work is split: the server writes a request into
the deploy folder, and this process, which outlives the server, carries it out. One move:

1. **prepare** with the server still serving: on a clone, refuse tracked changes, `git fetch --tags origin`
   and find the tag `vX.Y.Z`; from PyPI, ask PyPI when the version was uploaded and install it into uv's cache
   with `uvx`. A failure here is `refused` and touches nothing.
2. **stop** the server (SIGTERM, so open requests finish, for up to `deploy_stop_seconds`; then SIGKILL).
3. **apply**: `git checkout --detach vX.Y.Z` then `uv sync --inexact --frozen` (the release's own lock,
   never rewritten); from PyPI nothing is left to do, the next start runs
   `uvx --from 'just-dna-registry[server]==X.Y.Z' --exclude-newer <upload time> registry serve`
   (extras from `REGISTRY_DEPLOY_EXTRAS`).
4. **start** and **check**: `/health` must answer `status: ok` with the target's version within
   `deploy_health_seconds`.
5. Anything failing after step 2 **rolls back** to the commit or version recorded at step 1, checked the same
   way. `rolled_back` means the box serves what it served before; `failed` means even that did not come up,
   and the shell is needed after all.

The source is read off the folder the supervisor runs in (`detect_source`): a git clone of this package moves
by tag; any other folder (one holding `.env` and the data) runs from PyPI through `uvx`, which keeps no clone,
no project and no lock file in step. A clone cannot become a PyPI box by request; that is a start command
changed once by hand (docs/UPGRADE.md).

**The supervisor's own code moves at its own next start, not with the server's.** It has imported what it
runs before the move; `GET /admin/deploy` names its version beside the server's.

A child that exits on its own is started again after `RESTART_BACKOFF_SECONDS`, and logged; that is the
supervisor being a supervisor, not a deploy.
"""

import fcntl
import io
import logging
import os
import signal
import subprocess
import tarfile
import tempfile
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
#: Held (flock) by the one supervisor of a folder, in that folder: two boxes started from one clone would
#: each move the other's code (0.34.1). Untracked and git-ignored; the lock goes with the process.
FOLDER_LOCK = ".registry-supervise.lock"
#: A failing step's output kept in the supervisor's own log, never in the served record (it holds paths).
OUTPUT_TAIL_LINES = 20

Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


def run_command(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


class FolderTaken(Exception):
    """Another supervisor already runs from this folder; the message names its pid."""


class FolderLock:
    """One supervisor per folder, whatever box each serves: a move checks out or pins the folder, so two
    supervisors on one folder (production and the test server from a shared clone, say) would move both."""

    def __init__(self, root: Path) -> None:
        self.path = root / FOLDER_LOCK
        self._handle: Any = None

    def acquire(self) -> None:
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            holder = handle.read().strip() or "another process"
            handle.close()
            raise FolderTaken(
                f"another `registry supervise` (pid {holder}) already runs from this folder; each server "
                "needs a folder of its own, or a move of one would move the other"
            ) from None
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle, fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


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

    def serve_argv(self, serve: list[str]) -> list[str]: ...


def _pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sync_argv(extras: str, *, frozen: bool = False) -> list[str]:
    """`--frozen` on a clone: install the release's committed lock exactly and never rewrite it, or the
    rewritten `uv.lock` is a tracked change the next move refuses (found rehearsing, 2026-11-18)."""
    argv = ["uv", "sync", "--inexact", *(["--frozen"] if frozen else [])]
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
        changed = sorted({line[3:].strip() for line in dirty.splitlines() if line.strip()})
        if changed:
            raise StepFailed(
                f"the clone has uncommitted changes to tracked files ({', '.join(changed)}); "
                "commit or discard them first"
            )
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

    def serve_argv(self, serve: list[str]) -> list[str]:
        return ["uv", "run", "--no-sync", "registry", "serve", *serve]

    def _checkout(self, ref: str) -> None:
        _checked(self.runner, ["git", "checkout", "--detach", "--quiet", ref], self.root, "git checkout")
        _checked(self.runner, sync_argv(self.extras, frozen=True), self.root, "uv sync")


def pypi_has(version: str) -> bool:
    """Whether PyPI publishes `version` of this package."""
    response = httpx.get(f"https://pypi.org/pypi/{PACKAGE}/{version}/json", timeout=30, follow_redirects=True)
    return response.status_code == 200


@dataclass(frozen=True)
class PypiRelease:
    """What PyPI says about one version of this package: when its dependencies are pinned to, and its sdist."""

    pinned_at: str
    sdist_url: str | None


def pypi_release(version: str) -> PypiRelease:
    """Ask PyPI about `version`: its upload time, one minute late, as uv's `--exclude-newer` takes it, and its
    sdist, which carries the release's `uv.lock` from 0.34.2 on."""
    try:
        response = httpx.get(f"https://pypi.org/pypi/{PACKAGE}/{version}/json", timeout=30, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise StepFailed(f"PyPI could not be asked about {version}: {type(exc).__name__}") from exc
    if response.status_code == 404:
        raise StepFailed(f"{version} is not on PyPI")
    if response.status_code != 200:
        raise StepFailed(f"PyPI answered {response.status_code} for {version}")
    files = response.json().get("urls", [])
    uploads = [f["upload_time_iso_8601"] for f in files if f.get("upload_time_iso_8601")]
    if not uploads:
        raise StepFailed(f"PyPI lists no files for {version}")
    latest = max(datetime.fromisoformat(u) for u in uploads)
    sdist = next((f["url"] for f in files if f.get("packagetype") == "sdist"), None)
    return PypiRelease((latest + timedelta(minutes=1)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), sdist)


def fetch_bytes(url: str) -> bytes:
    try:
        response = httpx.get(url, timeout=120, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise StepFailed(f"the sdist could not be downloaded: {type(exc).__name__}") from exc
    return response.content


#: The two files `uv export` needs, read out of an sdist by name and nothing else extracted.
_LOCK_MEMBERS = ("pyproject.toml", "uv.lock")


def export_locked_constraints(sdist: bytes, extras: str, out: Path, runner: Runner) -> bool:
    """Write the release's locked dependency set to `out` as a constraints file; `False` when the sdist carries
    no `uv.lock` (releases before 0.34.2), and the caller falls back to the upload-time pin alone."""
    found: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(sdist), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = member.name.split("/")
            if member.isfile() and len(parts) == 2 and parts[1] in _LOCK_MEMBERS:
                handle = archive.extractfile(member)
                if handle is not None:
                    found[parts[1]] = handle.read()
    if set(found) != set(_LOCK_MEMBERS):
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name, data in found.items():
            (work / name).write_bytes(data)
        argv = ["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "--quiet", "--output-file", str(out)]
        for extra in extras.split():
            argv += ["--extra", extra]
        _checked(runner, argv, work, "uv export")
    return True


@dataclass
class UvxSource:
    """Run from PyPI with `uvx` (0.34.2): no clone and no project, only the folder holding `.env` and data.

    A move installs the target into uv's cache with the server still serving (a failed install is a
    `refused`, nothing stopped), then restarts the server from it; a rewind restarts from the previous one,
    already cached. Dependencies are the release's own lock where its sdist carries one (exported to
    `constraints/<version>.txt` in the deploy folder, passed as `uvx -c`), and pinned to its upload time
    (`--exclude-newer`) in any case, which is all a release from before 0.34.2 gets."""

    root: Path
    extras: str
    version: str
    pinned_at: str
    constraints_dir: Path
    runner: Runner = run_command
    release: Callable[[str], PypiRelease] = pypi_release
    download: Callable[[str], bytes] = fetch_bytes
    kind: str = "uvx"
    _prepared: tuple[str, str] | None = field(default=None, init=False)

    def constraints(self, version: str) -> Path:
        return self.constraints_dir / f"{version}.txt"

    def _uvx(self, version: str, pinned_at: str) -> list[str]:
        extras = ",".join(self.extras.split())
        spec = f"{PACKAGE}[{extras}]=={version}" if extras else f"{PACKAGE}=={version}"
        locked = self.constraints(version)
        return ["uvx", "--from", spec, *(["-c", str(locked)] if locked.is_file() else []), "--exclude-newer", pinned_at]

    def current(self) -> Point:
        return Point(version=self.version, pinned_at=self.pinned_at)

    def prepare(self, version: str) -> None:
        release = self.release(version)
        if release.sdist_url and not self.constraints(version).is_file():
            exported = export_locked_constraints(
                self.download(release.sdist_url), self.extras, self.constraints(version), self.runner
            )
            if not exported:
                log.warning("%s carries no uv.lock in its sdist; dependencies pinned to its upload time only", version)
        _checked(self.runner, [*self._uvx(version, release.pinned_at), "registry", "--help"], self.root, "uvx install")
        self._prepared = (version, release.pinned_at)

    def apply(self, version: str) -> None:
        if self._prepared is None or self._prepared[0] != version:
            raise StepFailed(f"{version} was not prepared")
        self.version, self.pinned_at = self._prepared

    def restore(self, point: Point) -> None:
        if point.version is None or point.pinned_at is None:
            raise StepFailed("no version was recorded to return to")
        self.version, self.pinned_at = point.version, point.pinned_at

    def serve_argv(self, serve: list[str]) -> list[str]:
        return [*self._uvx(self.version, self.pinned_at), "registry", "serve", *serve]


def detect_source(
    root: Path, extras: str, *, recorded: Point | None, own_version: str, constraints_dir: Path,
    release: Callable[[str], PypiRelease] = pypi_release, download: Callable[[str], bytes] = fetch_bytes,
    runner: Runner = run_command,
) -> GitSource | UvxSource:
    """A git clone of this package moves by tag; any other folder runs from PyPI through `uvx`.

    From PyPI, the release served is the one the deploy state last recorded, with no network asked; else the
    supervisor's own, prepared once (asked of PyPI, its lock exported, installed). A restart of the supervisor,
    after a reboot say, must not quietly put back the release it was started as."""
    project = _pyproject(root).get("project") or {}
    if project.get("name") == PACKAGE and (root / ".git").exists():
        return GitSource(root, extras, runner=runner)
    if recorded is not None and recorded.version and recorded.pinned_at:
        return UvxSource(root, extras, recorded.version, recorded.pinned_at, constraints_dir,
                         runner=runner, release=release, download=download)
    source = UvxSource(root, extras, own_version, "", constraints_dir, runner=runner, release=release, download=download)
    source.prepare(own_version)
    source.apply(own_version)
    return source


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
    source: GitSource | UvxSource
    serve_args: list[str]
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
        argv = self.source.serve_argv(self.serve_args)
        log.info("starting the server: %s", " ".join(argv))
        self.child = subprocess.Popen(argv, cwd=self.root)

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

        lock = FolderLock(self.root)
        lock.acquire()  # before any signal handler or child: a refused start touches nothing
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
            lock.release()


def serve_args(host: str, port: int, mode: str | None) -> list[str]:
    """What follows `registry serve` for the child, whichever source launches it."""
    argv = ["--host", host, "--port", str(port)]
    if mode:
        argv += ["--mode", mode]
    return argv


def health_url(host: str, port: int) -> str:
    local = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    return f"http://{local}:{port}/health"

