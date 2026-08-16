"""
`specfiles.py` mirrors constants that are private to `just-dna-compiler`, so it can drift silently.

These tests are the tie-back. They reach into the compiler's `_TABLE_KINDS` / `_FACT_TABLES` /
`_INPUT_FILES` on purpose — the alternative is a hand-maintained list that goes stale the release a
table kind is added, and the failure mode of staleness is a module the registry rejects at publish
for no reason the author can see.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from just_dna_compiler.compiler import (
    _FACT_TABLES,
    _INPUT_FILES,
    _PROVENANCE_FILE,
    _TABLE_KIND_CSVS,
)
from just_dna_format.manifest import ModuleManifest

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.specfiles import (
    CORE_CSVS,
    FACT_CSVS,
    PROVENANCE_FILE,
    RECOGNIZED_SPEC_FILES,
    REQUIRED_SPEC_FILES,
    RESOLUTION_CSV,
    SIGNATURE_INPUTS,
    SPEC_DATA_FILES,
    SPEC_YAML,
    VERIFICATION_FILE,
    DERIVED_DIR,
    DERIVED_FILES,
    LEGACY_README_FILE,
    README_FILE,
    carries_spec_content,
    has_spec_data,
    is_spec_file,
    plan_layout,
)


def test_table_kinds_match_the_compiler() -> None:
    """A table kind the compiler accepts but the registry doesn't know is a module we reject for no
    reason the author can act on."""
    assert set(_TABLE_KIND_CSVS) == set(SPEC_DATA_FILES) - set(CORE_CSVS) - set(FACT_CSVS) - {
        RESOLUTION_CSV
    }


def test_fact_tables_match_the_compiler() -> None:
    assert {csv for csv, _, _ in _FACT_TABLES} == set(FACT_CSVS)


def test_signature_inputs_match_the_compilers_input_set() -> None:
    """`SIGNATURE_INPUTS` must be exactly what `content_signature(spec_dir)` reads, or a
    re-derivation materializes the wrong file set and produces a signature nothing else agrees
    with."""
    assert set(_INPUT_FILES) == set(SIGNATURE_INPUTS)


def test_provenance_filename_matches_the_compiler() -> None:
    assert _PROVENANCE_FILE == PROVENANCE_FILE


def test_the_authored_csv_loader_is_public_and_the_registry_needs_no_private_symbol() -> None:
    """The registry no longer loads `variants.csv` itself, and this pins why it does not have to.

    Through 0.11 `_acmg_check` reached for the compiler's **private** `_load_csv_rows`, because
    `verify_acmg_sf` took rows and nothing public turned a CSV into `VariantRow`s the way the
    compiler will — an empty cell becomes `None` rather than `""`, and the module's declared build is
    injected into each row. Compiler 0.5.1 (RM41) made `load_csv_rows` public and added
    `load_spec_variants`, and `verify_acmg_sf`/`check_identifiers` now take `spec_dir=`, so the
    registry hands over a directory and holds no copy of the rule.

    The assertion is that the *public* surface is still there. If it regressed, the tempting fix is to
    reach back for the private symbol or to hand-roll a loader — a second, drifting copy of a
    normalization this workspace already had to get right once.
    """
    import inspect

    from just_dna_compiler.compiler import load_csv_rows, load_spec_variants

    assert list(inspect.signature(load_csv_rows).parameters)[:3] == [
        "path", "row_model", "file_label"
    ]
    assert list(inspect.signature(load_spec_variants).parameters) == ["spec_dir"]


def test_recognized_covers_every_signature_input() -> None:
    """Anything that feeds the signature has to survive a storage round-trip, or revalidate and
    re-derivation disagree with publish about the same version."""
    assert set(SIGNATURE_INPUTS) <= set(RECOGNIZED_SPEC_FILES)


_MINIMAL_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  title: Coronary
  description: d
  report_title: R
genome_build: GRCh38
"""
_MINIMAL_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category,direction,"
    "stat_significance\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19,risk,significant\n"
)
_MINIMAL_STUDIES = (
    "rsid,pmid,population,p_value,conclusion,study_design\n"
    "rs4244285,[PMID: 29165669],T,0.05,E,U\n"
)


def test_the_verification_attestation_is_recognized_but_not_signed_over() -> None:
    """S11: `verification.json` reaches storage on publish and was then dropped by every rebuild.

    Two properties, and the second is what makes the first safe. Recognition is what makes
    `revalidate` materialize a file back out of storage and `upgrade` carry it forward — the
    `README.md` lesson of 0.14, at the enricher's attestation. Staying out of `SIGNATURE_INPUTS` is
    what keeps it from touching `content_signature`: an attestation is derived, and a module's
    identity must not depend on whether its author happened to ship one.
    """
    assert VERIFICATION_FILE in RECOGNIZED_SPEC_FILES
    assert VERIFICATION_FILE not in SIGNATURE_INPUTS
    assert is_spec_file(VERIFICATION_FILE)


def test_an_attestation_survives_the_rebuild_that_used_to_drop_it(client, api_key, app) -> None:
    """The end-to-end half: publish with one, and the upgrade planner still has it.

    `prepare_version_upgrade` rebuilds its file set from `RECOGNIZED_SPEC_FILES` ∩ storage, so before
    0.16 an author's attestation was uploaded, stored, and then silently absent from the very
    re-publish that claims to carry a version forward. Asserted beside `provenance.json`, which is
    deliberately *not* carried — it describes how the predecessor was built, while the attestation is
    hash-bound to the authored bytes and so invalidates itself if they move.
    """
    from just_dna_registry.services.upgrade import prepare_version_upgrade

    attestation = b'{"format": "0.6", "checks": {"clin_sig": {"checked": 0, "reason": "no snapshot"}}}'
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", (SPEC_YAML, _MINIMAL_YAML.encode(), "text/yaml")),
            ("files", ("variants.csv", _MINIMAL_VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _MINIMAL_STUDIES.encode(), "text/csv")),
            ("files", (VERIFICATION_FILE, attestation, "application/json")),
            ("files", (PROVENANCE_FILE, b'{"tool": "x"}', "application/json")),
        ],
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    manifest = ModuleManifest.model_validate(resp.json())

    storage = app.state.storage
    prep = prepare_version_upgrade(storage, "just-dna-seq", "coronary", "1.0.0", manifest)
    assert prep is not None
    assert prep.files[VERIFICATION_FILE] == attestation
    assert PROVENANCE_FILE not in prep.files

    # And it changed nothing about the module's identity: the same spec without it signs the same.
    without = client.post(
        "/api/v1/modules/just-dna-seq/plain/validate",
        files=[
            ("files", (SPEC_YAML, _MINIMAL_YAML.encode(), "text/yaml")),
            ("files", ("variants.csv", _MINIMAL_VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _MINIMAL_STUDIES.encode(), "text/csv")),
        ],
        headers={"Authorization": f"Bearer {api_key}"},
    ).json()
    with_it = client.post(
        "/api/v1/modules/just-dna-seq/plain/validate",
        files=[
            ("files", (SPEC_YAML, _MINIMAL_YAML.encode(), "text/yaml")),
            ("files", ("variants.csv", _MINIMAL_VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _MINIMAL_STUDIES.encode(), "text/csv")),
            ("files", (VERIFICATION_FILE, attestation, "application/json")),
        ],
        headers={"Authorization": f"Bearer {api_key}"},
    ).json()
    assert with_it["content_signature"] == without["content_signature"]


def test_required_is_only_the_yaml() -> None:
    """Composition is the compiler's rule. A PGx-only module carries no `variants.csv` and that is
    correct — the registry must not second-guess it with a hardcoded triple."""
    assert REQUIRED_SPEC_FILES == (SPEC_YAML,)


def test_has_spec_data_accepts_a_pgx_only_module() -> None:
    pgx_only = {SPEC_YAML, "haplotypes.csv", "diplotypes.csv", "allele_function.csv"}
    assert has_spec_data(pgx_only)
    assert not has_spec_data({SPEC_YAML})


def test_is_spec_file_rejects_compiled_output() -> None:
    assert is_spec_file("variants.csv")
    assert is_spec_file(RESOLUTION_CSV)
    assert not is_spec_file("weights.parquet")
    assert not is_spec_file("manifest.json")


# ── The composition rule, end to end ──────────────────────────────────────────

_PGX_EXAMPLE = Path("/data/sources/just-dna-format/reference_examples/cyp2c19_star_alleles")


@pytest.fixture
def pgx_client(tmp_path):
    """An app with empty, explicitly-pinned caches — so nothing on the developer's machine leaks in."""
    empty = tmp_path / "no-cache"
    client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "m.db",
                local_storage_dir=tmp_path / "a",
                ensembl_cache=empty,
                clinvar_cache=empty,
                constraint_cache=empty,
            )
        )
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    return client


def _pgx_parts():
    if not _PGX_EXAMPLE.is_dir():
        pytest.skip("just-dna-format reference examples not checked out beside this repo")
    return [
        ("files", (p.name, p.read_bytes(), "text/plain"))
        for p in sorted(_PGX_EXAMPLE.iterdir())
        if p.is_file() and p.suffix in (".csv", ".yaml", ".md")
    ]


def test_a_pgx_only_module_publishes_revalidates_and_upgrades(pgx_client) -> None:
    """One CSV = one concern: a PGx module carries no `variants.csv`, and that is complete.

    Through 0.10 all three services hardcoded a `(module_spec.yaml, variants.csv, studies.csv)`
    triple, so this module was rejected outright at publish, read as `skipped` by revalidate, and was
    permanently un-upgradable. Driven against a real reference example rather than a hand-written
    fixture, so it is the compiler's judgement of completeness being tested, not ours.
    """
    from just_dna_registry.db.facets import is_trusted
    from just_dna_registry.services.revalidate import revalidate_version
    from just_dna_registry.services.upgrade import prepare_version_upgrade

    name = "cyp2c19_star_alleles"
    resp = pgx_client.post(
        f"/api/v1/modules/just-dna-seq/{name}/versions",
        data={"version": "1.0.0"},
        files=_pgx_parts(),
        headers={"Authorization": "Bearer mk_live_testkey"},
    )
    assert resp.status_code == 201, resp.text
    manifest = ModuleManifest.model_validate(resp.json())

    # A variants-free module never gets a `resolution_mode`, and `fully_resolved` is then `all()` over
    # an empty list — vacuously `True`, about a file that does not exist.
    assert manifest.compilation.resolution_mode is None
    assert manifest.compilation.fully_resolved is True

    # Through 0.11.2 this asserted `is_trusted() is True`, reading that vacuous flag as a verdict.
    # It is not one *for this module*: all 106 `haplotypes.csv` rows carry a `start` with no `chrom`
    # (CPIC publishes the position on `sequence_location` and the chromosome on `gene` — there is no
    # `chrom` column at all), so nothing here joins to a VCF by position and the catalog was
    # advertising it as fully-baked. Compiler 0.5.3 is what makes this visible, and the warning is
    # the durable record of it.
    assert manifest.compilation.fully_resolved is True  # still vacuously so
    assert any("have no chrom+start" in w for w in manifest.compilation.warnings)
    assert is_trusted(manifest) is False

    storage = pgx_client.app.state.storage
    status, _ = revalidate_version(storage, "just-dna-seq", name, "1.0.0", manifest)
    assert status == "ok"  # was "skipped"

    prep = prepare_version_upgrade(storage, "just-dna-seq", name, "1.0.0", manifest)
    assert prep is not None  # was None — un-upgradable
    # The 0.5 sidecars survive the round trip. They are absent from `manifest.inputs` by design, so
    # carrying only what the manifest lists silently dropped them.
    assert {"resolution.csv", "sources.csv"} <= set(prep.files)


def test_a_module_that_joins_to_no_vcf_is_not_advertised_as_trusted(pgx_client) -> None:
    """The catalog column, not just the helper — a filter is what a consumer actually meets.

    `trusted` is projected into `versions` on publish, so the defect this covers was not "a function
    returned True" but "the catalog served a module that annotates nothing under the fully-baked
    facet". Driven through a real publish of a real reference example, because the whole point is that
    the compiler's judgement reaches the column.
    """
    resp = pgx_client.post(
        "/api/v1/modules/just-dna-seq/cyp2c19_star_alleles/versions",
        data={"version": "1.0.0"},
        files=_pgx_parts(),
        headers={"Authorization": "Bearer mk_live_testkey"},
    )
    assert resp.status_code == 201, resp.text
    # From the projected column (the version list reads rows, never re-parsing the manifest)...
    versions = pgx_client.get(
        "/api/v1/modules/just-dna-seq/cyp2c19_star_alleles/versions"
    ).json()["items"]
    assert [v["resolution"]["trusted"] for v in versions] == [False]
    # ...and from the manifest on the card, which is a second implementation that must agree.
    card = pgx_client.get("/api/v1/modules").json()["items"][0]
    assert card["resolution"]["trusted"] is False
    # The vacuous flag is still reported as the compiler set it — this facet reinterprets, not edits.
    assert card["resolution"]["fully_resolved"] is True


def test_the_unjoinable_phrase_still_reaches_the_manifest(pgx_client) -> None:
    """The prose coupling behind `is_trusted`, pinned against the real compiler.

    `is_trusted` reads a *warning string* because the manifest carries no structured record of which
    checks ran (asked for as S8 upstream, tracked there as RM43). That coupling is acceptable only
    while a break fails loudly instead of silently re-granting trust to modules that join to nothing.

    What this test is for changed with the 0.5.4 floor. The phrase is now imported from
    `just_dna_compiler.compiler.UNJOINABLE_PHRASE` (S13), so a *reword* can no longer desynchronize the
    two spellings — and an import cannot tell us the warning is still emitted, still fires for an
    rsid-only PGx module, and still survives into `manifest.compilation.warnings`, which is the only
    copy a reindex can see. That is the whole chain this drives, through a real publish of a real
    reference example. If it breaks, the facet has stopped seeing what the compiler says; do not delete
    the test.
    """
    from just_dna_registry.db.facets import UNJOINABLE_PHRASE, joins_nothing_positionally

    resp = pgx_client.post(
        "/api/v1/modules/just-dna-seq/cyp2c19_star_alleles/versions",
        data={"version": "1.0.0"},
        files=_pgx_parts(),
        headers={"Authorization": "Bearer mk_live_testkey"},
    )
    manifest = ModuleManifest.model_validate(resp.json())
    emitted = [w for w in manifest.compilation.warnings if UNJOINABLE_PHRASE in w]
    assert emitted, manifest.compilation.warnings
    # The sentence names the table and both counts, which is what makes it worth surfacing verbatim.
    assert "haplotypes.csv" in emitted[0] and "106" in emitted[0]
    assert joins_nothing_positionally(manifest) is True


def test_the_licensing_facet_surfaces_a_no_sale_clause(pgx_client) -> None:
    """Every PGx upstream is CC BY-SA *plus* a no-sale clause, and a marketplace has to know."""
    pgx_client.post(
        "/api/v1/modules/just-dna-seq/cyp2c19_star_alleles/versions",
        data={"version": "1.0.0"},
        files=_pgx_parts(),
        headers={"Authorization": "Bearer mk_live_testkey"},
    )
    card = pgx_client.get("/api/v1/modules").json()["items"][0]
    assert card["licensing"]["commercial_use"] is False
    # Only the annotation layer taints; a coordinate is a fact, so a fact-layer source does not.
    assert card["licensing"]["noncommercial_layers"] == ["annotation"]


# ── `plan_layout`: what may arrive, from where, and what it becomes ────────────


def test_the_signature_inputs_can_never_be_moved_by_the_derived_folder() -> None:
    """The invariant the whole layout convention rests on, asserted rather than assumed.

    `content_signature` reads `SIGNATURE_INPUTS` from the spec root. If a file that may live under
    `derived/` were ever added to that set, splitting a module would change its content identity and
    a downloaded module would stop being republishable as itself.
    """
    assert set(DERIVED_FILES).isdisjoint(SIGNATURE_INPUTS)


def test_derived_files_are_recognized_spec_files() -> None:
    """Otherwise `upgrade` and `revalidate`, which rebuild a spec from `RECOGNIZED_SPEC_FILES`,
    would drop exactly the tables the folder exists to hold."""
    assert set(DERIVED_FILES) <= set(RECOGNIZED_SPEC_FILES)


def test_a_recognized_file_is_hoisted_from_any_subdirectory() -> None:
    """Liberal in: `derived/` is what we emit, but a producer may already use another name and
    accepting theirs costs nothing. Blessing a second name in the code would mean keeping it."""
    for folder in (DERIVED_DIR, "metadata", "enriched", "authored"):
        plan = plan_layout([SPEC_YAML, f"{folder}/{RESOLUTION_CSV}"])
        assert plan.renames == {f"{folder}/{RESOLUTION_CSV}": RESOLUTION_CSV}
        assert plan.conflicts == []


def test_unknown_files_are_left_exactly_where_they_are() -> None:
    """The compiler tolerates unknown files as a contract; a rule invented here would break it."""
    plan = plan_layout([SPEC_YAML, "notes/scratch.txt", "figures/fig1.png", "receipt.txt"])
    assert plan.renames == {} and plan.conflicts == [] and plan.notes == []


def test_the_logs_subtree_is_never_touched() -> None:
    """The manifest records these paths verbatim, so hoisting one renames an attested file."""
    plan = plan_layout([SPEC_YAML, "logs/reviewer.log", "logs/nested/pi.log", "v1.log"])
    assert plan.renames == {}


def test_two_paths_for_one_root_name_is_a_conflict_not_a_choice() -> None:
    plan = plan_layout([SPEC_YAML, RESOLUTION_CSV, f"{DERIVED_DIR}/{RESOLUTION_CSV}"])
    assert plan.renames == {}
    assert len(plan.conflicts) == 1 and RESOLUTION_CSV in plan.conflicts[0]


def test_the_legacy_readme_is_renamed_unless_the_real_one_is_present() -> None:
    renamed = plan_layout([SPEC_YAML, LEGACY_README_FILE])
    assert renamed.renames == {LEGACY_README_FILE: README_FILE} and renamed.warnings == []

    both = plan_layout([SPEC_YAML, LEGACY_README_FILE, README_FILE])
    assert both.renames == {} and len(both.warnings) == 1


def test_a_readme_under_another_spelling_warns_rather_than_vanishing() -> None:
    """S7: the failure was silent in both directions, and the silence is the part worth fixing.

    Warned, never renamed. `MODULE.md` earns a rename because this project told authors to write it;
    guessing that `readme.md` or `README.txt` meant the card would be inventing intent, and the
    author can settle it with one rename or one `amend_readme` call.
    """
    for spelling in ("readme.md", "Readme.md", "README.txt", "README"):
        plan = plan_layout([SPEC_YAML, spelling])
        assert plan.renames == {}, f"{spelling} must not be renamed on a guess"
        assert len(plan.warnings) == 1, spelling
        assert README_FILE in plan.warnings[0] and "amend_readme" in plan.warnings[0]

    # Nothing was lost when the real name is there too, so nothing is said.
    assert plan_layout([SPEC_YAML, README_FILE, "readme.txt"]).warnings == []
    # And the ordinary case stays silent.
    assert plan_layout([SPEC_YAML, README_FILE]).warnings == []


def test_a_flat_spec_plans_no_change_at_all() -> None:
    """The common case has to be a no-op, or every publish rewrites bytes the author sent."""
    plan = plan_layout([SPEC_YAML, *CORE_CSVS, README_FILE, PROVENANCE_FILE, "logo.png", "v1.log"])
    assert not plan.changed and plan.notes == [] and plan.conflicts == []


def test_the_archive_filter_keeps_everything_the_planner_acts_on() -> None:
    """A dry run that drops what the publish would keep is not a rehearsal — and the pre-flight's
    archive filter runs *before* the planner, so anything it drops can never be normalized."""
    for name in (LEGACY_README_FILE, f"{DERIVED_DIR}/{RESOLUTION_CSV}", "logs/reviewer.log"):
        assert carries_spec_content(name), name
    assert not carries_spec_content("weights.parquet")
