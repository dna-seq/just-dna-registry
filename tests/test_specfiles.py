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
    has_spec_data,
    is_spec_file,
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


def test_the_unjoinable_marker_still_matches_what_the_compiler_emits(pgx_client) -> None:
    """The prose coupling in `facets.UNJOINABLE_MARKER`, pinned against the real compiler.

    `is_trusted` reads a *warning string* because the manifest carries no structured record of which
    checks ran (asked for as S8 upstream, tracked there as RM43). That coupling is acceptable only
    while a reword fails loudly instead of silently re-granting trust to modules that join to nothing
    — which is what this asserts. If the compiler rephrases, fix the marker; do not delete the test.
    """
    from just_dna_registry.db.facets import UNJOINABLE_MARKER, joins_nothing_positionally

    resp = pgx_client.post(
        "/api/v1/modules/just-dna-seq/cyp2c19_star_alleles/versions",
        data={"version": "1.0.0"},
        files=_pgx_parts(),
        headers={"Authorization": "Bearer mk_live_testkey"},
    )
    manifest = ModuleManifest.model_validate(resp.json())
    emitted = [w for w in manifest.compilation.warnings if UNJOINABLE_MARKER in w]
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
