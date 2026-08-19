"""
`specfiles.py` mirrors constants that are private to `just-dna-compiler`, so it can drift silently.

These tests are the tie-back. They reach into the compiler's `_TABLE_KINDS` / `_FACT_TABLES` /
`_INPUT_FILES` on purpose — the alternative is a hand-maintained list that goes stale the release a
table kind is added, and the failure mode of staleness is a module the registry rejects at publish
for no reason the author can see.
"""

import json
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
from just_dna_format.verification import VerificationDoc

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.specfiles import (
    CORE_CSVS,
    DERIVED_DIR,
    DERIVED_FILES,
    FACT_CSVS,
    LEGACY_README_FILE,
    LICENSING_CSV,
    PROVENANCE_FILE,
    README_FILE,
    RECOGNIZED_SPEC_FILES,
    RENAMED_ON_UPLOAD,
    REQUIRED_SPEC_FILES,
    RESOLUTION_CSV,
    SIGNATURE_INPUTS,
    SOURCES_CSV,
    SPEC_DATA_FILES,
    SPEC_YAML,
    VERIFICATION_FILE,
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

    **What is asserted changed at the 0.6 adoption, and the reason is worth keeping.** Through 0.16
    this compared the stored bytes to the uploaded bytes, which held because nothing on the server
    wrote this file. Under 0.6 the server's own enrichment attests its checks into it, so the stored
    copy is a *merge* and byte equality is the wrong question — asserting it would only pin that we
    had not adopted the feature. What must stay true is that the file survives the storage round-trip
    into the rebuild, which is what this test exists for; who wrote which record inside it is
    `test_a_publisher_cannot_forge_a_check_this_server_runs` below.
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
    assert PROVENANCE_FILE not in prep.files
    # Carried forward, and carried forward as a *readable* attestation rather than the bytes that
    # arrived: the server re-attested it during the publish, so what the rebuild gets is a document
    # the next compile can read.
    carried = VerificationDoc.model_validate_json(prep.files[VERIFICATION_FILE])
    assert {r.check for r in carried.records} == {r.check for r in manifest.verification.checks}
    assert manifest.verification is not None

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


def test_a_publisher_cannot_forge_a_check_this_server_runs(client, api_key) -> None:
    """Exactly how much of `manifest.verification` is the publisher's word, measured rather than assumed.

    The 0.17 decision to surface this block at all turned on this question, and the ROADMAP's worry —
    "a forged pass is worse than silence" — is *half* answered by the format, in a way that is much
    better than it looks from the models alone. Both halves are pinned here because the surface's
    wording depends on them, and a change in either would make our own documentation false.

    **Half one: a check this server runs cannot be forged.** The publish path runs enrichment itself
    and attests what it saw, and that record displaces whatever arrived under the same name. Here an
    upload claims `clinical_significance` ran over 999 subjects and found nothing; what publishes is
    this server's own `skipped` record for a deployment with no ClinVar snapshot.

    **Half two: a check this server does *not* run survives verbatim, and is unverifiable.** Nothing
    in this deployment produces `acmg_secondary_findings`, so the fabricated record is carried into
    the manifest exactly as sent. That is the residual surface, it is why every field in the block is
    presented as the publisher's claim, and it is why an absent block must read as *nothing was said*
    rather than as *nothing was found*.

    A third property falls out of the format and is worth pinning beside them: the **closure is
    hash-bound**. A closure whose `module_hash` does not match the authored bytes is dropped by the
    compiler rather than republished, so `closed` cannot be claimed by editing a JSON file.
    """
    forged = json.dumps(
        {
            "module_hash": "sha256:" + "0" * 64,
            "signature": "sha256:" + "0" * 64,
            "difficulty": 20,
            "nonce": 1,
            "producer": "totally-legit-tool 9.9",
            "produced_at": "2026-01-01T00:00:00Z",
            "closure": {
                "closed_at": "2026-01-01T00:00:00Z",
                "closed_by": "a person who says it is fine",
                "signature": None,
            },
            "records": [
                {
                    "check": check,
                    "subjects": 999,
                    "findings": 0,
                    "skipped": None,
                    "detail": "everything is perfect",
                    "source": source,
                    "release": "2026-01",
                    "checked_at": "2026-01-01T00:00:00Z",
                }
                for check, source in (
                    ("clinical_significance", "clinvar"),
                    ("acmg_secondary_findings", "acmg"),
                )
            ],
        }
    ).encode()
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", (SPEC_YAML, _MINIMAL_YAML.encode(), "text/yaml")),
            ("files", ("variants.csv", _MINIMAL_VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _MINIMAL_STUDIES.encode(), "text/csv")),
            ("files", (VERIFICATION_FILE, forged, "application/json")),
        ],
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    published = {r.check: r for r in ModuleManifest.model_validate(resp.json()).verification.checks}

    # Displacement is the property, not the verdict: this fixture *has* a ClinVar snapshot, so the
    # check really runs and reports `subjects=0` against a spec whose one variant it found nothing
    # for. What matters is that none of the forged cells survived — not the count, not the prose, and
    # not the invented release, which is replaced by the snapshot actually read.
    ours = published["clinical_significance"]
    assert ours.subjects == 0 and ours.detail != "everything is perfect", (
        "a forged 'ran' record displaced this server's own"
    )
    assert ours.release != "2026-01"
    theirs = published["acmg_secondary_findings"]
    assert theirs.subjects == 999 and theirs.skipped is None, (
        "the unverifiable half changed shape — re-read the surface's wording before changing this"
    )
    assert ModuleManifest.model_validate(resp.json()).verification.closure is None


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
    # an empty list — vacuously `True`, about a file that does not exist. 0.6 publishes the
    # denominator that says so out loud, which is what retires the inference.
    assert manifest.compilation.resolution_mode is None
    assert manifest.compilation.fully_resolved is True
    assert manifest.compilation.resolution_subjects == 0

    # **This module's verdict reversed at the 0.6 adoption, and it is the compiler that moved.**
    # Through 0.11.2 it read `True` off the vacuous flag; 0.11.3 corrected that to `False`, because
    # all 106 `haplotypes.csv` rows carried a `start` with no `chrom` (CPIC publishes the position on
    # `sequence_location` and the chromosome on `gene` — there is no `chrom` column at all), so
    # nothing joined to a VCF by position. RM43 shipped the positional fill: the same 106 rows are
    # now placed from the `resolution.csv` the example ships, and RM44/S31 publish that as counts
    # instead of a sentence. So the module really does annotate now, and `True` is the honest answer.
    assert (manifest.compilation.positional_rows, manifest.compilation.positional_rows_placed) == (
        106, 106
    )
    assert not any("have no chrom+start" in w for w in manifest.compilation.warnings)
    assert is_trusted(manifest) is True

    storage = pgx_client.app.state.storage
    status, _ = revalidate_version(storage, "just-dna-seq", name, "1.0.0", manifest)
    assert status == "ok"  # was "skipped"

    prep = prepare_version_upgrade(storage, "just-dna-seq", name, "1.0.0", manifest)
    assert prep is not None  # was None — un-upgradable
    # The derived sidecars survive the round trip. They are absent from `manifest.inputs` by design,
    # so carrying only what the manifest lists silently dropped them. The ledger is asserted under
    # the *current* spelling: 0.17 stores it as `licensing.csv`, and a rebuild that produced the
    # deprecated name would be re-introducing the file 1.0 stops reading.
    assert {"resolution.csv", LICENSING_CSV} <= set(prep.files)
    assert SOURCES_CSV not in prep.files


#: A PGx module that genuinely joins to nothing: rsID-keyed haplotypes with no coordinate column at
#: all, and no `resolution.csv` to fill one from, published against a deployment with empty caches.
#:
#: Hand-written, and that is a deliberate exception to this file's own rule of driving the real
#: reference corpus. The corpus **used to be** this case — the CPIC example carried 106 rows with a
#: `start` and no `chrom` — and RM43's positional fill repaired it, which is the good outcome and
#: also the reason a fixture is now needed: nothing published upstream is unjoinable any more. Left
#: to the corpus, the negative half of this facet would simply stop being tested, and the way we
#: would find out is a catalog advertising an unjoinable module as fully-baked.
_UNJOINABLE_YAML = """\
schema_version: "1.0"
module:
  name: rsid_only_pgx
  title: rsID-only PGx
  description: d
  report_title: R
genome_build: GRCh38
"""
_UNJOINABLE_HAPLOTYPES = (
    "haplotype_name,rsid,allele,gene\n"
    "*2,rs4244285,A,CYP2C19\n"
    "*17,rs12248560,T,CYP2C19\n"
)


def _publish_unjoinable(pgx_client) -> ModuleManifest:
    resp = pgx_client.post(
        "/api/v1/modules/just-dna-seq/rsid_only_pgx/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", (SPEC_YAML, _UNJOINABLE_YAML.encode(), "text/yaml")),
            ("files", ("haplotypes.csv", _UNJOINABLE_HAPLOTYPES.encode(), "text/csv")),
        ],
        headers={"Authorization": "Bearer mk_live_testkey"},
    )
    assert resp.status_code == 201, resp.text
    return ModuleManifest.model_validate(resp.json())


def test_a_module_that_joins_to_no_vcf_is_not_advertised_as_trusted(pgx_client) -> None:
    """The catalog column, not just the helper — a filter is what a consumer actually meets.

    `trusted` is projected into `versions` on publish, so the defect this covers was not "a function
    returned True" but "the catalog served a module that annotates nothing under the fully-baked
    facet".

    Since 0.17 the verdict is read from `positional_rows_placed` vs `positional_rows` rather than
    from warning prose, so this also pins that the *counts* reach the column — and it is a stronger
    check than the sentence ever allowed, because a partial failure now shows as 0 of 2 rather than
    as the mere presence of a complaint.
    """
    manifest = _publish_unjoinable(pgx_client)
    assert (manifest.compilation.positional_rows, manifest.compilation.positional_rows_placed) == (
        2, 0
    )
    # From the projected column (the version list reads rows, never re-parsing the manifest)...
    versions = pgx_client.get(
        "/api/v1/modules/just-dna-seq/rsid_only_pgx/versions"
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

    manifest = _publish_unjoinable(pgx_client)
    emitted = [w for w in manifest.compilation.warnings if UNJOINABLE_PHRASE in w]
    assert emitted, manifest.compilation.warnings
    # The sentence names the table and both counts, which is what makes it worth surfacing verbatim.
    assert "haplotypes.csv" in emitted[0] and "2" in emitted[0]
    assert joins_nothing_positionally(manifest) is True


def test_the_structured_counts_are_preferred_and_the_prose_is_the_legacy_path(pgx_client) -> None:
    """RM44's actual adoption: the counts decide, and the sentence only decides without them.

    `CLAUDE.md` and the 0.11.3 ROADMAP entry both said to delete the prose coupling once RM44 landed.
    It landed, and deleting it would have been wrong — every version already in a catalog was compiled
    before 0.6 and carries neither counter, so the sentence is still the only record a reindex can see
    for them. Deleting it would have silently re-granted trust to exactly the modules 0.11.3 took it
    from.

    Both paths are therefore pinned on one manifest, by stripping the counts off a copy of it: the
    same version must reach the same verdict either way, or the fallback is not a fallback.
    """
    from just_dna_registry.db.facets import (
        is_trusted,
        positionally_joinable,
        predates_positional_counts,
    )

    modern = _publish_unjoinable(pgx_client)
    assert predates_positional_counts(modern) is False
    assert positionally_joinable(modern) is False
    assert is_trusted(modern) is False

    # The same module as a pre-0.6 manifest: no counters, only the warning the compiler wrote.
    legacy = modern.model_copy(deep=True)
    legacy.compilation.positional_rows = None
    legacy.compilation.positional_rows_placed = None
    assert predates_positional_counts(legacy) is True
    assert positionally_joinable(legacy) is None  # cannot say — never `True`
    assert is_trusted(legacy) is False  # ...but the sentence still says it, so the verdict holds

    # With neither the counters nor the sentence, the answer is an admission rather than a pass.
    silent = legacy.model_copy(deep=True)
    silent.compilation.warnings = []
    assert is_trusted(silent) is None


def test_the_licensing_facet_surfaces_a_no_sale_clause(pgx_client) -> None:
    """Every PGx upstream is CC BY-SA *plus* a no-sale clause, and a marketplace has to know.

    Guarded on the shape rather than trusting it: this drives a sibling *working tree*, and when
    upstream renamed the ledger to `licensing.csv` (RM51) the ledger stopped reaching the compile and
    this test failed as a bare `assert True is False` — a wrong permissive facet reported as an
    arithmetic surprise. If the example stops carrying a ledger under either spelling, say so.
    """
    parts = _pgx_parts()  # skips when the sibling checkout is absent
    shipped = {name for _, (name, _, _) in parts}
    assert shipped & {SOURCES_CSV, LICENSING_CSV}, (
        f"the reference example carries no licensing ledger under either spelling: {sorted(shipped)}"
    )
    pgx_client.post(
        "/api/v1/modules/just-dna-seq/cyp2c19_star_alleles/versions",
        data={"version": "1.0.0"},
        files=parts,
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


def test_the_licensing_ledger_is_stored_under_the_spelling_that_survives_1_0() -> None:
    """The rename that inverted at the 0.6 adoption, and the reason it had to.

    Under 0.5 this pointed the other way: `licensing.csv` → `sources.csv`, because the compiler read
    only the old name and the ledger was otherwise dropped from the compile. A 0.6 compiler reads
    both, prefers `licensing.csv`, and warns that `sources.csv` is removed at 1.0. Left pointing
    backwards, this pass would have written a deprecation warning into `manifest.compilation.warnings`
    of every publish — permanently, since a published manifest is immutable — and stored the one
    spelling that stops being read at all at 1.0.

    The direction is not written down anywhere in `specfiles`: it is read off `SIDECAR_SPELLINGS` and
    `DEPRECATED_SPELLINGS`, so the next such rename arrives with the floor bump rather than with an
    incident.
    """
    plan = plan_layout([SPEC_YAML, "haplotypes.csv", SOURCES_CSV])
    assert plan.renames == {SOURCES_CSV: LICENSING_CSV}
    assert plan.warnings == [] and plan.conflicts == []
    assert len(plan.notes) == 1 and LICENSING_CSV in plan.notes[0]

    # The current spelling is left exactly alone — the common case must be a no-op.
    assert plan_layout([SPEC_YAML, "haplotypes.csv", LICENSING_CSV]).changed is False

    # And a deprecated spelling is still hoisted out of `derived/` while being renamed.
    subfoldered = plan_layout([SPEC_YAML, f"{DERIVED_DIR}/{SOURCES_CSV}"])
    assert subfoldered.renames == {f"{DERIVED_DIR}/{SOURCES_CSV}": LICENSING_CSV}


def test_both_licensing_spellings_present_is_refused_rather_than_preferred() -> None:
    """0.5 warned and let one win. 0.6 cannot: `layout.resolve_sidecar` **raises**.

    So carrying the loser through as an ordinary extra file no longer yields a publish with a
    warning — it yields a `SidecarCollision` out of the compiler with our own upload as the cause.
    Refused here instead, where the message names both paths and the author can act on it.

    Upstream's reasoning (RM49) is why agreeing beats working around it: these tables are fact-hashed
    and hand-editable, so two copies are two claims, and preferring either discards somebody's
    curation without saying so.
    """
    plan = plan_layout([SPEC_YAML, SOURCES_CSV, LICENSING_CSV])
    assert plan.renames == {} and plan.warnings == []
    assert len(plan.conflicts) == 1
    assert LICENSING_CSV in plan.conflicts[0] and SOURCES_CSV in plan.conflicts[0]

    # The readme keeps the *other* answer, and the divergence is deliberate: an extra markdown file
    # makes the compiler do nothing at all, while overwriting authored prose is unrecoverable.
    readme_plan = plan_layout([SPEC_YAML, README_FILE, LEGACY_README_FILE])
    assert readme_plan.conflicts == [] and len(readme_plan.warnings) == 1


def test_a_rename_can_never_move_a_module_identity_or_be_dropped_by_storage() -> None:
    """The two invariants that make `RENAMED_ON_UPLOAD` safe to add a name to.

    A destination inside `SIGNATURE_INPUTS` would mean an upload spelling decides `content_signature`
    — so the same data would claim two different global `409 duplicate_content` slots depending on
    which name it arrived under. A destination outside `RECOGNIZED_SPEC_FILES` would survive the
    publish and then be dropped by `revalidate`/`upgrade`, which rebuild a spec from that list.
    """
    destinations = set(RENAMED_ON_UPLOAD.values())
    assert destinations.isdisjoint(SIGNATURE_INPUTS)
    assert destinations <= set(RECOGNIZED_SPEC_FILES)
    # Sources are equally barred from `SIGNATURE_INPUTS`, and for the mirror-image reason: renaming
    # a signature input *away* would drop it out of `content_signature` entirely.
    assert set(RENAMED_ON_UPLOAD).isdisjoint(SIGNATURE_INPUTS)
    # A rename source may now be a recognized name, which it could not be at 0.5 — `sources.csv` is a
    # legal spelling the compiler still reads, not an alien name. What must stay true is that the
    # planner reaches the rename before claiming the file under its own name; `plan_layout` checks
    # `RENAMED_ON_UPLOAD` first, and this is the assertion that would catch that order being flipped.
    for source, dest in RENAMED_ON_UPLOAD.items():
        assert plan_layout([SPEC_YAML, source]).renames == {source: dest}


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
