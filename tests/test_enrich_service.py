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
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from just_dna_registry.config import Settings
from just_dna_registry.models.api import SpecStats
from just_dna_registry.services.enrich import (
    ENRICHMENT_SUBJECT_TABLES,
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
    enrichment_subject_count,
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


# ── What the cost guard is actually counting ──────────────────────────────────


def test_a_pgx_module_is_not_zero_subjects(tmp_path: Path) -> None:
    """The bound has to count what `enrich()` asks about, not what `variants.csv` holds.

    A PGx module has no `variants.csv` at all, so `variant_count` is `0` while the enricher collects a
    subject per PGx row — the one module family whose row count the old guard could not see. Measured
    against the format's own reference example rather than asserted: the numbers below come from the
    compiler's `validate_spec`, so a change in what it reports fails here.
    """
    from just_dna_compiler.compiler import validate_spec

    example = Path("/data/sources/just-dna-format/reference_examples/pgx_slco1b1_simvastatin")
    if not example.is_dir():
        pytest.skip("just-dna-format reference examples not checked out beside this repo")

    raw = validate_spec(example).stats or {}
    stats = SpecStats.model_validate(
        {k: v for k, v in raw.items() if k in SpecStats.model_fields}
    )
    assert stats.variant_count == 0             # the old guard's entire input
    assert stats.table_rows["pharm_variants.csv"] == 9
    assert enrichment_subject_count(stats) == 9  # what the enricher would actually ask about


def test_every_subject_table_is_counted() -> None:
    """`variants.csv` plus each table the enricher collects from, and no double-count of the core."""
    stats = SpecStats.model_validate(
        {"variant_count": 5, "table_rows": {csv: 2 for csv in ENRICHMENT_SUBJECT_TABLES}}
    )
    assert enrichment_subject_count(stats) == 5 + 2 * len(ENRICHMENT_SUBJECT_TABLES)
    # `heteroplasmy.csv` earns its place in the tuple: enricher 0.5.3 added it to `_collect_subjects`,
    # and before that a heteroplasmy module both enriched to nothing and counted as nothing.
    assert "heteroplasmy.csv" in ENRICHMENT_SUBJECT_TABLES
    # A table the enricher never asks about must not inflate the bound into a spurious 422.
    assert enrichment_subject_count(
        SpecStats.model_validate({"variant_count": 1, "table_rows": {"diplotypes.csv": 9_000}})
    ) == 1


# ── A check that did not run ──────────────────────────────────────────────────


@dataclass
class _Findings:
    """The fields of `just_dna_enricher.enrich.EnrichmentResult` that `_render_notes` reads.

    Mirrored rather than constructed because the real class is built by a network run: what is under test
    is the *rendering* of a set of findings, and every finding shape here is one the enricher can
    genuinely return. A field the enricher adds and this class lacks fails loudly at the attribute
    access, which is the direction that matters — `_render_notes` reads unguarded on purpose, so that a
    new finding cannot be silently dropped from a publisher's warnings.
    """

    ref_mismatches: list = field(default_factory=list)
    clin_sig_conflicts: list = field(default_factory=list)
    clin_sig_not_checked: str | None = None
    stale_rsids: list = field(default_factory=list)
    par_twins_dropped: list = field(default_factory=list)
    unreachable_rsids: list = field(default_factory=list)


def _findings(**over) -> _Findings:
    return _Findings(**over)


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

    notes = _render_notes(_findings(clin_sig_not_checked="no_snapshot"))
    assert any("clin_sig cross-check did not run" in n for n in notes)
    # ...and a check that ran contributes nothing, so the absence of a line is itself the signal.
    assert _render_notes(_findings()) == []


def test_the_publish_path_says_when_an_rsid_was_never_asked_about() -> None:
    """S20, in the prose a failed publish carries.

    `unresolved` counts keys with no position and is silent about why, so on its own it reads as "no
    such locus" — the one reading a failed request cannot support. This line exists so a publisher
    facing a strict refusal can tell whether to author coordinates or simply try again.
    """
    notes = _render_notes(_findings(unreachable_rsids=["rs6567160", "rs13010010"]))
    assert len(notes) == 1
    assert "rs6567160" in notes[0]
    assert "unchecked rather than empty" in notes[0]
    assert "Re-run" in notes[0]


# ── Actionability of the failure ──────────────────────────────────────────────


def test_the_unresolved_hint_names_both_remedies() -> None:
    """A strict refusal has two possible fixers — the author and the operator — and the message has
    to reach whichever one is reading it."""
    outcome = EnrichOutcome(ran=True, offline=True, unresolved=["rs1", "rs2"])
    hint = unresolved_hint(outcome, Settings())
    assert "2 variant(s) unresolved" in hint
    assert "warm-caches" in hint  # the operator's move
    assert "variants.csv" in hint  # the author's move


def test_the_hint_does_not_send_the_author_after_an_upstream_failure() -> None:
    """The third case, and the reason S20's distinction had to reach this function.

    All three of the usual remedies — provision a snapshot, allow egress, author coordinates — assume
    somebody's configuration or spec is at fault. When Ensembl was asked and never answered, none of
    them applies and every one of them costs the publisher work on a variant that is perfectly
    findable. So the advice for this case is only: try again.
    """
    outcome = EnrichOutcome(
        ran=True, offline=False, unresolved=["rs6567160"], unreachable_rsids=["rs6567160"]
    )
    hint = unresolved_hint(outcome, Settings())
    assert "rs6567160" in hint
    assert "Re-publish" in hint
    # The remedies that would be wrong here are absent, not merely de-emphasised.
    assert "warm-caches" not in hint and "variants.csv" not in hint


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
    # Every cache the resolver ladder can find, not only the three a strict publish needs: the PGx
    # snapshots were left unset here, so `available_references` resolved them through platformdirs
    # and the assertion quietly described whether the developer had run `warm-caches --pgx`.
    empty = tmp_path / "empty"
    settings = Settings(
        ensembl_cache=empty,
        clinvar_cache=empty,
        constraint_cache=empty,
        cpic_cache=empty,
        pharmvar_cache=empty,
        clinpgx_cache=empty,
        acmg_snapshot_dir=empty,
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


# ── An upstream that could not be reached ──────────────────────────────────────


def test_a_clingen_fetch_failure_is_unreachable_and_a_bad_local_table_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ClinGenError` covers two opposite histories, and the cause chain is what separates them.

    `fetch_curation_list` raises `from` the transport error; an unparseable local `gene_metrics.csv`
    is raised on its own. Only the first means ClinGen was asked and did not answer, so only the first
    may claim `unreachable` — the alternative was matching the sentence, and a warning text is a
    surface upstream is free to reword.
    """
    import httpx
    import just_dna_enricher.clingen as clingen

    from just_dna_registry.models.api import PgxCheck
    from just_dna_registry.services.enrich import _pgx_leg_clingen

    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "module_spec.yaml").write_text(
        'schema_version: "1.0"\nmodule:\n  name: m\n  version: 1\ngenome_build: GRCh38\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        clingen.httpx, "get", lambda *_a, **_k: (_ for _ in ()).throw(httpx.ConnectError("refused"))
    )
    fetched = PgxCheck()
    _pgx_leg_clingen(spec, fetched, set(), offline=False, declared_use="non_commercial")
    assert fetched.unreachable == ["clingen"]
    assert any("Unchecked, not no-curation-found" in w for w in fetched.warnings)

    def local_table_is_bad(*_a, **_k):
        raise clingen.ClinGenError("existing gene_metrics.csv is invalid: row 2 has no gene")

    monkeypatch.setattr(clingen, "enrich_dosage_sensitivity", local_table_is_bad)
    authored = PgxCheck()
    _pgx_leg_clingen(spec, authored, set(), offline=False, declared_use="non_commercial")
    assert authored.unreachable == []  # nothing was asked, and nothing upstream is at fault
    assert any("gene_metrics.csv is invalid" in w for w in authored.warnings)


def test_every_pass_that_can_degrade_can_say_it_reached_nothing() -> None:
    """Enumerated from `EnrichmentReport`, not from a list in this file.

    The pass adapters keep growing (five today, from two in 0.11), and each new one arrives with the
    same trap: an empty finding list from a run that reached nothing renders identically to a clean
    one. So the guard walks the report's own fields — a sixth pass added without the field fails here
    rather than shipping a clean-looking verdict nobody established.
    """
    import typing

    from pydantic import BaseModel

    from just_dna_registry.models.api import EnrichmentReport

    checks = {}
    for name, info in EnrichmentReport.model_fields.items():
        args = typing.get_args(info.annotation)
        if type(None) not in args:  # `Optional[XCheck]` — an *optional pass*, not a finding list
            continue
        for arg in args:
            if isinstance(arg, type) and issubclass(arg, BaseModel) and arg.__name__.endswith("Check"):
                checks[name] = arg

    assert set(checks) == {"frequencies", "literature", "identifiers", "acmg", "pgx"}
    for name, model in checks.items():
        assert "unreachable" in model.model_fields, f"{name} cannot say it reached nothing"
        assert "warnings" in model.model_fields, f"{name} cannot say why"


def test_no_adapter_catches_an_unavailability_subclass_with_its_parent_first() -> None:
    """Order matters here in a way that fails *silently*, so it is checked structurally.

    Enricher 0.6.2 (RM101, our S37) made "the source could not be reached" a **subclass** of each
    pass's own error type — `FrequencyUnavailable(FrequencyEnrichmentError)` and five siblings. That
    is what keeps `except <Pass>Error` catching everything it used to, and it is also the trap: a
    parent arm written above the subclass arm swallows the outage and reports it as a structural note
    with no `unreachable`. Nothing raises, nothing 500s, and the check comes back looking clean.

    So this walks the AST of every handler in `services/enrich.py` rather than driving a request per
    pass: an adapter added later, for a pass that grows an unavailability subclass later, is covered
    without anybody remembering to add a case. The behavioural half is in `test_preflight_api.py`,
    which drives the real passes through real client failures.

    **A parent and its subclass in one `except (A, B)` tuple is not a finding.** That form is redundant
    rather than dead — every instance is still caught, and the arm still runs — so flagging it would
    make this guard cry wolf on working code, which is how a guard gets deleted. Upstream adopted this
    walk for their own tree (S38) and made the same carve-out; `_shadowed_handlers` is shared by the
    self-test below so the two cannot drift.
    """
    from just_dna_registry.services import enrich as enrich_service

    source = Path(enrich_service.__file__).read_text(encoding="utf-8")
    assert _shadowed_handlers(source) == []


def test_the_shadowed_handler_walk_can_actually_fail() -> None:
    """A zero from the guard above is worth nothing unless the walk is able to report a one.

    Three shapes, and the middle one is the only defect. The third is the trap in the *guard* rather
    than in the code it checks: `except (Parent, Child)` catches everything it means to, so calling it
    a finding would make the guard wrong about working code.
    """
    parent_first = """
try:
    enrich_frequencies(spec)
except FrequencyEnrichmentError:
    pass
except FrequencyUnavailable:
    pass
"""
    subclass_first = """
try:
    enrich_frequencies(spec)
except FrequencyUnavailable:
    pass
except FrequencyEnrichmentError:
    pass
"""
    one_tuple = """
try:
    enrich_frequencies(spec)
except (FrequencyEnrichmentError, FrequencyUnavailable):
    pass
"""
    imports = "from just_dna_enricher.frequencies import FrequencyEnrichmentError, FrequencyUnavailable\n"

    assert len(_shadowed_handlers(imports + parent_first)) == 1
    assert _shadowed_handlers(imports + subclass_first) == []
    assert _shadowed_handlers(imports + one_tuple) == []


def _shadowed_handlers(source: str) -> list[str]:
    """`except` clauses in `source` that an earlier clause in the same `try` already catches.

    Resolves bare names only, against the `just_dna_enricher` modules `source` itself imports — so a
    new pass's module is covered without editing a list, and a dotted `except httpx.HTTPError` is
    skipped rather than half-resolved. Same limitation upstream's copy documents.
    """
    import ast
    import importlib

    tree = ast.parse(source)
    modules = [
        importlib.import_module(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("just_dna_enricher.")
    ]
    assert modules, "no enricher imports found — the walk would vacuously pass"

    def resolve(node: ast.expr) -> list[type]:
        names = node.elts if isinstance(node, ast.Tuple) else [node]
        found = []
        for n in names:
            if not isinstance(n, ast.Name):
                continue
            for module in modules:
                cls = getattr(module, n.id, None)
                if isinstance(cls, type) and issubclass(cls, BaseException):
                    found.append(cls)
                    break
        return found

    offenders = []
    for block in ast.walk(tree):
        if not isinstance(block, ast.Try):
            continue
        seen: list[type] = []
        for handler in block.handlers:
            if handler.type is None:
                continue
            # Per clause, not per name: a parent and its child inside one tuple are redundant rather
            # than dead, so only what an *earlier arm* shadows counts.
            caught = resolve(handler.type)
            for cls in caught:
                shadowing = [e for e in seen if issubclass(cls, e)]
                if shadowing:
                    offenders.append(
                        f"line {handler.lineno}: `except {cls.__name__}` is unreachable — "
                        f"{shadowing[0].__name__} in an earlier arm already catches its subclasses"
                    )
            seen.extend(caught)
    return offenders
