"""0.3 contract upgrade: back-populate the additive 0.3 axes (direction/stat_significance/clin_sig)
from the legacy `state`/booleans and re-publish as a new PATCH. The `revalidate` audit surfaces such
versions as `upgradable` (they still validate — the columns are additive); `upgrade_version`
performs the migrate + re-publish, never mutating the predecessor."""

import csv
import io
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from just_dna_format.manifest import ModuleManifest
from just_dna_format.spec import StudyRow, VariantRow

from just_dna_registry.config import Settings
from just_dna_registry.services.publish import publish_version
from just_dna_registry.services.revalidate import revalidate_version
from just_dna_registry.services.upgrade import (
    GAP_CONTRACT,
    GAP_NONE,
    GAP_PATCH,
    GAP_UNKNOWN,
    _describe_variants_rewrite,
    contract_gap,
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
from just_dna_registry.version import installed_compiler

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
    the default is a no-op, because a same-contract version is not a gap.

    Sameness is asserted on `content_signature`, **not** on `artifact.digest`, and the distinction is
    the one `CLAUDE.md` draws: the digest names bytes and the signature names data. This spec authors no
    `sources.csv`, so the enricher writes one per compile with `fetched_at` stamped at second
    resolution, and `sources.parquet` is in `ARTIFACT_PARQUETS` — so two compiles of identical inputs
    produce different digests whenever they straddle a second. A digest assertion here was a coin flip
    on how long the compile took, which is the same defect 0.16.1 removed one file over."""
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
    # Non-lossy: identical spec recompiled under the same contract is the same *data*.
    assert new_manifest.content_signature == upgraded.content_signature
    assert new_manifest.content_signature is not None  # or the line above passes on two Nones


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


# ── The documented 0.5.4 → 0.6 catalog procedure ──────────────────────────────


_V054_CORPUS = Path("/data/sources/just-dna-format")


def _v054_specs(tmp_path: Path) -> list[Path]:
    """The real `v0.5.4` reference example specs, from the tag rather than the working tree.

    The tag matters: `main` and the checkout both carry 0.6-era specs (rewritten onto `licensing.csv`,
    new fact tables), so a corpus taken from the tree cannot answer "what does a 0.5-era catalog do".
    Skips rather than fails where the sibling repo is not present — this is the one test here that
    reaches outside its own tree.
    """
    if not (_V054_CORPUS / ".git").is_dir():
        pytest.skip("sibling just-dna-format checkout not available")
    out = tmp_path / "v054"
    out.mkdir()
    extract = subprocess.run(
        ["git", "archive", "v0.5.4", "reference_examples"],
        cwd=_V054_CORPUS, capture_output=True,
    )
    if extract.returncode != 0:
        pytest.skip("v0.5.4 tag not present in the sibling checkout")
    subprocess.run(["tar", "-x", "-C", str(out)], input=extract.stdout, check=True)
    specs = sorted(d for d in (out / "reference_examples").iterdir() if d.is_dir())
    assert len(specs) == 11, f"expected the 11-spec 0.5.4 corpus, got {len(specs)}"
    return specs


def _declared_name(spec_dir: Path) -> str:
    """The module's own name. Three of the eleven live in a directory named for their subject
    instead (`grch37_build` declares `hfe_grch37`), and publish enforces the match."""
    return yaml.safe_load((spec_dir / "module_spec.yaml").read_text())["module"]["name"]


def test_the_0_5_4_corpus_needs_force_for_the_digest_rebaseline(
    tmp_path: Path, settings: Settings, app
) -> None:
    """UPGRADE.md § 0.17 step 2 promises a catalog-wide digest re-baseline. Plain `upgrade` cannot
    deliver one, and this is the test that found it.

    `upgrade` acts only where there is *back-population* to do, so a module already on-contract is a
    deliberate no-op — which is exactly the population a schema-only re-baseline exists for. The step
    read `--apply` alone until this was driven over the real corpus: five of the eleven were skipped
    and kept their 0.5 parquet shape. Asserted as a partition rather than as counts, so the numbers
    can move with the corpus while the property cannot.
    """
    repo, storage = app.state.repo, app.state.storage
    repo.add_namespace("just-dna-seq", repo.create_account("ops"))

    skipped_without_force, acted_without_force = [], []
    for spec_dir in _v054_specs(tmp_path):
        name = _declared_name(spec_dir)
        files = {f.name: f.read_bytes() for f in spec_dir.iterdir() if f.is_file()}
        manifest = publish_version(
            repo=repo, storage=storage, settings=settings, namespace="just-dna-seq", name=name,
            version="1.0.0", changelog="0.5.4-era", owner="just-dna-seq", files=files,
        )
        plain = upgrade_version(
            repo=repo, storage=storage, settings=settings, namespace="just-dna-seq", name=name,
            version="1.0.0", manifest=manifest,
        )
        (acted_without_force if plain is not None else skipped_without_force).append(name)

        if plain is None:
            # The step-2 claim: with `--force` it re-emits anyway, and the digest moves.
            forced = upgrade_version(
                repo=repo, storage=storage, settings=settings, namespace="just-dna-seq", name=name,
                version="1.0.0", manifest=manifest, recompile=True,
            )
            assert forced is not None, f"{name}: --force must re-emit an on-contract module"
            _, remade = forced
            # Same authored data, so the content identity holds; only the compiled bytes move.
            assert remade.content_signature == manifest.content_signature
            assert remade.compilation.compile_success

    # The finding: plain `upgrade` is not a catalog-wide re-baseline, because some modules are skipped.
    assert skipped_without_force, (
        "no module was a no-op — either the corpus changed or `upgrade` now re-emits unconditionally; "
        "if the latter, UPGRADE.md § 0.17 step 2 can drop --force"
    )
    assert acted_without_force, "no module had back-population — the 0.3 half of step 2 is untested"


def test_back_population_moves_the_content_signature(
    tmp_path: Path, settings: Settings, app
) -> None:
    """§ 0's "content_signature does not move" is about the *contract*, not about `upgrade`.

    0.6 moves no signature. The 0.3 back-population `upgrade` applies on the way past does, because it
    rewrites authored cells — and a rewritten cell is new content by definition. Worth pinning
    separately from the step above: the two claims sit four lines apart in the document and read as one.
    """
    repo, storage = app.state.repo, app.state.storage
    repo.add_namespace("just-dna-seq", repo.create_account("ops"))

    moved = []
    for spec_dir in _v054_specs(tmp_path):
        name = _declared_name(spec_dir)
        files = {f.name: f.read_bytes() for f in spec_dir.iterdir() if f.is_file()}
        manifest = publish_version(
            repo=repo, storage=storage, settings=settings, namespace="just-dna-seq", name=name,
            version="1.0.0", changelog="0.5.4-era", owner="just-dna-seq", files=files,
        )
        status, _ = revalidate_version(
            storage, "just-dna-seq", name, "1.0.0", manifest, settings=settings,
        )
        out = upgrade_version(
            repo=repo, storage=storage, settings=settings, namespace="just-dna-seq", name=name,
            version="1.0.0", manifest=manifest,
        )
        if out is None:
            assert status != "upgradable", f"{name}: revalidate said upgradable and upgrade did nothing"
            continue
        _, upgraded = out
        # Exactly the modules `revalidate` flags are the ones whose authored data is rewritten, and a
        # rewrite of authored data must move the content identity.
        assert status == "upgradable", f"{name}: upgrade acted on a version revalidate called {status}"
        assert upgraded.content_signature != manifest.content_signature, (
            f"{name}: back-population rewrote authored cells without moving content_signature"
        )
        moved.append(name)

    assert moved, "no module was back-populated — this assertion would be vacuous"


# ── The prospective test-data guard, and a re-publish it cannot be about ─────────

_TEST_YAML = _YAML.replace("name: coronary", "name: test_coronary")


def _publish_test_named(
    repo, storage, settings: Settings, version: str = "1.0.0"
) -> ModuleManifest:
    """A `test_`prefixed module on a **production** instance, deliberately accepted (0.14).

    This is a state production is allowed to be in: `allow_test_data=true` is a documented override,
    it warns rather than refuses, and `purge-test-data` is the thing that removes it later.
    """
    return publish_version(
        repo=repo,
        storage=storage,
        settings=settings,
        namespace="just-dna-seq",
        name="test_coronary",
        version=version,
        changelog="seed",
        owner="just-dna-seq",
        files={
            "module_spec.yaml": _TEST_YAML.encode(),
            "variants.csv": _VARIANTS.encode(),
            "studies.csv": _STUDIES.encode(),
        },
        allow_test_data=True,
    )


def test_upgrade_re_publishes_test_prefixed_data_it_did_not_admit(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    """`upgrade` must not re-ask a question that was already answered when the data was admitted.

    The test-data guard is **prospective** (`CLAUDE.md`): it exists so a mistyped namespace cannot
    spend a version number and a global `content_hash` that only a purge frees. An `upgrade` re-publish
    spends neither on a new identifier — the module is already in the catalog under that exact name,
    admitted either by an `allow_test_data=true` override or by a deployment whose mode says this is
    the data it is for. Refusing there prevents nothing and makes the 0.17 catalog-wide re-baseline
    impossible to finish on any instance holding such a module.

    Driven on a **prod**-mode instance on purpose, because that is the case a mode flag cannot fix:
    the data is legitimately there and the operator has no way to pass the override through `upgrade`.
    """
    repo, storage = app.state.repo, app.state.storage
    assert settings.is_test_instance is False
    manifest = _publish_test_named(repo, storage, settings)

    result = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="test_coronary", version="1.0.0",
        manifest=manifest, recompile=True,
    )

    assert result is not None, "the upgrade was a no-op, so this test proves nothing"
    new_version, new_manifest = result
    assert new_version == "1.0.1"
    assert new_manifest.identity.name == "test_coronary"
    # The predecessor is untouched, exactly as for any other upgrade.
    assert repo.get_manifest_json("just-dna-seq", "test_coronary", "1.0.0") is not None


# ── The contract gap, detected rather than asserted by a flag ─────────────────────


def _manifest_compiled_under(manifest: ModuleManifest, compiler: str | None) -> ModuleManifest:
    """The same manifest as if an older (or unidentifiable) compiler had produced it.

    A copy rather than a mutation, and the stamp is written in the compiler's own spelling — a name
    and a version — because parsing that spelling is exactly what is under test.
    """
    clone = manifest.model_copy(deep=True)
    clone.compilation.compiler_version = compiler
    return clone


def test_the_gap_is_measured_against_the_installed_compiler(
    client: TestClient, api_key: str
) -> None:
    """A version compiled under an older *contract* is found without anybody passing `--force`.

    This is the defect that made `--force` the documented normal path at the 0.6 cut: the predecessor
    of this function asked "is `content_signature` absent", true only of a pre-0.5 manifest, so every
    0.5-era version answered *no gap* and a catalog-wide re-baseline skipped 5 of 11 reference modules
    while reporting success. The rule is now a comparison, so it cannot go stale at the next cut.

    All four scales are driven, and the two that must **not** act are the point as much as the one that
    must: a compiler patch moves no schema, and an unidentifiable stamp is not evidence of anything.
    """
    manifest = _publish(client, api_key)
    current = installed_compiler()
    assert current is not None, "the server tier is installed in this suite"

    fresh = contract_gap(manifest)
    assert (fresh.scale, fresh.witness) == (GAP_NONE, "compiler_version")
    assert fresh.acts_by_default is False

    older_contract = contract_gap(
        _manifest_compiled_under(manifest, "just-dna-compiler 0.5.4")
    )
    assert older_contract.scale == GAP_CONTRACT
    assert older_contract.acts_by_default is True
    assert older_contract.compiled_under == "0.5.4" and older_contract.current == current
    assert "0.5.4" in older_contract.describe()

    patch_only = contract_gap(
        _manifest_compiled_under(manifest, "just-dna-compiler 0.6.0")
    )
    assert patch_only.scale == GAP_PATCH
    assert patch_only.acts_by_default is False, "a patch moves no schema; --force is for that"

    for stamp in ("just-dna-compiler unknown", "some-other-compiler 3", None):
        unknown = contract_gap(_manifest_compiled_under(manifest, stamp))
        assert unknown.scale == GAP_UNKNOWN, stamp
        assert unknown.acts_by_default is False, stamp
        assert "cannot be identified" in unknown.describe()


def test_a_pre_0_5_manifest_is_still_dated_without_a_parseable_stamp(
    client: TestClient, api_key: str
) -> None:
    """The old witness is kept as a fallback, because it reaches where the stamp does not.

    The compiler began writing `content_signature` in 0.5, so its absence dates a manifest with no
    parsing at all. `witness` says which comparison decided — the field exists so "I compared 0.5.4
    against 0.6.1" is distinguishable from "I found no signature, which only means older than 0.5".
    """
    manifest = _manifest_compiled_under(_publish(client, api_key), None)
    manifest.content_signature = None

    gap = contract_gap(manifest)
    assert (gap.scale, gap.witness) == (GAP_CONTRACT, "content_signature")
    assert gap.acts_by_default is True
    assert gap.compiled_under is None
    assert "pre-0.5" in gap.describe()


def test_upgrade_acts_on_a_contract_gap_with_no_force(
    client: TestClient, api_key: str, app, settings: Settings
) -> None:
    """End to end: `upgrade_version` with `recompile=False` re-publishes an older-contract version.

    **Driven on a version with no 0.3 drift left, and that is the whole design of this test.** The
    fixture spec carries legacy `state` cells, so a data gap would make the upgrade act for a reason
    that has nothing to do with the contract — which is precisely the population the 0.6 sweep did
    *not* skip. The five it skipped were the ones already on-contract in their data, where the stale
    parquet was the only thing left to fix. So this upgrades once to exhaust the drift, then stamps the
    successor as 0.5.4-compiled: after that the gap is the only possible reason to act.

    The same call is a no-op for a version this server just compiled, which is what keeps the sweep
    idempotent — run it twice and the second run does nothing.
    """
    manifest = _publish(client, api_key)
    repo, storage = app.state.repo, app.state.storage

    # Exhaust the 0.3 data gap first: 1.0.1 is on-contract in its rows.
    _, on_contract = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", manifest=manifest,
    )
    assert prepare_version_upgrade(
        storage, "just-dna-seq", "coronary", "1.0.1", on_contract
    ).variants_plan.needed is False, "the drift must be gone, or the gap is not what is under test"

    # Now the only difference is the stamp: as if 0.5.4 had produced these very bytes.
    stale = _manifest_compiled_under(on_contract, "just-dna-compiler 0.5.4")
    repo.set_version_manifest("just-dna-seq", "coronary", "1.0.1", stale)

    result = upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version="1.0.1", manifest=stale,
    )
    assert result is not None, "a contract gap must not need --force"
    new_version, new_manifest = result
    assert new_version == "1.0.2"
    # The immutable changelog names the versions it compared instead of a hardcoded era. The old text
    # said "under just-dna-format 0.5" and would have stamped that, permanently, onto every version
    # re-baselined at the 0.6 cut.
    changelog = repo.get_version_changelog("just-dna-seq", "coronary", "1.0.2")
    assert changelog is not None
    assert "0.5.4" in changelog and str(installed_compiler()) in changelog

    # And the successor, compiled here and now, is not a gap.
    assert upgrade_version(
        repo=repo, storage=storage, settings=settings,
        namespace="just-dna-seq", name="coronary", version=new_version, manifest=new_manifest,
    ) is None


def test_the_plan_reports_which_columns_it_actually_rewrote() -> None:
    """S15: the changelog named three columns it did not touch and omitted the one it did.

    The reporter measured `antonkulaga/big_five_personality_snps` 1.0.0 → 1.0.1: `direction` and
    `stat_significance` were already authored and did not move, `clin_sig` arrived empty on all 990
    rows, and `state` was rewritten on 990 of 990 — while the changelog read *"back-populated the 0.3
    axes (direction/stat_significance/clin_sig)"*, a hardcoded list naming exactly the three that
    stood still.

    This fixture is that shape: both 0.3 axes authored, `state` carrying the legacy vocabulary that
    `upgraded()` trims to a derived mirror of `direction`. The assertion is on the *measured* diff,
    so it fails if the counts are inferred from `_UPGRADED_COLUMNS` rather than observed.
    """
    authored = (
        "rsid,genotype,weight,state,conclusion,direction,stat_significance\n"
        "rs1,A/G,0.4,ref,ok,neutral,not_significant\n"
        "rs2,C/T,0.9,significant,ok,neutral,not_significant\n"
    )
    plan = plan_variants_upgrade(authored)
    assert plan.upgradable_rows == 2, "the rows do need an upgrade — via `state`, not the axes"

    # The heart of it: only the column that moved is reported, and with a real count.
    assert plan.changed_cells == {"state": 2}
    assert set(plan.changed_cells) & {"direction", "stat_significance"} == set()

    rows = list(csv.DictReader(io.StringIO(plan.migrated_variants_csv)))
    assert {r["state"] for r in rows} == {"neutral"}, "state really was rewritten"
    assert {r["direction"] for r in rows} == {"neutral"}, "and direction really was not"

    # A column that arrives and stays empty changes the shape, not a value — so it is reported as
    # added and not as changed. Counting it among the changes is the error S15 is the mirror of.
    assert "clin_sig" in plan.added_columns
    assert "clin_sig" not in plan.changed_cells


def test_the_upgrade_changelog_names_the_columns_it_moved() -> None:
    """The sentence a published version keeps forever, and the reason S15 was worth a release.

    A changelog is the only human-readable record of what a version changed, and this one is written
    by us rather than by the publisher — so an inaccuracy here is ours and is immutable once the
    version is published.
    """
    authored = (
        "rsid,genotype,weight,state,conclusion,direction,stat_significance\n"
        "rs1,A/G,0.4,ref,ok,neutral,not_significant\n"
    )
    plan = plan_variants_upgrade(authored)
    sentence = _describe_variants_rewrite(plan)

    assert "rewrote state on 1 row(s)" in sentence
    for untouched in ("direction", "stat_significance"):
        assert untouched not in sentence, f"{untouched} did not move and must not be claimed"
    assert "clin_sig" in sentence, "it did arrive, and the header change is worth recording"
    assert "added column(s)" in sentence
