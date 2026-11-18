"""Deploy over the API (0.34): `POST /admin/deploy` checks and records a move, `registry supervise` makes it.

The supervisor is driven against a real child process (a small HTTP server answering `/health` with the
version a fake source last installed), so stopping, starting, the health check and the rollback all run for
real; only what a move installs is faked. The git source runs against real repositories, with `uv sync`
the one command answered without running."""

import json
import os
import socket
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.maintenance import RUN_FILE, run_root
from just_dna_registry.services import deploy
from just_dna_registry.services.deploy import DEPLOY_FLOOR, DeployRefused, Point
from just_dna_registry.supervisor import GitSource, PypiSource, StepFailed, Supervisor, detect_source


def _settings(tmp_path: Path, **extra: object) -> Settings:
    return Settings(
        db_path=tmp_path / "registry.db", storage_backend="local", local_storage_dir=tmp_path / "artifacts",
        deploy_health_seconds=20, deploy_stop_seconds=10, **extra,
    )


def _beat(settings: Settings, *, age_seconds: int = 0) -> None:
    at = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat(timespec="seconds")
    deploy.write_json(deploy.deploy_root(settings) / deploy.HEARTBEAT_FILE,
                      {"at": at, "pid": os.getpid(), "version": DEPLOY_FLOOR, "source": "git"})


def _run_record(settings: Settings, name: str, **record: object) -> None:
    path = run_root(settings) / name
    path.mkdir(parents=True)
    (path / RUN_FILE).write_text(json.dumps({"id": name, "ended": None, **record}))


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# ── What the API refuses, and what it leaves for the supervisor ──────────────────────────────────────


def test_a_request_is_refused_until_the_box_is_enabled_and_supervised(tmp_path: Path) -> None:
    off = _settings(tmp_path)
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(off, "0.34.1", requested_by="ops", running="0.34.0")
    assert refused.value.code == "deploy_not_enabled"

    on = _settings(tmp_path, deploy=True)
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(on, "0.34.1", requested_by="ops", running="0.34.0")
    assert refused.value.code == "not_supervised"

    _beat(on, age_seconds=deploy.HEARTBEAT_FRESH_SECONDS + 30)  # a supervisor that went away
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(on, "0.34.1", requested_by="ops", running="0.34.0")
    assert refused.value.code == "not_supervised"
    assert deploy.read_request(on) is None


@pytest.mark.parametrize(("target", "code"), [
    ("main", "invalid_version"),
    ("v0.34.1", "invalid_version"),
    ("0.34.1rc1", "invalid_version"),
    ("0.33.1", "below_deploy_floor"),
    ("0.34.0", "already_running"),
])
def test_only_a_release_at_or_above_the_floor_and_not_the_running_one_is_taken(
    tmp_path: Path, target: str, code: str
) -> None:
    settings = _settings(tmp_path, deploy=True)
    _beat(settings)
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(settings, target, requested_by="ops", running="0.34.0")
    assert refused.value.code == code
    assert deploy.read_request(settings) is None


def test_a_live_maintenance_run_or_a_publish_on_the_gate_refuses_a_move(tmp_path: Path) -> None:
    settings = _settings(tmp_path, deploy=True)
    _beat(settings)
    _run_record(settings, "killed-before-0.34")  # no pid: predates the field, never counted
    _run_record(settings, "killed", pid=_dead_pid())
    assert deploy.runs_in_progress(settings) == []
    accepted = deploy.request_deploy(settings, "0.34.1", requested_by="ops", running="0.34.0",
                                     gate_occupancy={"active": 0, "queued": 0, "limit": 1})
    assert accepted["version"] == "0.34.1"
    (deploy.deploy_root(settings) / deploy.REQUEST_FILE).unlink()

    _run_record(settings, "upgrade-going", pid=os.getpid())
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(settings, "0.34.1", requested_by="ops", running="0.34.0")
    assert refused.value.code == "maintenance_run_in_progress"
    assert "upgrade-going" in refused.value.message

    quiet = _settings(tmp_path / "other", deploy=True)
    _beat(quiet)
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(quiet, "0.34.1", requested_by="ops", running="0.34.0",
                              gate_occupancy={"active": 0, "queued": 1, "limit": 1})
    assert refused.value.code == "server_busy"


def test_one_request_at_a_time_and_previous_resolves_to_what_ran_before(tmp_path: Path) -> None:
    settings = _settings(tmp_path, deploy=True)
    _beat(settings)
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(settings, "previous", requested_by="ops", running="0.34.1")
    assert refused.value.code == "no_previous"

    deploy.write_json(deploy.deploy_root(settings) / deploy.STATE_FILE, {
        "current": {"version": "0.34.1", "revision": "b" * 40},
        "previous": {"version": "0.34.0", "revision": "a" * 40},
    })
    record = deploy.request_deploy(settings, "previous", requested_by="ops", running="0.34.1")
    assert (record["version"], record["from_version"], record["from_revision"]) == ("0.34.0", "0.34.1", "b" * 40)
    assert deploy.read_request(settings) == record
    with pytest.raises(DeployRefused) as refused:
        deploy.request_deploy(settings, "0.34.2", requested_by="ops", running="0.34.1")
    assert refused.value.code == "deploy_in_progress"


def _account(repo: Repository, name: str, *, admin: bool) -> dict[str, str]:
    account_id = repo.create_account(name)
    repo.set_site_admin(account_id, admin)
    repo.add_api_key(f"mk_live_{name}", account_id)
    return {"Authorization": f"Bearer mk_live_{name}"}


def test_the_routes_are_for_site_admins_and_serve_no_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path, deploy=True)
    app = create_app(settings)
    client = TestClient(app)
    admin = _account(app.state.repo, "ops", admin=True)
    plain = _account(app.state.repo, "plain", admin=False)

    assert client.get("/api/v1/admin/deploy", headers=plain).status_code == 403
    assert client.post("/api/v1/admin/deploy", json={"version": "0.34.1"}, headers=plain).status_code == 403

    refused = client.post("/api/v1/admin/deploy", json={"version": "0.34.1"}, headers=admin)
    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "not_supervised"

    _beat(settings)
    bad = client.post("/api/v1/admin/deploy", json={"version": "latest"}, headers=admin)
    assert (bad.status_code, bad.json()["detail"]["error"]) == (422, "invalid_version")

    target = "99.0.0"  # above any running version, so only the shape and the floor are read
    asked = client.post("/api/v1/admin/deploy", json={"version": target}, headers=admin)
    assert asked.status_code == 202, asked.text
    assert asked.json()["version"] == target and asked.json()["requested_by"] == "ops"

    status = client.get("/api/v1/admin/deploy", headers=admin)
    assert status.status_code == 200
    body = status.json()
    assert body["enabled"] is True and body["supervised"] is True
    assert body["pending"]["id"] == asked.json()["id"]
    assert str(tmp_path) not in status.text


# ── The supervisor, against a real child ─────────────────────────────────────────────────────────────

CHILD = textwrap.dedent('''
    import http.server, json, sys
    from pathlib import Path
    root, port = Path(sys.argv[1]), int(sys.argv[2])
    version = (root / "installed").read_text().strip()
    if version.startswith("crash"):
        sys.exit(3)
    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"status": "ok", "version": version}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    http.server.HTTPServer(("127.0.0.1", port), Health).serve_forever()
''')


class FakeSource:
    """Installs by writing the version the child will report; `crash...` makes the child exit at once."""

    kind = "git"

    def __init__(self, root: Path, *, refuse: frozenset[str] = frozenset(), unrestorable: bool = False) -> None:
        self.root = root
        self.refuse = refuse
        self.unrestorable = unrestorable
        self.applied: list[str] = []

    def _installed(self) -> str:
        return (self.root / "installed").read_text().strip()

    def current(self) -> Point:
        return Point(self._installed(), f"rev-{self._installed()}")

    def prepare(self, version: str) -> None:
        if version in self.refuse:
            raise StepFailed(f"no tag v{version} on origin")

    def apply(self, version: str) -> None:
        self.applied.append(version)
        (self.root / "installed").write_text(version)

    def restore(self, point: Point) -> None:
        if self.unrestorable:
            raise StepFailed("uv sync exited 1")
        (self.root / "installed").write_text(str(point.version))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def supervisor(tmp_path: Path):
    root = tmp_path / "srv"
    root.mkdir()
    (root / "installed").write_text("0.34.0")
    (root / "child.py").write_text(CHILD)
    port = _free_port()
    made: list[Supervisor] = []

    def build(source: FakeSource | None = None) -> Supervisor:
        sup = Supervisor(
            settings=_settings(tmp_path, deploy=True), root=root, source=source or FakeSource(root),
            child_argv=[sys.executable, str(root / "child.py"), str(root), str(port)],
            health_url=f"http://127.0.0.1:{port}/health", poll_seconds=0.2,
        )
        made.append(sup)
        return sup

    yield build
    for sup in made:
        sup.stop_child()


def _ask(sup: Supervisor, version: str) -> dict:
    _beat(sup.settings)
    return deploy.request_deploy(sup.settings, version, requested_by="ops", running=sup.source.current().version)


def test_a_move_that_comes_up_is_recorded_with_what_ran_before(supervisor) -> None:
    sup = supervisor()
    sup.recover()
    sup.start_child()
    assert sup.wait_healthy("0.34.0") is None

    asked = _ask(sup, "0.34.1")
    sup.step()
    state = deploy.read_state(sup.settings)
    assert state["last"]["id"] == asked["id"]
    assert (state["last"]["outcome"], state["last"]["phase"]) == ("deployed", "done")
    assert state["previous"] == {"version": "0.34.0", "revision": "rev-0.34.0"}
    assert state["current"] == {"version": "0.34.1", "revision": "rev-0.34.1"}
    assert sup.health(sup.health_url)["version"] == "0.34.1"
    assert deploy.read_request(sup.settings) is None

    _ask(sup, "previous")
    sup.step()
    state = deploy.read_state(sup.settings)
    assert state["last"]["outcome"] == "deployed"
    assert sup.health(sup.health_url)["version"] == "0.34.0"
    assert [r["version"] for r in state["history"]] == ["0.34.0", "0.34.1"]


def test_a_move_that_does_not_come_up_is_rolled_back(supervisor) -> None:
    sup = supervisor()
    sup.recover()
    sup.start_child()
    assert sup.wait_healthy("0.34.0") is None
    pid_before = sup.child.pid

    _ask(sup, "0.34.9")
    sup.source.apply = lambda version: (sup.root / "installed").write_text("crash")  # type: ignore[method-assign]
    sup.step()
    last = deploy.read_state(sup.settings)["last"]
    assert last["outcome"] == "rolled_back"
    assert "exited" in last["detail"]
    assert sup.child.pid != pid_before and sup.health(sup.health_url)["version"] == "0.34.0"
    assert deploy.read_state(sup.settings)["current"]["version"] == "0.34.0"


def test_a_refused_prepare_leaves_the_server_running_untouched(supervisor, tmp_path: Path) -> None:
    sup = supervisor(FakeSource(tmp_path / "srv", refuse={"0.34.5"}))
    sup.recover()
    sup.start_child()
    assert sup.wait_healthy("0.34.0") is None
    pid_before = sup.child.pid

    _ask(sup, "0.34.5")
    sup.step()
    last = deploy.read_state(sup.settings)["last"]
    assert (last["outcome"], last["detail"]) == ("refused", "no tag v0.34.5 on origin")
    assert sup.child.pid == pid_before and sup.child_running()


def test_a_rollback_that_fails_too_says_so_and_keeps_trying_to_serve(supervisor, tmp_path: Path) -> None:
    sup = supervisor(FakeSource(tmp_path / "srv", unrestorable=True))
    sup.recover()
    sup.start_child()
    assert sup.wait_healthy("0.34.0") is None

    _ask(sup, "0.34.2")
    sup.source.apply = lambda version: (sup.root / "installed").write_text("crash")  # type: ignore[method-assign]
    sup.step()
    last = deploy.read_state(sup.settings)["last"]
    assert last["outcome"] == "failed"
    assert "restoring 0.34.0 failed too: uv sync exited 1" in last["detail"]


def test_a_supervisor_that_died_mid_move_reports_it_interrupted(supervisor) -> None:
    sup = supervisor()
    deploy.write_json(deploy.deploy_root(sup.settings) / deploy.STATE_FILE, {
        "last": {"id": "x", "version": "0.34.1", "phase": "applying", "outcome": None},
    })
    sup.recover()
    state = deploy.read_state(sup.settings)
    assert state["last"]["outcome"] == "interrupted"
    assert "applying" in state["last"]["detail"]
    assert state["history"][0]["id"] == "x"
    assert state["current"]["version"] == "0.34.0"


def test_a_server_that_exits_on_its_own_is_started_again(supervisor) -> None:
    sup = supervisor()
    sup.start_child()
    assert sup.wait_healthy(None) is None
    sup.child.kill()
    sup.child.wait()
    sup.step()
    assert sup.child_running()
    assert sup.wait_healthy("0.34.0") is None


# ── The sources ──────────────────────────────────────────────────────────────────────────────────────


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _release(work: Path, version: str) -> None:
    (work / "pyproject.toml").write_text(f'[project]\nname = "just-dna-registry"\nversion = "{version}"\n')
    _git(work, "add", "pyproject.toml")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", version)
    _git(work, "tag", f"v{version}")


def test_a_clone_moves_by_release_tag_and_returns_by_commit(tmp_path: Path) -> None:
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "--initial-branch=main", str(origin))
    _git(tmp_path, "init", "-q", "--initial-branch=main", str(work))
    _release(work, "0.34.0")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "HEAD:refs/heads/main", "--tags")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _release(work, "0.34.1")
    _git(work, "push", "-q", "origin", "HEAD:refs/heads/main", "--tags")

    synced: list[list[str]] = []

    def runner(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if argv[:2] == ["uv", "sync"]:
            synced.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)

    source = detect_source(clone, "server")
    assert isinstance(source, GitSource)
    source.runner = runner
    before = source.current()
    assert before.version == "0.34.0"

    with pytest.raises(StepFailed, match="no tag v0.35.0 on origin"):
        source.prepare("0.35.0")
    source.prepare("0.34.1")  # fetched: the tag pushed after the clone is there now
    source.apply("0.34.1")
    assert source.current().version == "0.34.1"
    assert synced == [["uv", "sync", "--inexact", "--extra", "server"]]

    source.restore(before)
    assert source.current() == before

    (clone / "pyproject.toml").write_text("edited by hand\n")
    with pytest.raises(StepFailed, match="uncommitted changes"):
        source.prepare("0.34.1")


def test_a_pypi_project_moves_by_pin(tmp_path: Path) -> None:
    root = tmp_path / "srv"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "registry-box"\nversion = "0"\ndependencies = ["just-dna-registry[server]==0.34.0"]\n'
    )
    (root / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "just-dna-registry"\nversion = "0.34.0"\n'
    )
    ran: list[list[str]] = []

    def runner(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    source = detect_source(root, "server")
    assert isinstance(source, PypiSource)
    source.runner = runner
    source.exists = lambda version: version == "0.34.1"
    assert source.current() == Point("0.34.0")
    with pytest.raises(StepFailed, match="0.34.7 is not on PyPI"):
        source.prepare("0.34.7")
    source.prepare("0.34.1")
    source.apply("0.34.1")
    assert ran == [
        ["uv", "add", "--no-sync", "just-dna-registry[server]==0.34.1"],
        ["uv", "sync", "--inexact"],
    ]


def test_a_folder_that_is_neither_is_not_supervised(tmp_path: Path) -> None:
    assert detect_source(tmp_path, "server") is None
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "just-dna-registry"\nversion = "0.34.0"\n')
    assert detect_source(tmp_path, "server") is None  # the package's own tree, but not a clone
