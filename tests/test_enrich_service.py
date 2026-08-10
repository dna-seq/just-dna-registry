"""
Unit tests for `services/enrich.py` — the seam where the network tier is wired.

Three things worth pinning that no HTTP test reaches:

* **The tier boundary.** CONSTITUTION Principle 2 says the compile path never imports the enricher.
  That is enforceable only because the import is lazy, and enforceable *forever* only because a test
  checks it.
* **VRS coverage**, which since enricher 0.5.1 (RM40) the registry *projects* rather than derives —
  so what is worth pinning moved: not the arithmetic, but that a dry run's numbers still equal the
  ones the compiler independently stamps into the manifest.
* **Cache resolution**, where the difference between "as configured" and "as resolved" decides
  whether a deployment can be pinned at all.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from just_dna_registry.config import Settings
from just_dna_registry.services.enrich import (
    EnrichmentGate,
    enricher_available,
    EnrichOutcome,
    PULLABLE_REFERENCES,
    REFERENCE_NAMES,
    RESOLUTION_REFERENCES,
    _render_notes,
    available_references,
    clin_sig_skip_note,
    configured_caches,
    unresolved_hint,
    vrs_coverage,
)


# ── The tier boundary ─────────────────────────────────────────────────────────


def test_the_compile_path_does_not_import_the_enricher() -> None:
    """CONSTITUTION Principle 2, made mechanical.

    `services/publish.py` runs the compile. If it ever gains a module-level `just_dna_enricher`
    import — directly or through something it imports — the compile path is importing the network
    tier, and the guarantee that the compiler cannot fetch stops being structural. Checked in a fresh
    interpreter, because in this one the enricher is already imported by other tests.
    """
    probe = (
        "import sys; import just_dna_registry.services.publish; "
        "print('just_dna_enricher' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False", out.stdout


# ── VRS coverage ──────────────────────────────────────────────────────────────


def test_vrs_coverage_projects_the_enrichers_own_counters() -> None:
    """Since enricher 0.5.1 (RM40) the counting is upstream's and this only renders it.

    That is the whole value of the RM: through 0.11 the registry counted slots itself over
    `EnrichmentResult.rows`, because `enrich()` computed a `MintResult` and dropped it — so a dry run
    could disagree with the manifest a publish would stamp from the same data. What is left to test
    is that nothing is re-derived here, including `complete`, which is the enricher's derivation
    rather than a comparison repeated on this side.
    """

    @dataclass
    class _Mint:  # the shape of `just_dna_enricher.vrs.MintResult`
        alleles: int
        identified: int
        complete: bool
        unmintable_reasons: dict[str, int]

    coverage = vrs_coverage(
        _Mint(alleles=4, identified=2, complete=False, unmintable_reasons={"indel: needs seq": 2})
    )
    assert (coverage.alleles, coverage.identified, coverage.complete) == (4, 2, False)
    # The actionable half, previously reachable only as a log line.
    assert coverage.unmintable_reasons == {"indel: needs seq": 2}


def test_vrs_coverage_distinguishes_not_minted_from_a_coverage_of_zero() -> None:
    """`None` in means the pass did not run, which is not the same as running and naming nothing.

    Both render `alleles == 0`, so the difference has to live in `complete`: never `True` (that would
    claim a vacuous success), and never `False` for a table that was never asked about.
    """
    assert vrs_coverage(None).complete is None
    assert vrs_coverage(None).unmintable_reasons == {}


def test_a_dry_run_reports_the_same_coverage_the_manifest_will_carry(tmp_path: Path) -> None:
    """The guarantee RM40 buys, end to end rather than by construction.

    `manifest.compilation.vrs_alleles` / `vrs_alleles_identified` are stamped by the *compiler* from
    the resolution table; `/check` reports the *enricher's* counters for the same table. Two
    independent producers of one number, which is exactly the shape that drifts — so this publishes
    and dry-runs the same spec and demands they agree.
    """
    from fastapi.testclient import TestClient

    from just_dna_registry.api.app import create_app

    empty = tmp_path / "no-cache"
    client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "m.db", local_storage_dir=tmp_path / "a",
                ensembl_cache=empty, clinvar_cache=empty, constraint_cache=empty,
            )
        )
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    auth = {"Authorization": "Bearer mk_live_testkey"}

    yaml = (
        'schema_version: "1.0"\nmodule:\n  name: coronary\n  title: C\n  description: d\n'
        "  report_title: C\ngenome_build: GRCh38\n"
    )
    variants = (
        "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
        "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
    )
    studies = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"
    parts = [
        ("files", ("module_spec.yaml", yaml.encode(), "text/yaml")),
        ("files", ("variants.csv", variants.encode(), "text/csv")),
        ("files", ("studies.csv", studies.encode(), "text/csv")),
    ]

    check = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True}, files=parts, headers=auth,
    )
    assert check.status_code == 200, check.text
    reported = check.json()["enrichment"]["vrs"]

    published = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"}, files=parts, headers=auth,
    )
    assert published.status_code == 201, published.text
    compilation = published.json()["compilation"]

    assert reported["alleles"] == compilation["vrs_alleles"]
    assert reported["identified"] == compilation["vrs_alleles_identified"]


# ── Cache resolution ──────────────────────────────────────────────────────────


def test_configured_caches_passes_the_setting_through_unresolved(tmp_path: Path) -> None:
    """What the enricher is handed must be the configured path, even when nothing is there.

    Resolving first and passing the result would send `None` for an empty cache, and `None` tells the
    enricher to go looking — which is exactly the ambient discovery the setting exists to forbid.
    """
    empty = tmp_path / "not-provisioned"
    settings = Settings(ensembl_cache=empty, clinvar_cache=empty, constraint_cache=empty)
    assert configured_caches(settings)["ensembl"] == empty
    # ...while *resolution* correctly reports there is nothing usable there.
    assert available_references(settings)["ensembl"] is None


def test_available_references_ignores_ambient_state_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit setting must win over the environment, or CI and production disagree."""
    monkeypatch.setenv("JUST_DNA_ENSEMBL_CACHE", "/somewhere/else/entirely")
    monkeypatch.setenv("JUST_DNA_PIPELINES_CACHE_DIR", "/another/place")
    settings = Settings(ensembl_cache=tmp_path / "empty")
    assert available_references(settings)["ensembl"] is None


# ── A check that did not run ──────────────────────────────────────────────────


def test_a_check_that_ran_adds_no_note() -> None:
    """`None` means it genuinely ran, and a clean pass must stay silent or the note means nothing."""
    assert clin_sig_skip_note(None) is None


def test_each_skip_reason_reaches_whoever_can_act_on_it() -> None:
    """The two machine tokens name a *deployment* state, so they are translated, not passed through.

    A publisher reading `no_snapshot` cannot act on the word; `warm-caches` is the operator's move and
    the env var is the operator's switch. Both lines also have to deny the reading they exist to
    prevent — that an empty conflict list was a pass.
    """
    disabled = clin_sig_skip_note("not_requested")
    assert "REGISTRY_ENRICH_VERIFY_CLINSIG=false" in disabled
    assert "not a clean bill of health" in disabled

    absent = clin_sig_skip_note("no_snapshot")
    assert "warm-caches" in absent
    assert "unchecked, not clean" in absent


def test_the_tautology_reason_is_passed_through_as_written() -> None:
    """The third reason is prose from the enricher, and it names the pins that matched.

    Translating it would drop exactly the part a publisher needs in order to agree with the skip, so
    this side only prefixes it.
    """
    reason = (
        "this module declares it was drafted from the very snapshot the check reads "
        "(release 2026-07-01), so every authored clin_sig is a copy of the value it would be "
        "compared against"
    )
    note = clin_sig_skip_note(reason)
    assert note == f"clin_sig cross-check did not run: {reason}"


def test_the_publish_path_never_renders_conflicts_without_the_skip() -> None:
    """The prose the publish path emits carries the skip beside the conflicts it qualifies.

    `_render_notes` feeds a failed publish's `warnings`, where an unqualified empty conflict list is
    the same misinformation the report field fixes.
    """

    @dataclass
    class _Result:  # the fields of `just_dna_enricher.enrich.EnrichmentResult` this reads
        ref_mismatches: list
        clin_sig_conflicts: list
        clin_sig_not_checked: str | None
        stale_rsids: list
        par_twins_dropped: list

    notes = _render_notes(
        _Result([], [], "no_snapshot", [], [])
    )
    assert any("clin_sig cross-check did not run" in n for n in notes)
    # ...and a check that ran contributes nothing, so the absence of a line is itself the signal.
    assert _render_notes(_Result([], [], None, [], [])) == []


# ── Actionability of the failure ──────────────────────────────────────────────


def test_the_unresolved_hint_names_both_remedies() -> None:
    """A strict refusal has two possible fixers — the author and the operator — and the message has
    to reach whichever one is reading it."""
    outcome = EnrichOutcome(ran=True, offline=True, unresolved=["rs1", "rs2"])
    hint = unresolved_hint(outcome, Settings())
    assert "2 variant(s) unresolved" in hint
    assert "warm-caches" in hint  # the operator's move
    assert "variants.csv" in hint  # the author's move


def test_the_hint_explains_a_skipped_enrichment_differently() -> None:
    outcome = EnrichOutcome(ran=False, skipped_reason="enrichment disabled")
    assert "enrichment disabled" in unresolved_hint(outcome, Settings())


# ── The concurrency gate ──────────────────────────────────────────────────────


def test_the_gate_rejects_rather_than_queues() -> None:
    """Queueing behind a multi-minute paced run converts a fast 503 into a slow timeout."""
    gate = EnrichmentGate(1)
    assert gate.try_acquire() is True
    assert gate.try_acquire() is False
    assert gate.active == 1
    gate.release()
    assert gate.active == 0
    assert gate.try_acquire() is True


def test_the_gate_floors_at_one() -> None:
    """A misconfigured 0 must not disable enrichment silently."""
    assert EnrichmentGate(0).try_acquire() is True


# ── declared_use: the third axis ──────────────────────────────────────────────


def test_declared_use_is_validated_at_config_time() -> None:
    """A typo'd deployment value must fail at boot, not silently read as `unstated` and quietly skip
    every PGx source for the life of the deployment."""
    import pytest as _pytest

    assert Settings(declared_use="non_commercial").declared_use == "non_commercial"
    with _pytest.raises(ValueError, match="declared_use must be one of"):
        Settings(declared_use="noncommercial")  # the hyphenless CLI spelling, which is not the vocab


def test_the_pgx_sources_all_forbid_sale() -> None:
    """The premise the gating rests on. If an upstream ever relicensed, `unstated` would start
    fetching it and this test is where we would find out."""
    from just_dna_enricher.licensing import CPIC_TERMS, PHARMVAR_TERMS, check_declared_use

    for terms in (CPIC_TERMS, PHARMVAR_TERMS):
        assert terms.commercial_use is False
        assert check_declared_use(terms, "unstated") is not None  # skipped, with a reason
        assert check_declared_use(terms, "non_commercial") is None  # proceed


def test_a_missing_snapshot_is_not_an_unavailability(tmp_path: Path) -> None:
    """The corrected contract. A snapshot is what makes *offline* resolution possible; an online run
    reaches live Ensembl without one. Raising here would refuse the configuration that works."""
    settings = Settings(
        ensembl_cache=tmp_path / "empty",
        clinvar_cache=tmp_path / "empty",
        constraint_cache=tmp_path / "empty",
    )
    assert all(v is None for v in available_references(settings).values())
    assert enricher_available()  # ...and the tier itself is present, which is what a 503 would mean


# ── The shared client bundle ──────────────────────────────────────────────────


def test_the_shared_bundle_actually_holds_clients() -> None:
    """The whole point of sharing is the pacing state, and an empty bundle shares none of it.

    `LookupClients()` builds nothing: its "lazily built" is `lookup.py` doing `clients.x or X()` and
    closing what it made, not the dataclass filling itself. So the bundle this service handed to
    every pass was six `None`s — each pass built its own client with a fresh `PacingGate`, N
    concurrent runs egressed at N× the intended rate against limits enforced by IP that gnomAD sells
    no key to raise, and `close_lookup_clients` closed nothing. The gate defaulting to 1 is what
    makes one shared bundle *safe*; it is not what makes it exist.
    """
    from just_dna_registry.services.enrich import close_lookup_clients, shared_lookup_clients

    close_lookup_clients()  # this is process-global; start from a known state
    try:
        bundle = shared_lookup_clients()
        assert bundle is shared_lookup_clients(), "one bundle per process, or the pacing is per call"
        members = {
            name: getattr(bundle, name)
            for name in ("gnomad", "eutils", "europepmc", "crossref", "ontology", "ensembl")
        }
        assert all(client is not None for client in members.values()), members
        # Every paced client carries the state worth sharing. Ensembl deliberately has no gate: it
        # is the last link after cache and snapshot, so its volume stays low.
        assert all(
            getattr(client, "gate", None) is not None
            for name, client in members.items()
            if name != "ensembl"
        ), members
    finally:
        close_lookup_clients()


# ── Which snapshots gate what ─────────────────────────────────────────────────


def test_the_boot_gate_covers_only_what_a_publish_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`enrich_require_cache` may only refuse to start over a snapshot this service actually reads.

    `constraint` sat in `RESOLUTION_REFERENCES` while no registry pass consulted it — the
    gene-metrics pass writes an authored sidecar and nothing here runs it — so an operator who asked
    for the strict boot gate got `sys.exit(1)` over a file that would never have been opened, and
    `/check` blamed it for coordinates it had nothing to do with. Keep it out of the set that gates,
    and keep it in the set `warm-caches` reports.
    """
    from just_dna_registry.services import enrich as enrich_service
    from just_dna_registry.startup import validate_enrichment_caches

    provisioned = tmp_path / "snapshot"
    resolution_only = {name: None for name in REFERENCE_NAMES}
    resolution_only["ensembl"] = resolution_only["clinvar"] = provisioned
    monkeypatch.setattr(enrich_service, "available_references", lambda _s: resolution_only)

    # Ensembl and ClinVar are there; constraint and the three PGx caches are not. On the old
    # grouping this raised `SystemExit(1)` and the server never came up.
    validate_enrichment_caches(
        Settings(enrich_enabled=True, enrich_offline=True, enrich_require_cache=True)
    )

    assert "constraint" not in RESOLUTION_REFERENCES
    assert "constraint" in REFERENCE_NAMES  # still reportable, still pullable
    assert "constraint" in PULLABLE_REFERENCES
