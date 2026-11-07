"""Maintenance runs over REST (0.28.3): site admins read the enricher-facing runs, and no path leaves.

Runs are made by the real `maintenance_run` around the real `write_sweep`, in the run root the app's own
settings resolve, so what is served is what a command on this box leaves behind.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sdk_transport import sdk_transport
from typer.testing import CliRunner

from just_dna_registry.cli import app as cli
from just_dna_registry.client import RegistryClient, RegistryError
from just_dna_registry.config import Settings, get_settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.maintenance import SWEEP_FILE, maintenance_run, run_root, write_sweep
from just_dna_registry.services.runs import PathScrubber
from just_dna_registry.sweep_report import HELD, SweepItem, SweepResult


def _key(repo: Repository, name: str, *, admin: bool) -> dict:
    account_id = repo.create_account(name)
    repo.set_site_admin(account_id, admin)
    repo.add_api_key(f"mk_live_{name}", account_id)
    return {"Authorization": f"Bearer mk_live_{name}"}


def _run(settings: Settings, command: str, *, sweep: bool) -> str:
    """One real run that prints this box's paths into its log and, for a sweep, keeps its result."""
    with maintenance_run(settings, command, f"registry {command} --out {settings.db_path.parent}/x") as run:
        print(f"read {settings.db_path} and {run_root(settings)}/elsewhere")
        if sweep:
            result = SweepResult(items=[SweepItem(
                label="ns/mod@1.0.0", status=HELD, code="needs_online",
                head="  ns/mod@1.0.0  held  needs_online",
                detail=[f"snapshot at {settings.local_storage_dir}/ensembl", "allele A/G at 3/5 of rows"],
            )])
            write_sweep(run, result.to_json())
        return run.id


@pytest.fixture
def admin(repo: Repository) -> dict:
    return _key(repo, "ops", admin=True)


def _forbidden_paths(settings: Settings) -> set[str]:
    return {
        str(p) for p in (settings.db_path, settings.db_path.parent, run_root(settings), settings.local_storage_dir)
    } | {str(Path.home()), str(Path.cwd())}


def test_only_a_site_admin_reads_runs(client: TestClient, repo: Repository, settings: Settings, admin) -> None:
    run_id = _run(settings, "upgrade", sweep=True)
    stranger = _key(repo, "stranger", admin=False)
    for path in ("/api/v1/admin/runs", f"/api/v1/admin/runs/{run_id}", f"/api/v1/admin/runs/{run_id}/log"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=stranger).status_code == 403, path
        assert client.get(path, headers=admin).status_code == 200, path


def test_the_sweep_is_served_structured_and_scrubbed(client: TestClient, settings: Settings, admin) -> None:
    run_id = _run(settings, "upgrade", sweep=True)
    body = client.get(f"/api/v1/admin/runs/{run_id}", headers=admin).json()
    assert body["run"]["command"] == "upgrade" and body["run"]["has_sweep"] and body["run"]["has_log"]
    assert body["sweep"]["counts"] == {HELD: 1}
    (item,) = body["sweep"]["items"]
    assert (item["status"], item["code"]) == (HELD, "needs_online")
    assert item["detail"] == ["snapshot at <storage>/ensembl", "allele A/G at 3/5 of rows"]
    assert body["run"]["invocation"] == "registry upgrade --out <data>/x"
    rendered = json.dumps(body)
    assert not {p for p in _forbidden_paths(settings) if p in rendered}, rendered


def test_the_log_is_served_scrubbed_and_tailed(client: TestClient, settings: Settings, admin) -> None:
    run_id = _run(settings, "upgrade", sweep=False)
    text = client.get(f"/api/v1/admin/runs/{run_id}/log", headers=admin).text
    raw = (run_root(settings) / run_id / "run.log").read_text()
    # The haystack is the log: the operator's copy still holds the paths the served one must not.
    assert str(settings.db_path) in raw
    assert "read <data>/registry.db and <runs>/elsewhere" in text, text
    assert not {p for p in _forbidden_paths(settings) if p in text}, text
    tail = client.get(f"/api/v1/admin/runs/{run_id}/log?tail=1", headers=admin).text
    assert tail.count("\n") == 1 and tail == text.splitlines(keepends=True)[-1]


def test_a_run_of_another_command_is_not_served(client: TestClient, settings: Settings, admin) -> None:
    served = _run(settings, "upgrade", sweep=False)
    hidden = _run(settings, "merge-accounts", sweep=False)
    listing = client.get("/api/v1/admin/runs", headers=admin).json()
    assert [item["id"] for item in listing["items"]] == [served] and listing["total"] == 1
    assert client.get(f"/api/v1/admin/runs/{hidden}", headers=admin).status_code == 404
    assert client.get(f"/api/v1/admin/runs/{hidden}/log", headers=admin).status_code == 404
    assert client.get("/api/v1/admin/runs?command=merge-accounts", headers=admin).status_code == 422


@pytest.mark.parametrize("run_id", ["..", "../registry.db", "%2e%2e", "nope"])
def test_an_id_is_looked_up_never_joined(client: TestClient, settings: Settings, admin, run_id: str) -> None:
    _run(settings, "upgrade", sweep=False)
    assert client.get(f"/api/v1/admin/runs/{run_id}/log", headers=admin).status_code == 404


def test_newest_first_and_paged(client: TestClient, settings: Settings, admin) -> None:
    ids = [_run(settings, command, sweep=False) for command in ("warm-caches", "upgrade", "revalidate")]
    page = client.get("/api/v1/admin/runs?per_page=2", headers=admin).json()
    assert [item["id"] for item in page["items"]] == ids[::-1][:2] and page["total"] == 3
    only = client.get("/api/v1/admin/runs?command=upgrade", headers=admin).json()
    assert [item["id"] for item in only["items"]] == [ids[1]]


def test_the_client_wraps_all_three(client: TestClient, settings: Settings, admin) -> None:
    run_id = _run(settings, "replay-upgrade", sweep=True)
    sdk = RegistryClient("http://testserver", token=admin["Authorization"].split()[1],
                         transport=sdk_transport(client))
    assert sdk.runs(command="replay-upgrade")["items"][0]["id"] == run_id
    assert sdk.run(run_id)["sweep"]["items"][0]["code"] == "needs_online"
    assert "<runs>/elsewhere" in sdk.run_log(run_id, tail=5)
    with pytest.raises(RegistryError) as refused:
        sdk.run_log("nope")
    assert refused.value.status_code == 404


def test_a_leftover_path_is_masked_and_an_allele_is_not(settings: Settings) -> None:
    scrub = PathScrubber(settings)
    assert scrub("cache at /opt/elsewhere/ensembl/chr1.parquet") == "cache at <path>"
    assert scrub("A/G 3/5 https://rest.ensembl.org/variation/human and /api/v1/modules") == (
        "A/G 3/5 https://rest.ensembl.org/variation/human and /api/v1/modules"
    )


def test_a_real_upgrade_dry_run_keeps_its_sweep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    try:
        assert CliRunner().invoke(cli, ["init-db"]).exit_code == 0
        result = CliRunner().invoke(cli, ["upgrade", "--dry-run"])
        assert result.exit_code == 0, result.output
        sweeps = list((tmp_path / "runs").glob(f"*-upgrade/{SWEEP_FILE}"))
    finally:
        get_settings.cache_clear()
    assert len(sweeps) == 1, list((tmp_path / "runs").iterdir())
    assert json.loads(sweeps[0].read_text())["items"] == []
