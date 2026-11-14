"""`GET /upgrade/status` (0.32): which current versions the upgrade sweep has not brought up to date.

Built after two wrong answers on 2026-11-14 to "are the polygon's held modules published?": every listed
version read `needs_upgrade: false`, four of them held by the 0.8 sweep, and a desk question said "12 held"
a week after 8 were published. The first two tests are those two failures. Runs are the real
`maintenance_run` around the real `write_sweep`, in the run root the app's own settings resolve.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sdk_transport import sdk_transport
from typer.testing import CliRunner

from just_dna_registry import client_cli
from just_dna_registry.client import RegistryClient
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.maintenance import RUN_FILE, maintenance_run, run_root, write_sweep
from just_dna_registry.services import held as held_store
from just_dna_registry.sweep_report import PUBLISHED, REFUSED, UNCHANGED, WOULD_UPGRADE, SweepItem, SweepResult
from just_dna_registry.version import installed_compiler

NS, NAME = "just-dna-seq", "coronary"
ROUTE = "/api/v1/upgrade/status"


def _module(seed, version: str = "1.0.0") -> None:
    seed(NS, NAME, version, genes=["APOE"], categories=["cardio"], created_at=f"2026-01-01T00:00:0{version[-1]}Z")


def _stamp(repo: Repository, version: str, stamp: str | None) -> None:
    """The stored manifest as if `stamp` (the compiler's own spelling) had built it."""
    repo.conn.execute(
        "UPDATE versions SET manifest_json = json_set(manifest_json, '$.compilation.compiler_version', ?) "
        "WHERE version = ? AND module_id = (SELECT id FROM modules WHERE namespace = ? AND name = ?)",
        (stamp, version, NS, NAME),
    )
    repo.conn.commit()


def _older_contract() -> str:
    major, minor, _ = installed_compiler().split(".")
    return f"just-dna-compiler {major}.{int(minor) - 1}.0"


def _sweep(settings: Settings, status: str, code: str, *, version: str = "1.0.0", apply: bool = True,
           command: str = "upgrade", drift: int = 0) -> str:
    invocation = f"registry --mode prod {command} {'--apply ' if apply else ''}--online"
    with maintenance_run(settings, command, invocation) as run:
        label = f"{NS}/{NAME}@{version}"
        write_sweep(run, SweepResult(items=[SweepItem(
            label=label, status=status, code=code, head=f"  {label}  {status}  {code}",
            detail=[f"read {settings.db_path}"], drift_to_read=drift,
        )]).to_json())
        return run.id


def _status(client: TestClient, **params: str) -> dict:
    resp = client.get(ROUTE, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _only(body: dict) -> dict:
    (item,) = body["items"]
    assert (item["namespace"], item["name"]) == (NS, NAME)
    return item


def test_an_older_contract_with_no_sweep_on_record_is_behind_never_current(
    client: TestClient, repo: Repository, seed
) -> None:
    """The polygon's four: held by a sweep that kept no record (before 0.28.3), built under 0.7."""
    _module(seed)
    _stamp(repo, "1.0.0", _older_contract())
    body = _status(client)
    item = _only(body)
    assert (item["state"], item["gap"], item["last_sweep"]) == ("behind", "contract", None)
    assert body["counts"] == {"held": 0, "would_upgrade": 0, "behind": 1, "unknown": 0, "current": 0}
    assert (body["swept"], body["sweeps_on_record"], body["sweeps_since"]) == (0, 0, None)
    # The flag that read `false` for exactly these: it is `revalidate`'s, and still says nothing here.
    versions = client.get(f"/api/v1/modules/{NS}/{NAME}/versions").json()["items"]
    assert versions[0]["needs_upgrade"] is False


def test_a_drift_refusal_is_held_and_leaves_no_sentence_id_or_path(
    client: TestClient, repo: Repository, seed, settings: Settings
) -> None:
    """The drift hold is a *refusal* in the record, not status `held`."""
    _module(seed)
    _stamp(repo, "1.0.0", _older_contract())
    run_id = _sweep(settings, REFUSED, "rederive_drift_needs_reading", drift=6)
    body = _status(client)
    item = _only(body)
    assert item["state"] == "held"
    assert item["last_sweep"] == {
        "started": item["last_sweep"]["started"], "applied": True, "status": REFUSED,
        "code": "rederive_drift_needs_reading", "problem_type": "drift to read", "drift_to_read": 6,
    }
    assert item["last_sweep"]["started"]
    assert (body["counts"]["held"], body["swept"], body["sweeps_on_record"]) == (1, 1, 1)
    rendered = json.dumps(body)
    assert rendered.count(NAME) >= 1, "the haystack holds the module, so the absences below mean something"
    for absent in (run_id, "head", "detail", str(settings.db_path), str(run_root(settings))):
        assert absent not in rendered, absent


def test_a_successor_supersedes_the_hold(client: TestClient, repo: Repository, seed, settings: Settings) -> None:
    _module(seed)
    _stamp(repo, "1.0.0", _older_contract())
    _sweep(settings, REFUSED, "rederive_drift_needs_reading")
    _module(seed, "1.0.1")
    _stamp(repo, "1.0.1", f"just-dna-compiler {installed_compiler()}")
    item = _only(_status(client))
    assert (item["version"], item["state"], item["gap"], item["last_sweep"]) == ("1.0.1", "current", "none", None)


def test_the_newest_verdict_on_the_version_wins(client: TestClient, repo: Repository, seed, settings: Settings) -> None:
    _module(seed)
    _stamp(repo, "1.0.0", f"just-dna-compiler {installed_compiler()}")
    _sweep(settings, UNCHANGED, "unchanged")
    _sweep(settings, REFUSED, "enrichment_timeout")
    assert _only(_status(client))["state"] == "held"
    _sweep(settings, UNCHANGED, "unchanged")
    item = _only(_status(client))
    assert (item["state"], item["last_sweep"]["status"]) == ("current", UNCHANGED)
    assert _status(client)["sweeps_on_record"] == 3


def test_a_dry_run_says_would_upgrade_and_that_it_was_a_dry_run(
    client: TestClient, repo: Repository, seed, settings: Settings
) -> None:
    _module(seed)
    _sweep(settings, WOULD_UPGRADE, "contract_gap", apply=False)
    item = _only(_status(client, state="would_upgrade"))
    assert (item["state"], item["last_sweep"]["applied"]) == ("would_upgrade", False)


def test_replays_and_reverted_runs_are_not_the_catalog(
    client: TestClient, repo: Repository, seed, settings: Settings
) -> None:
    """A replay sweeps a scratch copy; a reverted run's changes were undone. Neither describes this catalog."""
    _module(seed)
    _stamp(repo, "1.0.0", f"just-dna-compiler {installed_compiler()}")
    _sweep(settings, REFUSED, "rederive_drift_needs_reading", command="replay-upgrade")
    reverted = _sweep(settings, REFUSED, "rederive_drift_needs_reading")
    record_file = run_root(settings) / reverted / RUN_FILE
    record = json.loads(record_file.read_text())
    record["reverted_by"] = "a-later-run"
    record_file.write_text(json.dumps(record))
    body = _status(client)
    assert (_only(body)["state"], body["sweeps_on_record"], body["swept"]) == ("current", 0, 0)


def test_a_kept_rederivation_is_held_and_says_so(
    client: TestClient, repo: Repository, seed, settings: Settings, tmp_path: Path
) -> None:
    """0.31.1's `--withhold-rederive` keeps the result; the status names it without a sweep record."""
    _module(seed)
    _stamp(repo, "1.0.0", f"just-dna-compiler {installed_compiler()}")
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "module_spec.yaml").write_text("module: {}\n")
    held_store.hold(settings, NS, NAME, "1.0.0", spec, drift={"moved": 1}, drift_to_read=["rs1"],
                    changelog="c", offline=False, run=None)
    item = _only(_status(client))
    assert (item["state"], item["kept"], item["kept_stale"]) == ("held", True, None)


def test_an_unidentifiable_compiler_is_unknown_and_a_published_predecessor_is_ignored(
    client: TestClient, repo: Repository, seed, settings: Settings
) -> None:
    _module(seed)
    _stamp(repo, "1.0.0", "just-dna-compiler unknown")
    # A signature dates it 0.5 or later; without one the pre-0.5 rule rightly says `contract`.
    repo.conn.execute("UPDATE versions SET manifest_json = json_set(manifest_json, '$.content_signature', ?)",
                      ("sha256:" + "0" * 64,))
    repo.conn.commit()
    _sweep(settings, PUBLISHED, "published", version="0.9.0")  # a version that is not the current one
    body = _status(client)
    assert (_only(body)["state"], body["swept"], body["sweeps_on_record"]) == ("unknown", 0, 1)


def test_the_sdk_and_the_cli_print_every_count_and_the_coverage(
    client: TestClient, repo: Repository, seed, settings: Settings, monkeypatch
) -> None:
    _module(seed)
    _stamp(repo, "1.0.0", _older_contract())
    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    report = sdk.upgrade_status()
    assert (report.counts["behind"], report.items[0].state) == (1, "behind")
    monkeypatch.setattr(client_cli, "_client", lambda url, token, **kw: sdk)
    out = CliRunner().invoke(client_cli.app, ["upgrade-status"])
    assert out.exit_code == 0, out.output
    assert "held 0  would_upgrade 0  behind 1  unknown 0  current 0" in out.output
    assert "recorded sweeps: 0; 0 of 1 current versions have a sweep verdict" in out.output
    assert f"behind        {NS}/{NAME}@1.0.0  — no sweep on record; built under" in out.output
