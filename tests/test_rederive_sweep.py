"""M12: `registry upgrade` re-derives a resolution table written before format 0.8, instead of carrying it.

Upstream's upgrade order (INTEGRATION_0_8 § 2 step 5): after the Ensembl snapshot switch an ordinary
enrich fills gaps and leaves a 0.7 row as it was, and a table holding both releases' placements for one
rsID refuses under `strict` (`rsid_placements_disagree`). So the sweep re-derives, online where a module
carries an indel (offline 0.8 cannot left-align one, RM385), and holds drift a person has to read, because
the successor is immutable.

The network is stubbed by never letting a test go online; the report is never stubbed. The enrich runs
for real, offline against this box's snapshot, and the drift a hold test needs is upstream's own
`SubjectDrift`, whose constructor refuses a case that contradicts its `respelled`.
"""

import csv
import dataclasses
import io
import json
import logging
import shutil
import threading
from pathlib import Path

import just_dna_enricher.enrich as enricher
import pytest
from fastapi.testclient import TestClient
from just_dna_enricher.enrich import SubjectDrift
from just_dna_enricher.enrich.rederive_words import DRIFT_CASES
from just_dna_format.manifest import ModuleManifest
from just_dna_format.resolution import ResolutionRow
from typer.testing import CliRunner

from just_dna_registry import cli
from just_dna_registry.config import Settings, get_settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect
from just_dna_registry.maintenance import SNAPSHOT_FILE, db_digest
from just_dna_registry.replay import SweepLines
from just_dna_registry.services import enrich as enrich_service
from just_dna_registry.services import held
from just_dna_registry.services.enrich import QUIET_DRIFT, snapshot_not_current
from just_dna_registry.services.publish import PublishError
from just_dna_registry.services.upgrade import (
    UpgradeHeld,
    needs_online_rederive,
    prepare_version_upgrade,
    resolution_needs_rederive,
    upgrade_version,
)
from just_dna_registry.specfiles import RESOLUTION_CSV
from just_dna_registry.storage.base import version_key
from just_dna_registry.sweep_report import HELD_SNAPSHOT, HELD_STALE

_NS, _NAME = "just-dna-seq", "coronary"
_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  title: Coronary
  description: d
  report_title: R
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
    "rs1801133,1,11796321,G,A,A/G,0.4,protective,het,MTHFR,folate\n"
)
_STUDIES = (
    "rsid,pmid,population,p_value,conclusion,study_design\n"
    "rs4244285,29165669,T,0.05,E,U\nrs1801133,29165669,T,0.05,E,U\n"
)


def _publish(client: TestClient, key: str, name: str = _NAME) -> ModuleManifest:
    resp = client.post(
        f"/api/v1/modules/{_NS}/{name}/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", ("module_spec.yaml", _YAML.replace("coronary", name).encode(), "text/yaml")),
            # A second module needs data of its own, or the publish is `409 duplicate_content`.
            ("files", ("variants.csv", (_VARIANTS if name == _NAME else _VARIANTS.replace("-0.8", "-0.7")).encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201, resp.text
    return ModuleManifest.model_validate(resp.json())


def _changelog(app, version: str, name: str = _NAME) -> str:
    changelog = app.state.repo.get_version_changelog(_NS, name, version)
    assert changelog is not None
    return changelog


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _as_0_7_table(app, name: str = _NAME) -> None:
    """Rewrite a stored `resolution.csv` the way a 0.7 run left it: no `source_release` on any row."""
    key = version_key(_NS, name, "1.0.0")
    rows = _rows(app.state.storage.read_file(key, RESOLUTION_CSV).decode())
    assert rows, "the fixture must have resolved something, or there is nothing to re-derive"
    assert any(row.get("source_release") for row in rows), "a 0.8 run must have stamped a release"
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows({**row, "source_release": ""} for row in rows)
    app.state.storage.store_module(key, {RESOLUTION_CSV: out.getvalue().encode()})


@pytest.fixture
def enrich_calls(monkeypatch):
    """Every `enrich()` call's keywords, with the real enrich still run (offline, against the snapshot)."""
    calls: list[dict] = []
    real = enricher.enrich

    def spy(spec_dir, **kwargs):
        calls.append(kwargs)
        return real(spec_dir, **kwargs)

    monkeypatch.setattr(enricher, "enrich", spy)
    return calls


def _inject_drift(monkeypatch, *drift: SubjectDrift) -> None:
    real = enricher.enrich

    def with_drift(spec_dir, **kwargs):
        result = real(spec_dir, **kwargs)
        return dataclasses.replace(result, rederived=list(drift)) if kwargs.get("rederive") else result

    monkeypatch.setattr(enricher, "enrich", with_drift)


# ── The trigger and the indel test, read off the tables ──────────────────────────────────────────────


def test_the_trigger_reads_the_column_upstream_writes() -> None:
    # Guards the column name: an absence test over a renamed column would call every table current.
    assert "source_release" in ResolutionRow.model_fields
    header = "variant_key,chrom,start,ref,alts,source_release\n"
    assert resolution_needs_rederive(header + "rs1,1,10,G,A,\n")
    assert resolution_needs_rederive(header + "rs1,1,10,G,A,ens-116\nrs2,1,11,G,A,\n")
    assert not resolution_needs_rederive(header + "rs1,1,10,G,A,ens-116\n")
    # A 0.7 table has no such column at all.
    assert resolution_needs_rederive("variant_key,chrom,start,ref,alts\nrs1,1,10,G,A\n")


def test_only_an_allele_offline_cannot_place_asks_for_the_network() -> None:
    res = "variant_key,chrom,start,ref,alts\n"
    var = "rsid,chrom,start,ref,alts,genotype\n"
    snv = {RESOLUTION_CSV: (res + 'rs1,1,10,G,A\nrs2,1,20,C,"A,T"\n').encode()}
    assert not needs_online_rederive(snv)
    assert needs_online_rederive({RESOLUTION_CSV: (res + "rs1,1,10,TA,T\n").encode()})
    assert needs_online_rederive({RESOLUTION_CSV: (res + 'rs1,1,10,G,"A,GA"\n').encode()})
    # An rsID-only authored row has nothing resolved yet: its genotype is the only allele on record.
    assert needs_online_rederive({"variants.csv": (var + "rs1,,,,,TA/T\n").encode()})
    assert not needs_online_rederive({"variants.csv": (var + "rs1,,,,,A/G\n").encode()})


def test_an_arm_upstream_adds_is_listed_until_somebody_decides_it_is_quiet() -> None:
    # Floored: an emptied foreign set would make "every quiet arm is upstream's" vacuous.
    assert len(DRIFT_CASES) >= 7
    assert QUIET_DRIFT < DRIFT_CASES
    assert {"moved", "lost_allele", "renamed", "undecided"} <= DRIFT_CASES - QUIET_DRIFT


# ── The publish path ─────────────────────────────────────────────────────────────────────────────────


def test_an_ordinary_publish_never_re_derives(
    client: TestClient, api_key: str, enrich_calls: list[dict]
) -> None:
    _publish(client, api_key)
    assert enrich_calls and all(call["rederive"] is False for call in enrich_calls)


def test_the_sweep_re_derives_a_0_7_table_and_says_so_in_the_changelog(
    client: TestClient, api_key: str, app, settings: Settings, enrich_calls: list[dict]
) -> None:
    manifest = _publish(client, api_key)
    _as_0_7_table(app)
    prep = prepare_version_upgrade(app.state.storage, _NS, _NAME, "1.0.0", manifest)
    assert prep is not None and prep.rederive and not prep.needs_online
    assert prep.rederive_subjects == 2
    enrich_calls.clear()

    result = upgrade_version(
        repo=app.state.repo, storage=app.state.storage, settings=settings,
        namespace=_NS, name=_NAME, version="1.0.0", manifest=manifest,
    )

    assert result is not None
    assert [call["rederive"] for call in enrich_calls] == [True]
    assert enrich_calls[0]["offline"] is True
    assert "Resolutions re-derived (offline" in _changelog(app, result[0])
    # The successor's table is a 0.8 run's again, so the next sweep carries it.
    stored = app.state.storage.read_file(version_key(_NS, _NAME, "1.0.1"), RESOLUTION_CSV).decode()
    assert not resolution_needs_rederive(stored)


def test_a_table_already_on_0_8_is_carried_as_before(
    client: TestClient, api_key: str, app, settings: Settings, enrich_calls: list[dict]
) -> None:
    manifest = _publish(client, api_key)
    prep = prepare_version_upgrade(app.state.storage, _NS, _NAME, "1.0.0", manifest)
    assert prep is not None and not prep.rederive
    enrich_calls.clear()
    result = upgrade_version(
        repo=app.state.repo, storage=app.state.storage, settings=settings,
        namespace=_NS, name=_NAME, version="1.0.0", manifest=manifest,
    )
    assert result is not None
    assert [call["rederive"] for call in enrich_calls] == [False]
    assert "re-derived" not in _changelog(app, result[0])


def test_drift_worth_reading_publishes_in_the_one_run_and_is_listed(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, enrich_calls: list[dict]
) -> None:
    """0.31.1: a re-derivation publishes what it answered and reports the drift; it never holds.

    Through 0.31.0 a `moved` subject refused the publish until `--accept-drift`, after the paced
    re-derivation had run, so accepting asked every source a second time.
    """
    manifest = _publish(client, api_key)
    _as_0_7_table(app)
    moved = SubjectDrift(
        variant_key="rs4244285", before="10:94781859 G>A", after="10:94781860 G>A",
        respelled=False, case="moved",
    )
    _inject_drift(monkeypatch, moved)
    enrich_calls.clear()
    drift: list[str] = []
    result = upgrade_version(
        repo=app.state.repo, storage=app.state.storage, settings=settings,
        namespace=_NS, name=_NAME, version="1.0.0", manifest=manifest, drift_out=drift,
    )
    assert result is not None and result[0] == "1.0.1"
    assert app.state.repo.version_exists(_NS, _NAME, "1.0.1")
    assert [call["rederive"] for call in enrich_calls] == [True]  # one re-derivation, not two
    assert drift == [str(moved)]
    assert "1 moved" in _changelog(app, result[0])


def test_quiet_drift_publishes_and_is_recorded(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    manifest = _publish(client, api_key)
    _as_0_7_table(app)
    _inject_drift(
        monkeypatch,
        SubjectDrift(variant_key="rs4244285", before="a", after="b", respelled=True, case="respelled"),
    )
    result = upgrade_version(
        repo=app.state.repo, storage=app.state.storage, settings=settings,
        namespace=_NS, name=_NAME, version="1.0.0", manifest=manifest,
    )
    assert result is not None
    assert "1 respelled" in _changelog(app, result[0])
    assert "accepted" not in _changelog(app, result[0])


def test_an_indel_module_is_held_offline_and_goes_online_only_when_allowed(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    manifest = _publish(client, api_key)
    _as_0_7_table(app)
    prep = prepare_version_upgrade(app.state.storage, _NS, _NAME, "1.0.0", manifest)
    assert prep is not None and prep.rederive
    # The indel test itself is `needs_online_rederive`'s, above; here the plan carries its answer, so the
    # stored table stays one the validator accepts.
    prep = prep.model_copy(update={"needs_online": True})
    args = {
        "repo": app.state.repo, "storage": app.state.storage, "settings": settings,
        "namespace": _NS, "name": _NAME, "version": "1.0.0", "manifest": manifest, "prepared": prep,
    }

    with pytest.raises(UpgradeHeld, match="--online"):
        upgrade_version(**args)

    # Online: the one publish runs with egress allowed. Stopped at the enrich, so nothing egresses here.
    seen: list[dict] = []

    class Stop(Exception):
        pass

    def record(spec_dir, **kwargs):
        # Whether the unshared-egress lock is held while the enrich runs. The dbSNP witness no longer
        # takes it (RM418: its `EutilsClient` paces on the process's NCBI gate); only the dataset probes do.
        free = enrich_service._UNSHARED_EGRESS.acquire(blocking=False)
        if free:
            enrich_service._UNSHARED_EGRESS.release()
        kwargs["serialized"] = not free
        seen.append(kwargs)
        raise Stop

    monkeypatch.setattr(enricher, "enrich", record)
    with pytest.raises(Stop):
        upgrade_version(**args, online=True)
    assert seen[0]["offline"] is False and seen[0]["rederive"] is True
    # RM398: online, the dbSNP witness is asked; since RM418 that does not serialize the sweep.
    assert seen[0]["verify_rsids"] is True and seen[0]["serialized"] is False
    # The process's own settings are untouched: only that one publish went online.
    assert settings.enrich_offline is True and settings.enrich_verify_rsids is False


# ── The snapshot check ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("record", "refused"),
    [
        ('{"repo": "datasets/just-dna-seq/ensembl_variations_split/data", "files": []}', None),
        ('{"repo": "datasets/just-dna-seq/ensembl_variations/data", "files": []}', "the old release"),
        (
            '{"repo": "datasets/just-dna-seq/ensembl_variations_split/data", '
            '"replacing": "datasets/just-dna-seq/ensembl_variations/data", "files": []}',
            "the old release",
        ),
        ('{"files": []}', "records no repo"),
        (None, "records no repo"),
    ],
)
def test_the_sweep_refuses_to_re_derive_against_anything_but_the_new_snapshot(
    settings: Settings, tmp_path: Path, monkeypatch, record: str | None, refused: str | None
) -> None:
    cache = tmp_path / "ensembl_variations"
    cache.mkdir()
    if record is not None:
        (cache / "pull-record.json").write_text(record)
    monkeypatch.setattr(enrich_service, "available_references", lambda _s: {"ensembl": cache})
    answer = snapshot_not_current(settings)
    if refused is None:
        assert answer is None
    else:
        assert answer is not None and refused in answer
        assert "warm-caches --apply" in answer


def test_no_snapshot_at_all_refuses(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr(enrich_service, "available_references", lambda _s: {"ensembl": None})
    answer = snapshot_not_current(settings)
    assert answer is not None and "no Ensembl snapshot" in answer


# ── The sweep ────────────────────────────────────────────────────────────────────────────────────────


def _sweep(settings: Settings, monkeypatch, *args: str, exit_code: int = 0) -> str:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(settings.local_storage_dir))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["upgrade", *args])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == exit_code, result.output
    return result.output


def _run_log(tmp_path: Path) -> str:
    (run,) = sorted((tmp_path / "runs").glob("*-upgrade"))
    return (run / "run.log").read_text()


def test_the_dry_run_states_how_each_module_re_derives(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    _publish(client, api_key)
    _as_0_7_table(app)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    out = _sweep(settings, monkeypatch, "--dry-run")
    assert "re-derive: snapshot only" in out
    # One line for the module, its reasons as codes; the sentence is the detail (log, or --verbose).
    # 0.30.1: the reasons follow the route code, each with its row count.
    assert f"⇧ {_NS}/{_NAME}@1.0.0: would upgrade [" in out and "rederive_snapshot, no_source_release:" in out
    assert "re-derive 2 recorded subject(s) from the snapshot" not in out
    assert "1 version(s) would upgrade" in out
    verbose = _sweep(settings, monkeypatch, "--dry-run", "--verbose")
    assert "    " in verbose and "re-derive 2 recorded subject(s) from the snapshot" in verbose


def test_a_stale_snapshot_holds_every_re_derivation_and_publishes_none(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    _publish(client, api_key)
    _as_0_7_table(app)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: "pulled from the old release")
    out = _sweep(settings, monkeypatch, "--apply")
    assert "re-derive refused for every module that needs it" in out
    assert f"… held {_NS}/{_NAME}@1.0.0: {HELD_SNAPSHOT}\n" in out
    assert "0 version(s) upgraded" in out
    assert f"by type: snapshot 1 (held {HELD_SNAPSHOT} 1)" in out
    assert not app.state.repo.version_exists(_NS, _NAME, "1.0.1")


def test_one_refusal_does_not_end_the_sweep(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    _publish(client, api_key, name="coronary")
    _publish(client, api_key, name="coronary_two")
    attempted: list[str] = []

    def refuse(**kwargs):
        attempted.append(kwargs["name"])
        raise PublishError("compile_failed", errors=["rs1: strict refused the row"])

    monkeypatch.setattr(cli, "upgrade_version", refuse)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    out = _sweep(settings, monkeypatch, "--apply")
    assert sorted(attempted) == ["coronary", "coronary_two"]
    assert out.count("✗ just-dna-seq/") == 2
    assert "2 refused" in out
    assert "by type: validation 2 (refused compile_failed 2)" in out


def test_the_terminal_gets_one_line_per_module_and_the_log_gets_the_rest(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    """0.28.2: per-module status and counts by type on the terminal; drift, digests and warnings in run.log.

    A refusal's drift list and an upstream warning logged mid-module were printed between the module
    lines through 0.28.1. Now each is one line, the warning is counted by its logger, and both are in
    the run's log whole.
    """
    _publish(client, api_key, name="coronary")
    _publish(client, api_key, name="coronary_two")
    real = cli.upgrade_version

    def upgrade_version(**kwargs):
        logging.getLogger("just_dna_enricher.enrich").warning("Re-derivation: 1 of 2 re-asked subject(s) moved")
        # RM403's retry line (0.8.1): its own logger, counted as network, not as the enricher's.
        logging.getLogger("just_dna_enricher.net").warning("_rest_rsid(rs1): attempt 1 of 3 failed; retrying")
        if kwargs["name"] == "coronary_two":
            raise PublishError("compile_failed", errors=["rs1 moved: the source names a different event"])
        return real(**kwargs)

    monkeypatch.setattr(cli, "upgrade_version", upgrade_version)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(tmp_path / "runs"))
    out = _sweep(settings, monkeypatch, "--apply", "--force")

    module_lines = [line for line in out.splitlines() if f" {_NS}/" in line]
    assert len(module_lines) == 2, out
    assert any(line.startswith(f"✓ {_NS}/coronary@1.0.0 → 1.0.1 [") for line in module_lines), out
    assert f"✗ {_NS}/coronary_two@1.0.0: compile_failed" in module_lines
    assert "rs1 moved" not in out and "digest sha256:" not in out
    assert "Re-derivation: 1 of 2" not in out
    assert "logged warnings: enrichment 2 (just_dna_enricher.enrich 2); network 2 (just_dna_enricher.net 2)" in out
    assert "1 version(s) upgraded and re-published, 1 refused (above)" in out

    body = _run_log(tmp_path)
    assert [line for line in out.splitlines() if line.strip() and line not in body] == []
    assert "    rs1 moved: the source names a different event" in body
    assert "    digest sha256:" in body
    assert body.count("Re-derivation: 1 of 2 re-asked subject(s) moved") == 2


def test_an_unexpected_failure_is_one_module_and_the_sweep_goes_on(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    _publish(client, api_key, name="coronary")
    _publish(client, api_key, name="coronary_two")
    attempted: list[str] = []

    def explode(**kwargs):
        attempted.append(kwargs["name"])
        raise TimeoutError("the snapshot volume stopped answering")

    monkeypatch.setattr(cli, "upgrade_version", explode)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(tmp_path / "runs"))
    out = _sweep(settings, monkeypatch, "--apply", "--force", exit_code=1)
    assert sorted(attempted) == ["coronary", "coronary_two"]
    assert out.count(": failed TimeoutError") == 2
    assert "2 failed" in out and "by type: timeout 2 (failed TimeoutError 2)" in out
    body = _run_log(tmp_path)
    assert "Traceback" in body and "the snapshot volume stopped answering" in body


def test_the_sweep_writes_its_own_log(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    """Everything the sweep printed is in its run's log, the held module included, without colour codes.

    Through 0.28.0 the sweep wrote only to the terminal, so the list of held modules (the output the
    operator acts on next) was as durable as a scroll-back buffer. A sweep that published nothing
    changed nothing, so its run keeps the log and drops the snapshot.
    """
    _publish(client, api_key)
    _as_0_7_table(app)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: "pulled from the old release")
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(tmp_path / "runs"))
    out = _sweep(settings, monkeypatch, "--apply")

    runs = sorted((tmp_path / "runs").glob("*-upgrade"))
    assert len(runs) == 1, runs
    body = (runs[0] / "run.log").read_text()
    printed = [line for line in out.splitlines() if line.strip()]
    assert len(printed) >= 4, out
    assert [line for line in printed if line not in body] == []
    assert f"… held {_NS}/{_NAME}@1.0.0: {HELD_SNAPSHOT}\n    pulled from the old release" in body
    assert "\x1b[" not in body
    assert body.splitlines()[0] == "# registry --mode prod upgrade --apply"
    assert body.rstrip().splitlines()[-1].startswith("# ok") and "nothing changed" in body
    assert not (runs[0] / SNAPSHOT_FILE).exists()
    assert json.loads((runs[0] / "run.json").read_text())["changed"] is False


_JOB_MODULES = {"coronary": "-0.8", "coronary_two": "-0.7", "coronary_three": "-0.6", "coronary_four": "-0.5"}


def _successors(db: Path, storage: Path) -> dict[str, tuple]:
    """Each module's PATCH as a sweep left it: its version, content identity, changelog and stored files.

    Not the digest: an enrich stamps `fetched_at` into `sources.csv`, so two compiles of one spec name
    different bytes whenever they straddle a second (see CLAUDE.md, *Manifest & integrity*)."""
    conn = connect(db)
    try:
        repo = Repository(conn)
        out = {}
        for name in _JOB_MODULES:
            row = repo.get_module_row(_NS, name)
            version = row["latest_version"]
            manifest = ModuleManifest.model_validate_json(
                (storage / version_key(_NS, name, version) / "manifest.json").read_text()
            )
            files = sorted(
                p.relative_to(storage / version_key(_NS, name, version)).as_posix()
                for p in (storage / version_key(_NS, name, version)).rglob("*") if p.is_file()
            )
            out[name] = (version, manifest.content_signature, repo.get_version_changelog(_NS, name, version), files)
        return out
    finally:
        conn.close()


def test_jobs_publish_what_one_worker_publishes_and_revert_to_the_byte(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    """`upgrade --apply --jobs 3` over four modules leaves the catalog `--jobs 1` leaves, and reverts.

    Two copies of one catalog, one per worker count: every module gets the same PATCH with the same
    content signature, changelog and stored files, and each run's journal names exactly the files it
    added. The parallel run is then reverted, and its catalog and storage read back to the byte. The
    first two re-publishes meet at a barrier, so the parallel run is shown to have overlapped rather
    than assumed to.
    """
    for name, weight in _JOB_MODULES.items():
        resp = client.post(
            f"/api/v1/modules/{_NS}/{name}/versions",
            data={"version": "1.0.0"},
            files=[
                ("files", ("module_spec.yaml", _YAML.replace("coronary", name).encode(), "text/yaml")),
                ("files", ("variants.csv", _VARIANTS.replace("-0.8", weight).encode(), "text/csv")),
                ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
            ],
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 201, resp.text
        _as_0_7_table(app, name=name)
    app.state.repo.conn.commit()
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)

    boxes = {}
    for jobs in (1, 3):
        box = tmp_path / f"jobs{jobs}"
        box.mkdir()
        shutil.copyfile(settings.db_path, box / "registry.db")
        shutil.copytree(settings.local_storage_dir, box / "artifacts")
        boxes[jobs] = box

    real = cli.upgrade_version
    meet = threading.Barrier(2, timeout=60)
    entered: list[str] = []

    def overlapping(**kwargs):
        entered.append(kwargs["name"])
        if len(entered) <= 2:
            meet.wait()  # both of the first two are inside at once, or this raises
        return real(**kwargs)

    outputs, journals = {}, {}
    for jobs, box in boxes.items():
        monkeypatch.setattr(cli, "upgrade_version", overlapping if jobs > 1 else real)
        monkeypatch.setenv("REGISTRY_DB_PATH", str(box / "registry.db"))
        monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(box / "artifacts"))
        monkeypatch.setenv("REGISTRY_RUN_DIR", str(box / "runs"))
        get_settings.cache_clear()
        try:
            result = CliRunner().invoke(cli.app, ["upgrade", "--apply", "--jobs", str(jobs)])
        finally:
            get_settings.cache_clear()
        assert result.exit_code == 0, result.output
        outputs[jobs] = result.output
        (run,) = (box / "runs").glob("*-upgrade")
        journals[jobs] = run
    assert sorted(entered) == sorted(_JOB_MODULES)

    for jobs, out in outputs.items():
        assert f"{len(_JOB_MODULES)} version(s) upgraded and re-published" in out, out
        # One whole line per module on the terminal, however many workers wrote them.
        published = SweepLines.parse(out).published
        assert set(published) == {f"{_NS}/{name}@1.0.0" for name in _JOB_MODULES}, out
        assert all(
            len(block) == 1 and block[0].startswith(f"✓ {label} → 1.0.1 [") for label, block in published.items()
        ), out
        # And each module's detail is in the run's log as one block: its digest line straight under its head.
        log = (journals[jobs] / "run.log").read_text().splitlines()
        for label in published:
            at = [i for i, line in enumerate(log) if f"✓ {label} → 1.0.1 [" in line and " | " in line]
            assert len(at) == 1, (label, log)
            block = log[at[0] + 1:at[0] + 3]
            assert any(line.startswith("    digest sha256:") for line in block), (label, block)

    one, many = (_successors(boxes[j] / "registry.db", boxes[j] / "artifacts") for j in (1, 3))
    assert {name: s[0] for name, s in one.items()} == dict.fromkeys(_JOB_MODULES, "1.0.1")
    assert many == one

    for run in journals.values():
        journal = [json.loads(line) for line in (run / "journal.jsonl").read_text().splitlines()]
        assert {e["op"] for e in journal} == {"add"}
        assert {(e["key"], e["name"]) for e in journal} == {
            (version_key(_NS, name, "1.0.1"), file) for name, (_, _, _, files) in one.items() for file in files
        }

    # Revert the parallel run and read back the catalog and the storage tree it started from.
    box = boxes[3]
    seed_db, seed_tree = db_digest(settings.db_path), _tree_of(settings.local_storage_dir)
    monkeypatch.setenv("REGISTRY_DB_PATH", str(box / "registry.db"))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(box / "artifacts"))
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(box / "runs"))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["revert-run", journals[3].name, "--yes"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert db_digest(box / "registry.db") == seed_db
    assert _tree_of(box / "artifacts") == seed_tree


def _tree_of(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_sweep_that_publishes_kept_the_catalog_as_it_was_before(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    """The run's snapshot is the catalog before the first PATCH, and its journal names the successor's files."""
    _publish(client, api_key)
    _as_0_7_table(app)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(tmp_path / "runs"))
    before = db_digest(settings.db_path)
    _sweep(settings, monkeypatch, "--apply")

    (run,) = sorted((tmp_path / "runs").glob("*-upgrade"))
    record = json.loads((run / "run.json").read_text())
    assert record["changed"] is True and record["db_before"] == before
    assert db_digest(run / SNAPSHOT_FILE) == before != db_digest(settings.db_path)
    journal = [json.loads(line) for line in (run / "journal.jsonl").read_text().splitlines()]
    assert journal and {e["key"] for e in journal} == {f"{_NS}/{_NAME}/1.0.1"}
    assert {e["op"] for e in journal} == {"add"}


# ── 0.30.1: the discriminator, one arm at a time ─────────────────────────────────────────────────────

from just_dna_registry.services.upgrade import (  # noqa: E402 - grouped with the tests that use them
    REDERIVE_CANNOT_SAY,
    REDERIVE_DECLARED_CORRECTION,
    REDERIVE_NO_SOURCE_RELEASE,
    REDERIVE_OLDER_SNAPSHOT,
    rederive_reasons,
)

_HEAD = "variant_key,rsid,chrom,start,ref,alts,source,authority,source_release\n"
_ENS = "ensembl-variation-2026_07_13-vep116.0"
_INSTALLED = {"ensembl": _ENS, "clinvar": "clinvar_2026-11-01"}


def test_a_current_table_has_no_reason_and_an_authored_row_never_is_one() -> None:
    """Authored rows name no release by construction; counting them would re-derive a module forever."""
    table = _HEAD + f"rs1,rs1,1,10,G,A,cache,ensembl,{_ENS}\nrs9,rs9,1,90,C,T,authored,,\n"
    assert rederive_reasons(table, None, _INSTALLED) == {}


def test_a_pre_08_row_names_no_release() -> None:
    table = _HEAD + "rs1,rs1,1,10,G,A,cache,ensembl,\nrs2,rs2,1,11,G,A,cache,ensembl,\n"
    assert rederive_reasons(table, None, _INSTALLED) == {REDERIVE_NO_SOURCE_RELEASE: 2}
    # A 0.7 table has no such column at all.
    assert rederive_reasons("variant_key,chrom,start,ref,alts\nrs1,1,10,G,A\n", None, _INSTALLED) == {
        REDERIVE_NO_SOURCE_RELEASE: 1
    }


def test_a_row_from_an_older_snapshot_is_the_half_0_28_did_not_see() -> None:
    """The case a plain dry run before this patch called current: every row names a release, an older one."""
    table = _HEAD + "rs1,rs1,1,10,G,A,cache,ensembl,ensembl-variation-2025_01_01-vep113.0\n"
    assert not resolution_needs_rederive(table)
    assert rederive_reasons(table, None, _INSTALLED) == {REDERIVE_OLDER_SNAPSHOT: 1}


def test_an_unreadable_installed_release_is_cannot_say_never_current() -> None:
    table = _HEAD + f"rs1,rs1,1,10,G,A,cache,ensembl,{_ENS}\n"
    assert rederive_reasons(table, None, {"ensembl": None}) == {REDERIVE_CANNOT_SAY: 1}


def test_rm438_a_backfilled_rsid_that_cannot_hold_the_authored_genotype() -> None:
    """S151's shape: a coordinate-keyed row back-filled with an rsID whose alleles cannot be the row's genotype."""
    key = "22:42130692:G:A"
    table = _HEAD + f"{key},rs1065852,22,42130692,G,GTTTTTTTTTTTTTTTT,cache,ensembl,{_ENS}\n"
    variants = "variant_key,chrom,start,ref,genotype\n" + f"{key},22,42130692,G,A/G\n"
    assert rederive_reasons(table, variants, _INSTALLED) == {REDERIVE_DECLARED_CORRECTION: 1}
    hosting = _HEAD + f"{key},rs1065852,22,42130692,G,A,cache,ensembl,{_ENS}\n"
    assert rederive_reasons(hosting, variants, _INSTALLED) == {}


def test_a_table_the_installed_enricher_wrote_has_converged() -> None:
    """A fresh 0.8.5 publish leaves `source_release` blank on rows it carries (measured 2026-11-13); acting on
    that would re-derive the module every sweep. The reasons act only for a table an older enricher wrote."""
    from just_dna_registry.services.upgrade import rederive_converged, table_written_by

    assert table_written_by(b'{"producer": "just-dna-enricher 0.7.0"}') == "0.7.0"
    assert table_written_by(None) is None and table_written_by(b"not json") is None
    assert rederive_converged("0.7.0", "0.8.5") is False
    assert rederive_converged("0.8.5", "0.8.5") is True
    assert rederive_converged(None, "0.8.5") is None


def test_a_published_re_derivation_counts_its_drift_on_the_line_and_lists_it_in_the_log(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    """0.31.1: the module's line says how many subjects want reading; the log lists each; it published."""
    _publish(client, api_key, name="coronary")
    real = cli.upgrade_version
    line = "rs4244285 moved: 10:94781859 G>A -> 10:94781860 G>A"

    def upgrade_version(**kwargs):
        kwargs["drift_out"].append(line)
        return real(**kwargs)

    monkeypatch.setattr(cli, "upgrade_version", upgrade_version)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    monkeypatch.setenv("REGISTRY_RUN_DIR", str(tmp_path / "runs"))
    out = _sweep(settings, monkeypatch, "--apply", "--force")

    [head] = [row for row in out.splitlines() if f" {_NS}/coronary@" in row]
    assert head.startswith(f"✓ {_NS}/coronary@1.0.0 → 1.0.1 [") and head.endswith(" drift to read: 1"), head
    assert "1 re-derived module(s) published with drift worth reading (1 subject(s)" in out
    assert line not in out
    assert f"    drift: {line}" in _run_log(tmp_path)
    assert app.state.repo.version_exists(_NS, "coronary", "1.0.1")


# ── --withhold-rederive keeps the re-derivation; --accept-drift publishes it (0.31.1) ────────────────

_MOVED = SubjectDrift(
    variant_key="rs4244285", before="10:94781859 G>A", after="10:94781860 G>A", respelled=False, case="moved",
)


def test_withheld_drift_is_kept_and_accepting_publishes_it_without_re_deriving(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, enrich_calls: list[dict]
) -> None:
    """Through 0.31.0 the held re-derivation was dropped with its temporary directory, so accepting it
    re-derived the module again and spent every online request twice."""
    manifest = _publish(client, api_key)
    _as_0_7_table(app)
    _inject_drift(monkeypatch, _MOVED)
    enrich_calls.clear()
    args = {
        "repo": app.state.repo, "storage": app.state.storage, "settings": settings,
        "namespace": _NS, "name": _NAME, "version": "1.0.0", "manifest": manifest,
    }

    with pytest.raises(PublishError) as refused:
        upgrade_version(**args, withhold=True)
    assert refused.value.detail == "rederive_drift_needs_reading"
    assert refused.value.errors == [str(_MOVED)]
    assert not app.state.repo.version_exists(_NS, _NAME, "1.0.1")
    kept = held.find(settings, _NS, _NAME, "1.0.0")
    assert kept is not None and kept.stale_reason() is None
    assert kept.drift_to_read == [str(_MOVED)]
    kept_table = kept.files()[RESOLUTION_CSV]
    assert not resolution_needs_rederive(kept_table.decode())  # the 0.8 table, not the 0.7 one

    drift: list[str] = []
    result = upgrade_version(**args, from_held=kept, drift_out=drift)
    assert result is not None and result[0] == "1.0.1"
    # One re-derivation in all: the accepting publish only merges into the kept, complete table.
    assert [call["rederive"] for call in enrich_calls] == [True, False]
    assert drift == [str(_MOVED)]
    assert "1 moved" in _changelog(app, "1.0.1")
    stored = app.state.storage.read_file(version_key(_NS, _NAME, "1.0.1"), RESOLUTION_CSV)
    assert stored == kept_table
    assert held.find(settings, _NS, _NAME, "1.0.0") is None  # consumed


def test_a_kept_re_derivation_from_another_toolchain_is_never_published(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    manifest = _publish(client, api_key)
    _as_0_7_table(app)
    _inject_drift(monkeypatch, _MOVED)
    args = {
        "repo": app.state.repo, "storage": app.state.storage, "settings": settings,
        "namespace": _NS, "name": _NAME, "version": "1.0.0", "manifest": manifest,
    }
    with pytest.raises(PublishError):
        upgrade_version(**args, withhold=True)
    kept = held.find(settings, _NS, _NAME, "1.0.0")
    assert kept is not None
    real = held.toolchain()
    monkeypatch.setattr(held, "toolchain", lambda: {**real, "just-dna-enricher": "0.0.1"})
    assert "just-dna-enricher" in (kept.stale_reason() or "")
    with pytest.raises(UpgradeHeld) as stale:
        upgrade_version(**args, from_held=kept)
    assert stale.value.code == HELD_STALE
    assert not app.state.repo.version_exists(_NS, _NAME, "1.0.1")


def test_the_sweep_withholds_then_accepts_with_one_re_derivation(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch, enrich_calls: list[dict]
) -> None:
    _publish(client, api_key)
    _publish(client, api_key, name="coronary_two")
    _as_0_7_table(app)
    _inject_drift(monkeypatch, _MOVED)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    enrich_calls.clear()

    out = _sweep(settings, monkeypatch, "--apply", "--withhold-rederive", "-m", _NAME)
    assert f"✗ {_NS}/{_NAME}@1.0.0: rederive_drift_needs_reading" in out
    assert "--accept-drift" in out
    assert not app.state.repo.version_exists(_NS, _NAME, "1.0.1")
    # A second withholding sweep reports the kept result again and re-derives nothing.
    out = _sweep(settings, monkeypatch, "--apply", "--withold-rederive", "-m", _NAME)
    assert f"✗ {_NS}/{_NAME}@1.0.0: rederive_drift_needs_reading" in out
    assert [call["rederive"] for call in enrich_calls] == [True]

    out = _sweep(settings, monkeypatch, "--apply", "--accept-drift")
    published = [row for row in out.splitlines() if row.startswith(f"✓ {_NS}/{_NAME}@1.0.0 → 1.0.1")]
    assert len(published) == 1 and " kept" in published[0] and published[0].endswith("drift to read: 1"), out
    # coronary_two was never kept, so --accept-drift leaves it alone rather than re-deriving it.
    assert f"· {_NS}/coronary_two@1.0.0: unchanged not_kept" in out
    assert [call["rederive"] for call in enrich_calls] == [True, False]
    assert not app.state.repo.version_exists(_NS, "coronary_two", "1.0.1")


def test_withholding_and_accepting_at_once_is_refused(settings: Settings, monkeypatch) -> None:
    out = _sweep(settings, monkeypatch, "--apply", "--withhold-rederive", "--accept-drift", exit_code=2)
    assert "not both" in out
