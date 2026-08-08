"""0.3 contract upgrade: back-populate the additive 0.3 axes (direction/stat_significance/clin_sig)
from the legacy `state`/booleans and re-publish as a new PATCH. The `revalidate` audit surfaces such
versions as `upgradable` (they still validate — the columns are additive); `upgrade_version`
performs the migrate + re-publish, never mutating the predecessor."""

import csv
import io

import yaml
from fastapi.testclient import TestClient
from just_dna_format.manifest import ModuleManifest
from just_dna_format.spec import StudyRow, VariantRow

from just_dna_registry.config import Settings
from just_dna_registry.services.revalidate import revalidate_version
from just_dna_registry.services.upgrade import (
    is_latest_version,
    offending_columns,
    offending_yaml_keys,
    plan_variants_upgrade,
    prepare_version_upgrade,
    trim_unknown_columns,
    trim_unknown_yaml_keys,
    upgrade_version,
)
from just_dna_registry.storage.base import version_key

_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  title: Coronary
  description: d
  report_title: R
genome_build: GRCh38
"""
# Legacy spec: only `state`, no 0.3 columns.
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
    "rs1801133,1,11796321,G,A,A/G,0.4,protective,het,MTHFR,folate\n"
)
_STUDIES = (
    "rsid,pmid,population,p_value,conclusion,study_design\n"
    "rs4244285,29165669,T,0.05,E,U\nrs1801133,29165669,T,0.05,E,U\n"
)


def _publish(client: TestClient, key: str, version: str = "1.0.0") -> ModuleManifest:
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": version},
        files=[
            ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201, resp.text
    return ModuleManifest.model_validate(resp.json())


# ── Pure planner ─────────────────────────────────────────────────────────────────


def test_plan_backfills_from_state_and_is_idempotent() -> None:
    plan = plan_variants_upgrade(_VARIANTS)
    assert (plan.total_rows, plan.upgradable_rows) == (2, 2)

    rows = list(csv.DictReader(io.StringIO(plan.migrated_variants_csv)))
    by_rsid = {r["rsid"]: r for r in rows}
    # risk → direction risk, unknown significance; protective → protective.
    assert by_rsid["rs4244285"]["direction"] == "risk"
    assert by_rsid["rs4244285"]["stat_significance"] == "unknown"
    assert by_rsid["rs1801133"]["direction"] == "protective"
    # Original columns are untouched.
    assert by_rsid["rs4244285"]["gene"] == "CYP2C19"

    # Idempotent: re-planning the migrated CSV finds nothing left to do.
    assert plan_variants_upgrade(plan.migrated_variants_csv).upgradable_rows == 0


def test_plan_leaves_already_0_3_rows_alone() -> None:
    already = (
        "rsid,genotype,weight,state,conclusion,direction,stat_significance\n"
        "rs1,A/G,0.4,protective,ok,protective,significant\n"
    )
    assert plan_variants_upgrade(already).upgradable_rows == 0


# ── End-to-end through storage + republish ───────────────────────────────────────


def test_revalidate_reports_upgradable(client: TestClient, api_key: str, app) -> None:
    manifest = _publish(client, api_key)
    status, messages = revalidate_version(app.state.storage, "just-dna-seq", "coronary", "1.0.0", manifest)
    assert status == "upgradable", messages
    assert messages and "0.3 columns" in messages[0]


def test_upgrade_publishes_next_patch_and_leaves_predecessor(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    manifest = _publish(client, api_key)
    result = upgrade_version(
        repo=app.state.repo, storage=app.state.storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
    )
    assert result is not None
    new_version, new_manifest = result
    assert new_version == "1.0.1"

    # The successor's stored spec carries the back-populated 0.3 columns.
    migrated = app.state.storage.read_file(
        version_key("just-dna-seq", "coronary", "1.0.1"), "variants.csv"
    ).decode()
    by_rsid = {r["rsid"]: r for r in csv.DictReader(io.StringIO(migrated))}
    assert by_rsid["rs4244285"]["direction"] == "risk"

    # Predecessor is untouched (immutable) and now itself validates clean of drift.
    old = app.state.storage.read_file(
        version_key("just-dna-seq", "coronary", "1.0.0"), "variants.csv"
    ).decode()
    assert old == _VARIANTS

    # And re-publishing the successor would be a no-op: it no longer drifts.
    status, _ = revalidate_version(
        app.state.storage, "just-dna-seq", "coronary", "1.0.1", new_manifest
    )
    assert status == "ok"


def test_upgrade_is_noop_when_no_drift(client: TestClient, api_key: str, app, settings: Settings) -> None:
    manifest = _publish(client, api_key)
    # First upgrade produces 1.0.1; a second upgrade of 1.0.1 has nothing to do.
    first = upgrade_version(
        repo=app.state.repo, storage=app.state.storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
    )
    assert first is not None
    _, upgraded_manifest = first
    second = upgrade_version(
        repo=app.state.repo, storage=app.state.storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.1", manifest=upgraded_manifest,
    )
    assert second is None


def test_superseded_predecessor_is_not_re_upgraded(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    # The immutability bug: once 1.0.0 has been upgraded to 1.0.1, re-running upgrade on the still
    # drifted 1.0.0 must NOT mint 1.0.2 (and 1.0.3, …) forever — the successor masks it.
    manifest = _publish(client, api_key)
    repo, storage = app.state.repo, app.state.storage
    new_version, _ = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
    )
    assert new_version == "1.0.1"
    assert is_latest_version(repo, "just-dna-seq", "coronary", "1.0.1")
    assert not is_latest_version(repo, "just-dna-seq", "coronary", "1.0.0")

    # 1.0.0 still *drifts* on its own bytes (immutable) …
    assert plan_variants_upgrade(_VARIANTS).needed
    # … but upgrading it is now a no-op — no 1.0.2 is created.
    again = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
    )
    assert again is None
    assert not repo.version_exists("just-dna-seq", "coronary", "1.0.2")


# ── Schema recompile (--force / recompile) ────────────────────────────────────────

def test_recompile_republishes_on_contract_version(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    """`recompile=True` re-emits a module with no 0.3 drift as the next PATCH (a schema migration);
    the default is a no-op. Within one contract the recompile is deterministic → identical digest."""
    manifest = _publish(client, api_key)
    repo, storage = app.state.repo, app.state.storage
    _, upgraded = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
    )  # 1.0.1 is now on-contract (no drift)

    # Default: nothing to do.
    assert upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.1", manifest=upgraded,
    ) is None
    # recompile=True re-publishes anyway.
    result = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.1", manifest=upgraded,
        recompile=True,
    )
    assert result is not None
    new_version, new_manifest = result
    assert new_version == "1.0.2"
    assert new_manifest.compilation.compile_success
    # Non-lossy: identical spec recompiled under the same contract yields the same content identity.
    assert new_manifest.artifact.digest == upgraded.artifact.digest


# ── Column trim (--trim, lossy) ───────────────────────────────────────────────────

# A legacy spec whose lax schema let an unknown column through (`legacy_note`) — 0.4 forbids it.
_VARIANTS_EXTRA_COL = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category,legacy_note\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19,keep-for-now\n"
)


def test_offending_and_trim_helpers() -> None:
    assert offending_columns(_VARIANTS_EXTRA_COL, VariantRow) == ["legacy_note"]
    trimmed, dropped = trim_unknown_columns(_VARIANTS_EXTRA_COL, VariantRow)
    assert dropped == ["legacy_note"]
    assert "legacy_note" not in trimmed and "CYP2C19" in trimmed
    assert offending_columns(trimmed, VariantRow) == []
    # A clean CSV is a byte-preserving no-op.
    assert trim_unknown_columns(_VARIANTS, VariantRow) == (_VARIANTS, [])
    assert offending_columns(_STUDIES, StudyRow) == []


def _make_stored_spec_legacy(app, api_key, client) -> ModuleManifest:
    """Publish a clean module, then overwrite its stored `variants.csv` with one carrying a column
    the current contract rejects — simulating a version published under an older, lax schema."""
    manifest = _publish(client, api_key)
    app.state.storage.store_module(
        version_key("just-dna-seq", "coronary", "1.0.0"),
        {"variants.csv": _VARIANTS_EXTRA_COL.encode()},
    )
    return manifest


def test_offending_column_blocks_upgrade_without_trim(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    manifest = _make_stored_spec_legacy(app, api_key, client)
    storage = app.state.storage
    prep = prepare_version_upgrade(storage, "just-dna-seq", "coronary", "1.0.0", manifest, trim=False)
    assert prep.blocked == {"variants.csv": ["legacy_note"]}
    assert not prep.would_act(recompile=True)  # blocked wins even over recompile
    # And the upgrade itself is a no-op (blocked), never crashing on the unknown column.
    assert upgrade_version(
        repo=app.state.repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
    ) is None


def test_trim_drops_column_and_republishes(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    manifest = _make_stored_spec_legacy(app, api_key, client)
    repo, storage = app.state.repo, app.state.storage
    prep = prepare_version_upgrade(storage, "just-dna-seq", "coronary", "1.0.0", manifest, trim=True)
    assert prep.dropped == {"variants.csv": ["legacy_note"]}
    assert prep.would_act(recompile=False)

    result = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
        trim=True, prepared=prep,
    )
    assert result is not None
    new_version, _ = result
    assert new_version == "1.0.1"
    # The offending column is gone from the successor's stored spec (lossy trim applied) …
    migrated = storage.read_file(
        version_key("just-dna-seq", "coronary", "1.0.1"), "variants.csv"
    ).decode()
    header = migrated.splitlines()[0]
    assert "legacy_note" not in header
    # … and the 0.3 back-population still ran on the trimmed spec.
    assert "direction" in header
    # Predecessor's stored (legacy) bytes are untouched.
    assert "legacy_note" in storage.read_file(
        version_key("just-dna-seq", "coronary", "1.0.0"), "variants.csv"
    ).decode()


# ── YAML-key trim (module_spec.yaml) ──────────────────────────────────────────────

# A legacy module_spec.yaml with a top-level unknown key and a typo'd `defaults` key. `module.version`
# is registry-owned (stripped non-lossily at publish), so it must NOT count as an offender here.
_YAML_LEGACY = """\
schema_version: "1.0"
legacy_top: whatever
module:
  name: coronary
  version: 2
  title: Coronary
  description: d
  report_title: R
defaults:
  curator: ai-module-creator
  currator: typo
genome_build: GRCh38
"""


def test_offending_yaml_keys_excludes_registry_owned() -> None:
    offenders = set(offending_yaml_keys(_YAML_LEGACY))
    assert offenders == {"legacy_top", "defaults.currator"}
    assert "module.version" not in offenders  # registry-owned, handled by the always-on strip
    trimmed, dropped = trim_unknown_yaml_keys(_YAML_LEGACY)
    assert set(dropped) == {"legacy_top", "defaults.currator"}
    assert offending_yaml_keys(trimmed) == []
    # The registry-owned key and the real keys are preserved by the trim.
    reparsed = yaml.safe_load(trimmed)
    assert reparsed["module"]["version"] == 2 and reparsed["defaults"]["curator"] == "ai-module-creator"


def test_trim_drops_yaml_keys_and_republishes(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    manifest = _publish(client, api_key)
    repo, storage = app.state.repo, app.state.storage
    # Overwrite the stored module_spec.yaml with a legacy one carrying offending keys.
    storage.store_module(
        version_key("just-dna-seq", "coronary", "1.0.0"), {"module_spec.yaml": _YAML_LEGACY.encode()}
    )
    blocked = prepare_version_upgrade(storage, "just-dna-seq", "coronary", "1.0.0", manifest, trim=False)
    assert blocked.blocked == {"module_spec.yaml": ["legacy_top", "defaults.currator"]}

    result = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
        trim=True,
    )
    assert result is not None
    new_ver, _ = result
    stored_yaml = storage.read_file(
        version_key("just-dna-seq", "coronary", new_ver), "module_spec.yaml"
    ).decode()
    assert "legacy_top" not in stored_yaml and "currator" not in stored_yaml
    # The authored `module.version` SURVIVES, quoted. Format 0.5 made it a real advisory field, so
    # the publish path normalizes it (`2` → `"2"`) instead of dropping it the way 0.10 did — the
    # registry stamps `Identity.version` regardless, so keeping the author's marker costs nothing.
    # It is not a trim offender either: the trim only removes keys no model accepts.
    assert yaml.safe_load(stored_yaml)["module"]["version"] == "2"
