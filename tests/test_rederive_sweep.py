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
from just_dna_registry.services import enrich as enrich_service
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


def test_an_arm_upstream_adds_holds_until_somebody_reads_it() -> None:
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


def test_drift_that_wants_reading_holds_the_successor_until_accepted(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    manifest = _publish(client, api_key)
    _as_0_7_table(app)
    moved = SubjectDrift(
        variant_key="rs4244285", before="10:94781859 G>A", after="10:94781860 G>A",
        respelled=False, case="moved",
    )
    _inject_drift(monkeypatch, moved)
    args = {
        "repo": app.state.repo, "storage": app.state.storage, "settings": settings,
        "namespace": _NS, "name": _NAME, "version": "1.0.0", "manifest": manifest,
    }

    with pytest.raises(PublishError) as refused:
        upgrade_version(**args)
    assert refused.value.detail == "rederive_drift_needs_reading"
    assert refused.value.errors == [str(moved)]
    assert refused.value.extra["drift"] == {"moved": 1}
    # Nothing was published: the refusal is before the compile.
    assert not app.state.repo.version_exists(_NS, _NAME, "1.0.1")

    result = upgrade_version(**args, accept_drift=True)
    assert result is not None
    assert "1 moved" in _changelog(app, result[0])
    assert "read and accepted by the operator" in _changelog(app, result[0])


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
        seen.append(kwargs)
        raise Stop

    monkeypatch.setattr(enricher, "enrich", record)
    with pytest.raises(Stop):
        upgrade_version(**args, online=True)
    assert seen[0]["offline"] is False and seen[0]["rederive"] is True
    # The process's own settings are untouched: only that one publish went online.
    assert settings.enrich_offline is True


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


def _sweep(settings: Settings, monkeypatch, *args: str) -> str:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(settings.local_storage_dir))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["upgrade", *args])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    return result.output


def test_the_dry_run_states_how_each_module_re_derives(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    _publish(client, api_key)
    _as_0_7_table(app)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    out = _sweep(settings, monkeypatch, "--dry-run")
    assert "re-derive: snapshot only" in out
    assert "re-derive 2 recorded subject(s) from the snapshot" in out
    assert "1 version(s) would upgrade" in out


def test_a_stale_snapshot_holds_every_re_derivation_and_publishes_none(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    _publish(client, api_key)
    _as_0_7_table(app)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: "pulled from the old release")
    out = _sweep(settings, monkeypatch, "--apply")
    assert "re-derive refused for every module that needs it" in out
    assert f"held {_NS}/{_NAME}@1.0.0: pulled from the old release" in out
    assert "0 version(s) upgraded" in out
    assert not app.state.repo.version_exists(_NS, _NAME, "1.0.1")


def test_one_refusal_does_not_end_the_sweep(
    client: TestClient, api_key: str, app, settings: Settings, monkeypatch
) -> None:
    _publish(client, api_key, name="coronary")
    _publish(client, api_key, name="coronary_two")
    attempted: list[str] = []

    def refuse(**kwargs):
        attempted.append(kwargs["name"])
        raise PublishError("rederive_drift_needs_reading", errors=["rs1 moved: the source names a different event"])

    monkeypatch.setattr(cli, "upgrade_version", refuse)
    monkeypatch.setattr(cli, "snapshot_not_current", lambda _s: None)
    out = _sweep(settings, monkeypatch, "--apply")
    assert sorted(attempted) == ["coronary", "coronary_two"]
    assert out.count("✗ just-dna-seq/") == 2
    assert "2 refused" in out
    assert "--accept-drift" in out
