"""
Server-side enrichment: the one place `just-dna-enricher` is wired.

`just-dna-format` and `just-dna-compiler` never fetch (CONSTITUTION Principle 2). The enricher is
the only tier permitted to, and the division of labour is a *file*: the enricher writes
`resolution.csv` (rsid → coordinate, VRS allele ids, reference-allele check) and the compiler reads
it. A service that runs `enrich()` and then `compile_module()` is conformant and is the intended
deployment shape; what is forbidden is the compile path importing the enricher — which is exactly
what `compile_module(ensembl_cache=…)`'s deprecated shim does, and why the registry does not use it.

Two callers, one wiring:

* `enrich_spec` — the publish path. Best-effort, offline by default, and its failures become
  `PublishError`s.
* `dry_run` (added with the `/check` endpoint) — the pre-flight. Reports rather than refuses.

The import of `just_dna_enricher` is deliberately **lazy and guarded**, inside the functions. That
is not defensive style, it is the mechanism: a module-level import here would be transitively
reachable from `services/publish.py`, and "the compile path never imports the enricher" would stop
being checkable. `tests/test_enrich_service.py` asserts it.
"""

import asyncio
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import httpx
from just_dna_compiler.compiler import content_signature, validate_spec
from just_dna_format.normalize import IDENTITY_AUTHORITY_KEYS

from just_dna_registry.config import Settings
from just_dna_registry.models.api import (
    AcmgCheck,
    CheckReport,
    ClinSigConflictEntry,
    EnrichmentReport,
    FrequencyCheck,
    FunctionConflictEntry,
    IdentifierCheck,
    LiteratureCheck,
    PgxCheck,
    RefMismatchEntry,
    SpecStats,
    StaleRsidEntry,
    ValidationReport,
    VersionRef,
    VrsCoverage,
)

logger = logging.getLogger("registry.enrich")

#: Snapshots that decide whether a **publish** works. Absent and offline, an rsID-authored module
#: cannot be placed and a strict publish fails — which is why `startup` warns about these at boot.
#:
#: Exactly the two the resolution chain reads. `constraint` sat here until it was noticed that no
#: registry pass reads it: the gene-metrics pass writes an authored sidecar (`gene_metrics.csv`) and
#: this service never runs it, so a missing constraint snapshot cannot cost a publish anything. Under
#: `enrich_require_cache` its presence here made the server *exit at boot* over a file nothing would
#: have opened, and it put "constraint" in the `/check` note that says nothing could be resolved —
#: the same false attribution the PGx set is kept out for.
RESOLUTION_REFERENCES: tuple[str, ...] = ("ensembl", "clinvar")

#: gnomAD gene constraint. Pullable and reported by `registry warm-caches` — an operator may well
#: want it on the box, and a future gene-metrics pass would read it — but nothing here consults it
#: today, so it gates neither a publish nor a check and never appears in a finding about a module.
METRICS_REFERENCES: tuple[str, ...] = ("constraint",)

#: The licence-gated PGx snapshots (enricher 0.5.1 / RM38). Kept apart from the three above because
#: they gate a *different* thing — only the opt-in `?pgx=` check reads them — and conflating the two
#: would greet every deployment that never asks for that check with three boot warnings about caches
#: it does not need. They matter for a **hosted** registry specifically: without them the check has
#: only two options, fetch a source that forbids sale live per request on the operator's own
#: acceptance and personal PharmVar key, or skip. Both published rate figures are per IP, so a server
#: multiplies its callers onto one allowance rather than each getting their own.
PGX_REFERENCES: tuple[str, ...] = ("cpic", "pharmvar", "clinpgx")

#: Every snapshot this deployment can hold. Keys are the names `registry warm-caches` reports and
#: `configured_caches` / `available_references` are keyed by.
REFERENCE_NAMES: tuple[str, ...] = (
    RESOLUTION_REFERENCES + METRICS_REFERENCES + PGX_REFERENCES
)

#: The two the registry can *download*. PharmVar is absent by upstream design rather than oversight:
#: its bulk data is taken under a key its terms make personal and non-transferable, so nothing is
#: published to pull and there is no `ensure_pharmvar_snapshot` to call. An operator builds it.
PULLABLE_REFERENCES: tuple[str, ...] = ("ensembl", "clinvar", "constraint", "cpic", "clinpgx")

#: Pulling one of these is *taking* licence-gated data, so `warm-caches` applies `declared_use` to it
#: — the same gate the enricher's own `cache pull` applies, for the same reason: under a data-usage
#: policy the terms are accepted at acquisition.
GATED_REFERENCES: tuple[str, ...] = ("cpic", "clinpgx")


class EnrichmentUnavailable(RuntimeError):
    """The network tier cannot run at all on this deployment.

    Distinct from "enrichment failed": nothing was attempted, because there is nothing to attempt it
    with. The router turns this into `503` — deliberately with no `Retry-After`, since retrying does
    not help until an operator changes the deployment.

    Note what this is **not**: a missing reference snapshot. An earlier cut of this raised here when
    `available_references` came back empty on an online run, which was exactly backwards — a snapshot
    is what makes *offline* resolution possible, and an online run falls through to live Ensembl and
    resolves perfectly well without one. That 503 refused the one configuration that works. A missing
    snapshot now degrades per-pass, with a reason in the report, the way every other finding does.
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            "the enrichment tier is unavailable: " + "; ".join(missing)
        )


@dataclass(frozen=True)
class EnrichOutcome:
    """What one enrichment pass did, in terms the publish path can act on.

    Note what is *not* an error here: unresolved variants. The enricher leaving a variant without a
    position is information, not a refusal — the refusal, if there is one, comes from the compiler's
    strict gate, which names the offenders in the compiler's own words. This carries the context
    that makes that refusal actionable ("offline, against this cache, N left over").
    """

    ran: bool
    mode: str = "best_effort"
    offline: bool = True
    skipped_reason: Optional[str] = None
    fully_resolved: bool = True
    unresolved: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    #: Ref mismatches, clin-sig conflicts, stale rsIDs and PAR drops, pre-rendered one per line.
    #: All are reported and never repaired, so they travel as prose rather than as a verdict.
    notes: list[str] = field(default_factory=list)
    #: The enricher's own `MintResult` (0.5.1 / RM40), or `None` when minting did not run — which is
    #: not the same as a coverage of zero, and the reason this is not two integers.
    vrs: Any = None


_shared_clients: Any = None
_clients_lock = threading.Lock()


def shared_lookup_clients() -> Any:
    """The process's one `LookupClients` bundle, built on first use.

    Shared rather than per-request because the pacing that keeps us inside gnomAD's and NCBI's stated
    limits lives *on the client object* (`PacingGate`), not in this process globally. N concurrent
    runs holding N bundles would each wait their own 6 seconds and collectively egress at N× the
    intended rate. Those limits are enforced by IP and gnomAD sells no key to raise them, so the
    consequence is the whole deployment being throttled — not the caller who overspent.

    That sharing is only safe because `PacingGate` has no lock and `enrich_max_concurrency` defaults
    to 1. Raising the concurrency races the gate; the setting says so.

    **Every member is constructed here, and `LookupClients()` on its own is not a bundle.** Its
    docstring says the clients are "optional and lazily built", which is true of `lookup.py` — each
    of its functions does `client = clients.x or XClient()` and closes what it made. Nothing builds
    them on the dataclass. So an empty `LookupClients()` handed to the passes below is six `None`s:
    every `resolver=`, `gnomad_client=`, `client=`, `eutils=` argument arrived empty, each pass built
    its own client with a fresh `PacingGate`, and the process-wide pacing this function exists for
    never happened — `close_lookup_clients` closed nothing either. Constructed eagerly rather than
    per attribute because the bundle is built once per process, on the first online run, and only
    then: an offline caller never asks for it.
    """
    global _shared_clients
    if _shared_clients is None:
        with _clients_lock:
            if _shared_clients is None:
                from just_dna_enricher.ensembl import EnsemblResolver
                from just_dna_enricher.eutils import EutilsClient
                from just_dna_enricher.gnomad import GnomadClient
                from just_dna_enricher.identifiers import OntologyClient
                from just_dna_enricher.literature import CrossrefClient, EuropePmcClient
                from just_dna_enricher.lookup import LookupClients

                # `EutilsClient` reads `NCBI_API_KEY` at construction to pick its interval (3/s
                # without, 10/s with), which is why `export_enricher_credentials` runs at boot and
                # this is built on demand rather than at import.
                _shared_clients = LookupClients(
                    gnomad=GnomadClient(),
                    eutils=EutilsClient(),
                    europepmc=EuropePmcClient(),
                    crossref=CrossrefClient(),
                    ontology=OntologyClient(),
                    ensembl=EnsemblResolver(),
                )
    return _shared_clients


def close_lookup_clients() -> None:
    """Close and drop the shared bundle (application shutdown)."""
    global _shared_clients
    with _clients_lock:
        if _shared_clients is not None:
            _shared_clients.close()
            _shared_clients = None


def enricher_available() -> bool:
    """Whether the network tier is installed (it ships in the `server` extra, not the base install)."""
    try:
        import just_dna_enricher  # noqa: F401
    except ImportError:
        return False
    return True


def configured_caches(settings: Settings) -> dict[str, Optional[Path]]:
    """The cache paths to hand the enricher — **as configured**, not as resolved.

    The distinction is load-bearing and cost a bug. `enrich()` runs the resolver ladder itself, and
    that ladder reads `None` as *"find one for me"*: explicit argument → `$JUST_DNA_ENSEMBL_CACHE` →
    `$JUST_DNA_PIPELINES_CACHE_DIR` → a platformdirs default. So passing the *resolved* value through
    inverts the intent — a configured-but-empty cache resolves to `None`, and `None` then licenses
    the very ambient discovery the explicit setting existed to prevent. A machine with a stray
    `~/.cache/just-dna-pipelines` would quietly enrich against it while the operator believed the
    deployment was pinned elsewhere.

    Passing the configured path keeps both behaviours honest: set it and discovery cannot happen;
    leave it unset and an existing just-dna-lite cache is reused, which is the documented default.
    """
    return {
        "ensembl": settings.ensembl_cache,
        "clinvar": settings.clinvar_cache,
        "constraint": settings.constraint_cache,
        "cpic": settings.cpic_cache,
        "pharmvar": settings.pharmvar_cache,
        "clinpgx": settings.clinpgx_cache,
    }


def available_references(settings: Settings) -> dict[str, Optional[Path]]:
    """Which reference snapshots this deployment can actually read, without downloading anything.

    Used for *reporting* — the boot check, `registry warm-caches`, and the `503` decision — never to
    build the arguments `enrich()` is called with (see `configured_caches` for why). Resolves through
    the same ladder the enricher would, so what this reports is what a run would find.

    `load_dotenv_file=False` because `config.py` already loaded it — and since enricher 0.5.2 that
    flag no longer suppresses the whole of it: `_cache_dir` now calls `load_env()` itself, which the
    flag does not reach. Harmless here, and it is the *fix* for a bug this caller was structurally
    immune to. Each `resolve_*_reference` receives its `default_*_cache_dir()` as an argument, so the
    default was computed before the ladder's own `load_env()` ran — meaning the first resolve in a
    process read platformdirs and every later one read `.env`. We never saw it because `config.py`
    loads `.env` at import, long before any of this. `override=False` throughout, so a real
    environment variable still wins and the setting we pass still takes precedence over both.

    Never downloads: that is `registry warm-caches`, deliberately not a request-path concern.
    """
    if not enricher_available():
        return {name: None for name in REFERENCE_NAMES}

    from just_dna_enricher.locations import (
        resolve_clinpgx_reference,
        resolve_clinvar_reference,
        resolve_constraint_reference,
        resolve_cpic_reference,
        resolve_ensembl_reference,
        resolve_pharmvar_reference,
    )

    configured = configured_caches(settings)
    resolvers = {
        "ensembl": resolve_ensembl_reference,
        "clinvar": resolve_clinvar_reference,
        "constraint": resolve_constraint_reference,
        "cpic": resolve_cpic_reference,
        "pharmvar": resolve_pharmvar_reference,
        "clinpgx": resolve_clinpgx_reference,
    }
    return {
        name: resolve(configured[name], load_dotenv_file=False)
        for name, resolve in resolvers.items()
    }


def vrs_coverage(mint: Any) -> VrsCoverage:
    """Project the enricher's `MintResult` onto the API model. `None` in → nothing claimed.

    Through 0.11 this counted the slots itself, over `EnrichmentResult.rows`, because `enrich()`
    computed a `MintResult` and dropped it. Enricher 0.5.1 returns it (RM40), so the counting is
    gone — and with it the two rules a re-implementation had to get right and could silently get
    wrong: per **ALT slot** rather than per row, and an *absent* `vrs_id` cell counting as
    `len(alts)` unnamed slots rather than as no slots at all. The second is the dangerous one, since
    getting it wrong reports a table where nothing minted as flawless coverage out of a denominator
    of nothing. Now the numbers are the enricher's, so a dry run cannot disagree with the manifest a
    publish would stamp.

    What arrived with them is `unmintable_reasons` — the actionable half, previously reachable only
    as a log line. "No refget table for build GRCh37" and "needs the reference sequence" are the
    tier's own limits, which no authored edit clears; a publisher shown only a shortfall would go
    looking for a mistake that is not theirs.
    """
    if mint is None:
        return VrsCoverage()
    return VrsCoverage(
        alleles=mint.alleles,
        identified=mint.identified,
        # Derived upstream, not stored twice. Vacuous on an empty table — "complete out of zero"
        # says nothing, so it is `None` rather than `True`.
        complete=mint.complete if mint.alleles else None,
        unmintable_reasons=dict(mint.unmintable_reasons),
    )


#: The CSVs `just_dna_enricher.enrich._collect_subjects` asks about, besides `variants.csv`. Mirrored
#: rather than imported because it is private there; the count below is a *bound*, so this erring on
#: the generous side is the safe direction and a table we miss only under-counts.
#:
#: `heteroplasmy.csv` joined the list in enricher 0.5.3 — it had been left out with the same silence
#: that made the whole family invisible here.
ENRICHMENT_SUBJECT_TABLES: tuple[str, ...] = (
    "pharm_variants.csv",
    "haplotypes.csv",
    "heteroplasmy.csv",
)


def enrichment_subject_count(stats: SpecStats) -> int:
    """How many rows an `enrich()` on this spec would actually ask about.

    Not `variant_count`, which counts `variants.csv` and nothing else. The enricher has collected
    subjects from the PGx tables since 0.5 and from `heteroplasmy.csv` since 0.5.3, so a module with
    no `variants.csv` reports `variant_count == 0` while handing the network tier every row it has —
    measured on the format's own `pgx_slco1b1_simvastatin`: `variant_count` absent, nine subjects.

    That made `enrich_max_variants` a guard the one module family most likely to need it slipped
    straight past. The cap exists because these upstreams throttle by IP and gnomAD sells no key to
    raise the limit, so an overspend throttles the whole deployment rather than the caller who caused
    it — a bound that reads zero for a 7,000-row PGx panel is not a bound.

    An upper bound, deliberately: the enricher de-duplicates subjects by `variant_key`, so a module
    naming one locus across three tables is counted three times here and asked once. Over-counting
    costs a publisher a `422` they can argue with; under-counting costs the deployment its rate limit.
    """
    return stats.variant_count + sum(
        stats.table_rows.get(csv_name, 0) for csv_name in ENRICHMENT_SUBJECT_TABLES
    )


def clin_sig_skip_note(reason: Optional[str]) -> Optional[str]:
    """Turn `EnrichmentResult.clin_sig_not_checked` into a line for a publisher, or `None`.

    Exists because an empty `clin_sig_conflicts` is ambiguous in the one direction that matters:
    "compared everything, nothing disagreed" and "never compared" render identically, and only the
    first is reassuring. Enricher 0.5.2 (S4) supplies the reason; this tier's job is to say it in
    terms of *this deployment*, since a publisher cannot see the server's settings.

    Which is why `not_requested` is reported here and deliberately **not** by the enricher's own CLI.
    There it is the author's own `--no-verify-clinsig` echoed back at them, so it is noise; here it is
    `REGISTRY_ENRICH_VERIFY_CLINSIG=false`, a choice the operator made and the publisher has no way
    to observe. Suppressing it would hand back a silence that reads as a clean check.

    The tautology reason arrives as prose rather than a token, and is passed through as written — it
    names the pins that matched, which is the part a publisher needs in order to agree with it.
    """
    if reason is None:
        return None
    if reason == "not_requested":
        return (
            "clin_sig cross-check did not run: this deployment has it switched off "
            "(REGISTRY_ENRICH_VERIFY_CLINSIG=false), so no authored clin_sig was compared against "
            "ClinVar. An empty conflict list here is not a clean bill of health."
        )
    if reason == "no_snapshot":
        return (
            "clin_sig cross-check did not run: no ClinVar snapshot is provisioned on this "
            "deployment, so no authored clin_sig was compared. Run `registry warm-caches --apply` "
            "to make the check possible. An empty conflict list here means unchecked, not clean."
        )
    return f"clin_sig cross-check did not run: {reason}"


def _render_notes(result: Any) -> list[str]:
    """Flatten an `EnrichmentResult`'s findings into one line each.

    Every one of these is reported-never-repaired by design, so they stay prose. The ref-mismatch
    line names the shift when the enricher established one, because a `+1` shift is almost always a
    wrong `start` rather than a wrong `ref` — the single most expensive authoring mistake in the
    format, and one that passes every offline gate.

    The clin_sig *skip* is here beside the clin_sig *conflicts* on purpose: the two are mutually
    exclusive and a reader of one needs the other, so they are never rendered from separate places.
    """
    notes: list[str] = []
    for mismatch in result.ref_mismatches:
        shift = getattr(mismatch, "shift", None)
        detail = (
            f" — the authored ref matches {shift:+d} base(s) away, so `start` is likely wrong, "
            f"not `ref`"
            if shift
            else ""
        )
        notes.append(
            f"ref mismatch {mismatch.variant_key} at {mismatch.chrom}:{mismatch.start}: "
            f"authored {mismatch.claimed!r}, reference has {mismatch.actual!r}{detail}"
        )
    for conflict in result.clin_sig_conflicts:
        notes.append(
            f"clin_sig conflict {conflict.variant_key}: authored {conflict.authored!r}, "
            f"ClinVar says {conflict.clinvar!r} ({conflict.confidence})"
            + (" — opposed calls" if conflict.opposed else "")
        )
    skipped = clin_sig_skip_note(result.clin_sig_not_checked)
    if skipped:
        notes.append(skipped)
    for status in result.stale_rsids:
        current = f" (now {status.current})" if status.current else ""
        notes.append(f"rsID {status.rsid} is {status.state}{current}")
    for rsid, chrom, start in result.par_twins_dropped:
        notes.append(
            f"pseudoautosomal {rsid} recorded once on X; the {chrom}:{start} spelling was dropped"
        )
    return notes


def enrich_spec(
    spec_dir: Path, settings: Settings, *, action: Optional[Any] = None
) -> EnrichOutcome:
    """Produce `resolution.csv` in `spec_dir`, ahead of the compile. Never raises on findings.

    Synchronous and blocking — it belongs on the same threadpool worker as the compile that follows
    it, which is why the publish router's single `run_in_threadpool` wraps both and this adds none
    of its own.

    Runs `mode="best_effort"` regardless of `compile_strict`, and that is load-bearing rather than
    lenient: `enrich(mode="strict")` raises *before* writing, so a strict failure would leave no
    resolution table at all — nothing to diagnose from, and a re-run that repeats the entire network
    pass. Letting the compiler's strict gate refuse instead keeps the table on disk and produces an
    error that names the variants.

    Raises `PublishError("enrich_failed")` only when the enricher itself refuses (a withdrawn rsID,
    an unreadable CSV) — never for unresolved variants, which ride on the outcome.
    """
    from just_dna_registry.services.publish import PublishError

    if not settings.enrich_enabled:
        return EnrichOutcome(ran=False, skipped_reason="enrichment disabled")

    if not enricher_available():
        logger.warning("enrichment requested but just-dna-enricher is not installed")
        return EnrichOutcome(
            ran=False,
            skipped_reason="just-dna-enricher is not installed (install the `server` extra)",
        )

    from just_dna_enricher.enrich import EnrichmentError, enrich

    caches = configured_caches(settings)
    offline = settings.enrich_offline
    refs = available_references(settings)
    if offline and refs["ensembl"] is None and refs["clinvar"] is None:
        # Not fatal here: a spec that authors its own coordinates needs no resolution at all, and
        # refusing would break those modules for no reason. The strict compile is the gate that
        # knows whether this actually cost anything.
        logger.warning("offline enrichment with no provisioned snapshot — resolution will be empty")

    # The same shared bundle `/check` uses, for the same reason: the outbound pacing lives on the
    # client object, so a publish that built its own would start its interval from zero and egress
    # on top of whatever a concurrent dry run was already spending — against one IP, on a budget
    # gnomAD sells no key to raise. Only constructed online: offline the enricher builds neither a
    # resolver nor a gnomAD client, so there is nothing to share and nothing to pace.
    clients = None if offline else shared_lookup_clients()

    try:
        result = enrich(
            spec_dir,
            mode=settings.enrich_mode,
            offline=offline,
            resolver=clients.ensembl if clients else None,
            gnomad_client=clients.gnomad if clients else None,
            ensembl_cache=caches["ensembl"],
            clinvar_cache=caches["clinvar"],
            use_clinvar=settings.enrich_use_clinvar,
            # Passed as configured, `offline` beside them. `enrich()` already gates both on it —
            # the gnomAD link and the dbSNP currency check are live-only — and an `and not offline`
            # here would only take the decision away from the pass that reports on it: with the
            # setting on and the run offline, the enricher says *why* the rsID check did not run.
            # Silencing that turns "could not be checked" into an indistinguishable "was not asked
            # for", which is the one distinction this tier exists to keep.
            use_gnomad=settings.enrich_use_gnomad,
            download=settings.enrich_download,
            write=True,
            mint_vrs=settings.enrich_mint_vrs,
            verify_ref=settings.enrich_verify_ref,
            verify_clinsig=settings.enrich_verify_clinsig,
            verify_rsids=settings.enrich_verify_rsids,
            keep_par_twin=settings.enrich_keep_par_twin,
        )
    except EnrichmentError as exc:
        # In best-effort the reachable causes are an invalid CSV (which validation should already
        # have caught) and a withdrawn rsID, which is fatal in both modes because dbSNP repudiating
        # the variant means the annotation may describe nothing.
        raise PublishError("enrich_failed", errors=[part.strip() for part in str(exc).split(";")])

    outcome = EnrichOutcome(
        ran=True,
        mode=result.mode,
        offline=offline,
        fully_resolved=result.fully_resolved,
        unresolved=list(result.unresolved),
        sources=list(result.sources),
        notes=_render_notes(result),
        vrs=result.vrs,
    )
    if action is not None:
        action.add_success_fields(
            enriched=True,
            enrich_offline=offline,
            enrich_sources=outcome.sources,
            resolution_rows=len(result.rows),
            unresolved=len(outcome.unresolved),
            vrs=(
                f"{result.vrs.identified}/{result.vrs.alleles}" if result.vrs else "not minted"
            ),
        )
    return outcome


def unresolved_hint(outcome: EnrichOutcome, settings: Settings) -> str:
    """Why the compiler's strict refusal happened, and what to do about it.

    The compiler names *which* variants have no position; it cannot know that the reason was an
    offline enrichment against an unprovisioned cache. This supplies that half, so the 422 is
    actionable by whichever of the two people can act — the publisher (author coordinates) or the
    operator (provision a snapshot, or allow egress).
    """
    if not outcome.ran:
        return (
            f"no resolution table was produced ({outcome.skipped_reason}), so any variant authored "
            f"by rsID alone has no position."
        )
    where = settings.ensembl_cache or "the enricher's default cache location"
    return (
        f"the enricher ran offline={outcome.offline} against {where} and left "
        f"{len(outcome.unresolved)} variant(s) unresolved. Provision a fuller snapshot "
        f"(`registry warm-caches --apply`), allow live lookups "
        f"(REGISTRY_ENRICH_OFFLINE=false), or author chrom/start in variants.csv."
    )


def validation_report(
    spec_dir: Path,
    repo: Any,
    name: str,
    strict: bool,
    *,
    normalized: Optional[list[str]] = None,
) -> ValidationReport:
    """The offline half of a dry run: validate, sign the content, and pre-check dedup.

    Shared by `/validate` (which stops here) and `/check` (which continues into the network tier).

    `normalized` is what the server rewrote before validating. It is reported rather than hidden:
    the point of a dry run is to predict a publish, and a publish that silently quotes your version
    or drops your `namespace:` key is doing something the author should be able to see.
    """
    result = validate_spec(spec_dir, IDENTITY_AUTHORITY_KEYS, strict=strict)

    # Cheap (no reference, no parquet) and the same value publish will gate `409 duplicate_content`
    # on, so a caller can see the rejection coming. `ValueError` when a data CSV will not parse —
    # which the validation findings already explain, so it degrades to `None` rather than 500ing.
    try:
        signature: Optional[str] = content_signature(spec_dir)
    except ValueError:
        signature = None

    published_as = [
        VersionRef(namespace=r["namespace"], name=r["name"], version=r["version"],
                   yanked=bool(r["yanked"]))
        for r in (repo.find_versions_by_content(signature) if signature else [])
    ]
    stats = result.stats or {}
    return ValidationReport(
        valid=result.valid,
        strict=strict,
        errors=list(result.errors),
        warnings=list(result.warnings),
        info=list(normalized or []) + list(result.info),
        stats=SpecStats.model_validate(
            {k: v for k, v in stats.items() if k in SpecStats.model_fields}
        ),
        content_signature=signature,
        name_matches_path=stats.get("module_name") in (None, name),
        published_as=published_as,
    )


def dry_run(
    *,
    settings: Settings,
    repo: Any,
    uploads: Mapping[str, bytes],
    name: str,
    strict: bool,
    offline: bool,
    frequencies: bool = False,
    literature: bool = False,
    identifiers: bool = False,
    acmg: bool = False,
    pgx: bool = False,
    declared_use: str = "unstated",
    gate: Optional["EnrichmentGate"] = None,
) -> CheckReport:
    """The `/check` worker: validate, then (unless the spec is broken) enrich and report.

    Owns the temp spec directory for the whole run, because the enrichment passes read
    `resolution.csv` back off disk between steps — the directory has to outlive `enrich()`, and it
    must not outlive the request.

    Synchronous and blocking; the router hands it to a threadpool worker. It releases `gate` in its
    own `finally` rather than letting the coroutine do it, because a run that exceeds the request
    timeout keeps its worker: `asyncio.wait_for` cancels the await, not the thread. Releasing on the
    caller's side would let a runaway run stop counting against occupancy while it is still spending.

    Never raises on a *finding*. It raises only where no answer exists to give:
    `EnrichmentUnavailable` (nothing provisioned to check against) and `PublishError` (a module too
    large to enrich, or an enricher refusal).
    """
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "spec"
            for rel, data in uploads.items():
                dest = spec_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            return _dry_run_inner(
                settings=settings, repo=repo, spec_dir=spec_dir, name=name, strict=strict,
                offline=offline, frequencies=frequencies, literature=literature,
                identifiers=identifiers, acmg=acmg, pgx=pgx, declared_use=declared_use,
                started=started,
            )
    finally:
        if gate is not None:
            gate.release()


def _dry_run_inner(
    *,
    settings: Settings,
    repo: Any,
    spec_dir: Path,
    name: str,
    strict: bool,
    offline: bool,
    frequencies: bool,
    literature: bool,
    identifiers: bool,
    acmg: bool,
    pgx: bool,
    declared_use: str,
    started: float,
) -> CheckReport:
    from just_dna_registry.services.publish import PublishError, normalize_module_block

    normalized = normalize_module_block(spec_dir)
    validation = validation_report(spec_dir, repo, name, strict, normalized=normalized)

    # The strongest cost guard in the design: a spec that cannot compile is not worth an outbound
    # request, and its findings are already the answer the caller needs.
    if not validation.valid:
        return CheckReport(
            validation=validation,
            skipped_reason="invalid_spec",
            would_publish=False,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )

    if not enricher_available():
        raise EnrichmentUnavailable(
            ["just-dna-enricher is not installed on this server (it ships in the `server` extra)"]
        )

    subject_count = enrichment_subject_count(validation.stats)
    if subject_count > settings.enrich_max_variants:
        # 422 rather than 413: the request body is fine, the amount of *work* it asks for is not.
        raise PublishError(
            "too_many_variants",
            errors=[
                f"{subject_count} enrichment subject(s) exceeds the limit of "
                f"{settings.enrich_max_variants}. Check a smaller module, or ask the operator to "
                f"raise REGISTRY_ENRICH_MAX_VARIANTS."
            ],
        )

    enrichment = _run_enrichment_passes(
        settings=settings, spec_dir=spec_dir, offline=offline,
        caches=configured_caches(settings),
        frequencies=frequencies, literature=literature, identifiers=identifiers, acmg=acmg,
        pgx=pgx, declared_use=declared_use,
    )
    return CheckReport(
        validation=validation,
        enrichment=enrichment,
        would_publish=_would_publish(validation, enrichment),
        elapsed_seconds=round(time.monotonic() - started, 3),
    )


def _would_publish(validation: ValidationReport, enrichment: EnrichmentReport) -> bool:
    """Whether a publish with the server's current settings would succeed.

    Derived here rather than left to the caller so the strict-publish contract lives in one place —
    a CI job branching on this must not have to reimplement the gates and drift from them.

    `unresolved` only blocks under strict, which is the one place `?strict=` reaches the enrichment
    half of the report. Ref mismatches and withdrawn rsIDs block in both modes. Clin-sig conflicts
    and VRS shortfalls never block — nor does `clin_sig_not_checked`, and it must not start to: a
    check the *operator* disabled or has no snapshot for is not a defect in the module, and failing
    a publish over it would make a publisher answer for a deployment they cannot configure.
    """
    return (
        validation.valid
        and validation.name_matches_path
        and not validation.published_as
        and not enrichment.ref_mismatches
        and not any(s.fatal for s in enrichment.stale_rsids)
        and not (validation.strict and enrichment.unresolved)
    )


def _run_enrichment_passes(
    *,
    settings: Settings,
    spec_dir: Path,
    offline: bool,
    caches: dict[str, Optional[Path]],
    frequencies: bool,
    literature: bool,
    identifiers: bool,
    acmg: bool,
    pgx: bool = False,
    declared_use: str = "unstated",
) -> EnrichmentReport:
    """Run `enrich` plus whichever optional passes were asked for, and project the findings."""
    from just_dna_enricher.enrich import EnrichmentError, enrich

    from just_dna_registry.services.publish import PublishError

    # Only reached online: with `offline=True` the enricher constructs neither a resolver nor a
    # gnomAD client, so there is nothing to share and nothing to pace.
    clients = None if offline else shared_lookup_clients()

    try:
        result = enrich(
            spec_dir,
            mode="best_effort",  # see EnrichmentReport.mode — strict raises, and this reports
            offline=offline,
            resolver=clients.ensembl if clients else None,
            gnomad_client=clients.gnomad if clients else None,
            ensembl_cache=caches["ensembl"],
            clinvar_cache=caches["clinvar"],
            use_clinvar=settings.enrich_use_clinvar,
            use_gnomad=settings.enrich_use_gnomad,  # `offline` gates it inside `enrich()`
            download=False,  # never provision a multi-hundred-MB snapshot inside a request
            # Required, not incidental: the optional passes below read `resolution.csv` back off
            # disk. The spec dir is a temp dir that is discarded when the request ends.
            write=True,
            mint_vrs=settings.enrich_mint_vrs,
            verify_ref=settings.enrich_verify_ref,
            verify_clinsig=settings.enrich_verify_clinsig,
            verify_rsids=settings.enrich_verify_rsids,  # ditto — live dbSNP is the only oracle
            keep_par_twin=settings.enrich_keep_par_twin,
        )
    except EnrichmentError as exc:
        raise PublishError(
            "enrichment_failed", errors=[part.strip() for part in str(exc).split(";")]
        )

    # A missing snapshot is a degradation to report, not a refusal. Offline it means nothing can be
    # resolved; online it only means the slower path was taken, since live Ensembl needs no snapshot.
    #
    # Scoped to the resolution snapshots, not every reference this deployment could hold: since
    # enricher 0.5.1 that set also contains the three PGx caches, and they have nothing to do with
    # placing a variant. Listing them here would tell a publisher their coordinates went unresolved
    # for want of a CPIC snapshot. The `?pgx=` check reports its own sources itself.
    present = available_references(settings)
    missing = [name for name in RESOLUTION_REFERENCES if present[name] is None]
    notes: list[str] = []
    if missing and offline:
        notes.append(
            f"no local snapshot for {', '.join(missing)}, and this run is offline — nothing could be "
            f"resolved that the spec did not already carry. Run `registry warm-caches --apply`, or "
            f"re-run without offline to use the live APIs."
        )
    elif missing:
        notes.append(
            f"no local snapshot for {', '.join(missing)}; resolution used the live APIs instead, "
            f"which is slower. `registry warm-caches --apply` makes this offline-capable."
        )
    # Said in prose as well as in the field below, and not folded into the missing-snapshot lines
    # above even when it duplicates one. Those explain why *resolution* degraded; this says a named
    # check produced no verdict, which is a different claim about a different empty list — and the
    # one a reader is most likely to mistake for a pass.
    skipped_clinsig = clin_sig_skip_note(result.clin_sig_not_checked)
    if skipped_clinsig:
        notes.append(skipped_clinsig)

    report = EnrichmentReport(
        mode=result.mode,
        offline=offline,
        unresolved=list(result.unresolved),
        sources=list(result.sources),
        ref_mismatches=[
            RefMismatchEntry(
                variant_key=m.variant_key, chrom=m.chrom, start=m.start, claimed=m.claimed,
                actual=m.actual, genome_build=m.genome_build, shift=getattr(m, "shift", None),
            )
            for m in result.ref_mismatches
        ],
        clin_sig_conflicts=[
            ClinSigConflictEntry(
                variant_key=c.variant_key, chrom=c.chrom, start=c.start, authored=c.authored,
                clinvar=c.clinvar, condition=c.condition, opposed=c.opposed,
                confidence=c.confidence,
            )
            for c in result.clin_sig_conflicts
        ],
        # Structured, beside the prose copy appended to `notes` above: a CI job branching on "was my
        # clin_sig actually checked" needs a token it can compare, not a sentence it has to match.
        clin_sig_not_checked=result.clin_sig_not_checked,
        stale_rsids=[
            StaleRsidEntry(
                rsid=s.rsid, state=s.state, current=s.current, fatal=s.is_fatal
            )
            for s in result.stale_rsids
        ],
        par_twins_dropped=[f"{rsid} {chrom}:{start}" for rsid, chrom, start in result.par_twins_dropped],
        notes=notes,
        vrs=vrs_coverage(result.vrs),
    )

    # Every optional pass is handed the *shared* bundle rather than left to build its own. The
    # pacing that keeps us inside gnomAD's 10-per-60s and NCBI's 3-per-second budgets lives on the
    # client object, so a frequency pass with a fresh `GnomadClient` would start its interval from
    # zero and double the rate the resolution chain above was just paced at — against the same IP,
    # in the same request.
    if frequencies:
        report.frequencies = _frequency_check(spec_dir, offline, clients)
    if literature:
        report.literature = _literature_check(spec_dir, offline, clients)
    if identifiers:
        report.identifiers = _identifiers_check(spec_dir, offline, clients)
    if acmg:
        report.acmg = _acmg_check(spec_dir, settings, offline)
    if pgx:
        report.pgx = _pgx_check(spec_dir, settings, offline, declared_use)
    return report


def _rows_note(rows: list[int], limit: int = 5) -> str:
    """`rows 1, 2, 3 …` — a row list that stays readable when a gene carries hundreds of them."""
    head = ", ".join(str(row) for row in rows[:limit])
    return f"rows {head}" + (f" … ({len(rows)} total)" if len(rows) > limit else "")


def _frequency_check(spec_dir: Path, offline: bool, clients: Any) -> FrequencyCheck:
    """gnomAD allele frequencies for the coordinates `enrich()` just resolved.

    `write=False`: a dry run answers a question, it does not leave a `frequencies.csv` behind in a
    temp directory nobody will read. The pass still returns every row it built.

    The three list fields are three different answers and are deliberately not merged. `covered` is
    an allele gnomAD served counts for; `missing` is one it was asked about and does not have — a
    fact about a locus it does cover; `uncovered` is one it cannot cover at all (the Y
    pseudoautosomal region is hard-masked), where recording an absence would state something nobody
    established.

    **A skipped-offline run reports no absences at all**, and that is the same rule again rather
    than a special case. gnomAD is the one pass with no snapshot to fall back on (the v4.1 sites
    VCFs are 58 GB / 742 GB), so offline it returns `skipped_offline=True` with `missing` holding
    every allele that no existing `frequencies.csv` already pins — an honest statement of *what is
    not pinned*, which is not the question this field answers. Surfaced verbatim it said gnomAD had
    been asked about 57 alleles and had none of them, having asked about nothing: `unchecked`
    reported as `not_found`. The count is still worth having, so it travels as a warning that says
    which of the two it is.
    """
    from just_dna_enricher.frequencies import FrequencyEnrichmentError, enrich_frequencies

    try:
        result = enrich_frequencies(
            spec_dir,
            mode="best_effort",
            offline=offline,
            write=False,
            client=clients.gnomad if clients else None,
        )
    except FrequencyEnrichmentError as exc:
        # In best-effort the reachable causes are structural — no `resolution.csv` (a module with no
        # coordinate-bearing table at all) or one that will not parse. A degradation to report, not
        # a reason to fail a dry run whose other findings are perfectly good.
        return FrequencyCheck(warnings=[str(exc)])
    if result.skipped_offline:
        return FrequencyCheck(
            covered=len(result.covered),
            sources=list(result.sources),
            skipped_offline=True,
            warnings=[
                f"gnomAD was not consulted: this run is offline and there is no frequency snapshot "
                f"to fall back on. {len(result.missing)} allele(s) have no frequency pinned by an "
                f"existing frequencies.csv — which is a coverage gap, not an absence from gnomAD."
            ],
        )
    return FrequencyCheck(
        covered=len(result.covered),
        missing=list(result.missing),
        uncovered=list(result.uncovered),
        sources=list(result.sources),
        skipped_offline=False,
    )


def _literature_check(spec_dir: Path, offline: bool, clients: Any) -> LiteratureCheck:
    """Citation existence (PubMed), identifier agreement (Crossref) and quote grounding (Europe PMC).

    `quotes_found` and `quotes_unchecked` are kept apart because a hit and a miss are not
    symmetric: a phrase absent from a 200-word abstract says nothing about the body of the paper,
    so a quote that could not be checked must never be reported as a quote that failed.
    """
    from just_dna_enricher.literature import LiteratureEnrichmentError, enrich_literature

    try:
        result = enrich_literature(
            spec_dir,
            mode="best_effort",
            offline=offline,
            write=False,
            eutils=clients.eutils if clients else None,
            europepmc=clients.europepmc if clients else None,
            crossref=clients.crossref if clients else None,
        )
    except LiteratureEnrichmentError as exc:
        # Most often "no studies.csv", which is the correct and complete shape of a PGx-only module
        # (one CSV, one concern) rather than a defect in it.
        return LiteratureCheck(warnings=[str(exc)])
    return LiteratureCheck(
        missing_pmids=list(result.missing),
        missing_dois=list(result.doi_missing),
        doi_conflicts=[str(conflict) for conflict in result.doi_conflicts],
        quotes_authored=result.quotes_authored,
        quotes_found=result.quotes_found,
        quotes_unchecked=result.quotes_unchecked,
        skipped_offline=result.skipped_offline,
    )


def _identifiers_check(spec_dir: Path, offline: bool, clients: Any) -> IdentifierCheck:
    """Authored trait CURIEs against OLS4 and gene symbols against HGNC.

    The one optional pass with **no offline route of any kind**: neither registry publishes a
    snapshot, and `check_identifiers` takes no `offline` parameter, so there is no decision here to
    defer to the pass the way `offline=` is deferred everywhere else. Guarding is the only option,
    and what it must not do is come back empty — an unasked question reported as a clean answer is
    the failure mode this whole tier is arranged against. So the skip is explicit and `clean` stays
    `None`.

    HGNC's `unknown` and OLS4's `absent` are findings; a CURIE in an ontology this tier has no IRI
    route for comes back `unchecked` and is reported apart from both, because the enricher's own
    `clean` counts it as clean and it is not a statement about the module.

    Degrades on a transport failure rather than failing the dry run: OLS4 being down says nothing
    about the spec, and the other passes' findings are still worth returning.
    """
    from just_dna_enricher.identifiers import check_identifiers

    if not (spec_dir / "variants.csv").is_file():
        return IdentifierCheck(
            warnings=["no variants.csv — `trait_efo_id` and `gene` are variants-table columns, so "
                      "there is nothing to check"]
        )
    if offline:
        return IdentifierCheck(
            skipped_offline=True,
            warnings=["offline: OLS4 and HGNC are live-only and neither publishes a snapshot, so "
                      "nothing was asked. That is not the same as nothing being found."],
        )

    try:
        report = check_identifiers(spec_dir=spec_dir, client=clients.ontology if clients else None)
    except ValueError as exc:
        # `variants.csv` will not load — which the validation findings already explain in full, so
        # this is a note rather than a second, worse-worded copy of them.
        return IdentifierCheck(warnings=[str(exc)])
    except httpx.HTTPError as exc:
        return IdentifierCheck(warnings=[f"OLS4/HGNC could not be reached: {exc}"])

    unchecked = [
        f"{t.curie}: not an ontology this tier can resolve, so its currency is unknown"
        for t in report.traits
        if t.state == "unchecked"
    ]
    return IdentifierCheck(
        checked_traits=len(report.traits) - len(unchecked),
        checked_genes=len(report.genes),
        stale_traits=[
            f"{t.curie} is {t.state}"
            + (f" — OLS4 replaces it with {t.replaced_by}" if t.replaced_by else "")
            for t in report.stale_traits
        ],
        stale_genes=[
            f"{g.symbol} is {g.state}"
            + (f" — HGNC now approves {g.current}" if g.current else "")
            for g in report.stale_genes
        ],
        unchecked=unchecked,
        # Scoped to what this pass asked. `IdentifierReport.clean` also folds in `rsids`, which this
        # call never populates (they are checked inside `enrich()` and reported as `stale_rsids`), so
        # reading it would let one pass answer for another's field.
        clean=(
            not (report.stale_traits or report.stale_genes)
            if (report.traits or report.genes)
            else None
        ),
    )


def _acmg_check(spec_dir: Path, settings: Settings, offline: bool) -> AcmgCheck:
    """Authored `acmg_sf` flags against the ACMG secondary-findings gene list.

    Offline-capable, and only because of `acmg_snapshot_dir`: `just-dna-enricher acmg build` turns
    ACMG's own version-pinned workbook into a snapshot, which is both the offline route and the
    *better* one — NCBI's scrapeable page still serves v3.2 while ACMG published v3.3 in June 2025,
    so a disagreement against the page is as likely to be the list being old as the module being
    wrong. The enricher demotes those to `unverifiable`, which is why that field is reported apart
    from `mismatches` rather than folded into it. With neither a snapshot nor a network the pass
    reports `unchecked` — a question never put, not a negative answer.

    Findings are grouped **by gene**, because that is what the column is about: `acmg_sf` is
    gene-level list membership, so a per-row list prints one identical sentence once per variant
    (thirteen times for the HFE reference example).
    """
    from just_dna_enricher.acmg import AcmgReport, AcmgSfError, verify_acmg_sf

    if not (spec_dir / "variants.csv").is_file():
        return AcmgCheck(
            warnings=["no variants.csv — `acmg_sf` is a variants-table column, so there is nothing "
                      "to check"]
        )
    if offline and settings.acmg_snapshot_dir is None:
        return AcmgCheck(
            warnings=["offline with no ACMG SF snapshot configured (REGISTRY_ACMG_SNAPSHOT_DIR); "
                      "build one with `just-dna-enricher acmg build`. Nothing was checked — which "
                      "is not the same as nothing being found."]
        )

    try:
        # `spec_dir=` is enricher 0.5.1 (RM41). Until then this check took rows only, so a caller had
        # to load `variants.csv` itself — and the only loader that does it the way the compiler will
        # (an empty cell becomes `None`, and the module's declared build is injected into each row)
        # was the compiler's *private* `_load_csv_rows`. Handing over the directory is not just
        # tidier: `load_spec_variants` behind this reads `module_spec.yaml` for the build and
        # re-stamps, which the hand-rolled call here did not do.
        report = verify_acmg_sf(
            spec_dir=spec_dir,
            mode="best_effort",
            offline=offline,
            snapshot_dir=settings.acmg_snapshot_dir,
        )
    except AcmgSfError as exc:
        # The scrape guards refusing (a re-laid-out page, a short list) or the fetch failing. The
        # guards exist precisely so a short list is never reported as a set of module defects, so
        # their refusal is a note about the list, not a finding about the module.
        return AcmgCheck(warnings=[f"the ACMG SF list could not be read: {exc}"])

    return AcmgCheck(
        list_version=report.version,
        checked=report.checked,
        mismatches=[
            f"{message} ({_rows_note(rows)})"
            for _gene, rows, message in AcmgReport.by_gene(report.mismatches)
        ],
        unverifiable=[
            f"{message} ({_rows_note(rows)})"
            for _gene, rows, message in AcmgReport.by_gene(report.unverifiable)
        ],
        clean=report.clean,
        warnings=list(report.warnings),
    )


def _pgx_check(
    spec_dir: Path, settings: Settings, offline: bool, declared_use: str
) -> PgxCheck:
    """Authored PGx assertions against every nomenclature and clinical-annotation authority we can
    reach: PharmVar + CPIC (`enrich_pgx`), ClinPGx (`enrich_clinpgx`), ClinGen dosage
    (`enrich_dosage_sensitivity`).

    **`declared_use` gates all three**, and that is the point of running them together. Every PGx
    upstream is CC BY-SA *plus* a no-sale clause, so on the default `unstated` each is skipped with a
    reason rather than queried — the registry will not declare a purpose on a publisher's behalf.
    Declaring `commercial` is a direct contradiction and raises, which surfaces as `422
    license_refused`. (The resolution / frequency / gene-metrics passes never consult it: none of
    *those* sources forbids sale, so they record attribution and move on.)

    **Snapshot first, live second, skipped with a reason third** — the shape enricher 0.5.1 gave the
    whole family (RM38), and the one that makes a *hosted* registry legitimate. Before it, PharmVar
    and CPIC were live-only, so this endpoint's two options were to fetch a licence-gated source per
    request on the operator's own acceptance and personal key, or to skip. Neither is a service.
    Every published rate figure for these is per IP, so a server multiplies its callers onto one
    allowance rather than each getting their own; a provisioned cache is what removes the question.

    So `offline` is no longer the axis it was. It now means *snapshot only*, per leg, and a
    deployment that has run `registry warm-caches --apply` gets the full check with zero egress.
    Which route each source actually took is **recorded, not implied** — `PgxResult.routes`, surfaced
    on `PgxCheck.routes` — because a pinned file and a live API can differ by a release, and a
    consumer must be able to tell which answered.

    Per source:

    * **CPIC** — open, no credential. Snapshot (`cpic_cache`) → live.
    * **PharmVar** — snapshot (`pharmvar_cache`) → live-with-a-key. Note the consequence: a built
      snapshot enables this leg with **no key at all**, so the key is no longer the only switch it
      was through 0.11. PharmVar is the one cache the registry cannot pull for you — its bulk data
      comes down under a key its terms §2 make personal and non-transferable, so nothing is
      published and an operator builds it.
    * **ClinPGx** — snapshot only; it has no live route at all (the API was retired). `download` is
      forced off here, as everywhere on a request path: provisioning a snapshot mid-request is an
      operator's job, not a caller's wait.
    * **ClinGen dosage** — CC0 and online-only, so `declared_use` never refuses it but `offline`
      skips it. It gained its own `offline` parameter in 0.5.1 (RM39); through 0.11 this function
      hoisted a guard around it because it was the one pass that ignored the flag.
    """
    from just_dna_enricher.licensing import LicenseRefusal

    from just_dna_registry.services.publish import PublishError

    caches = configured_caches(settings)
    present = available_references(settings)
    has_key = bool(settings.pharmvar_api_key or os.environ.get("PHARMVAR_API_KEY"))
    # A snapshot needs no credential, so the leg is worth running whenever *either* is available.
    use_pharmvar = has_key or present["pharmvar"] is not None
    check = PgxCheck(
        declared_use=declared_use, pharmvar_enabled=use_pharmvar, offline=offline
    )

    sources: set[str] = set()
    try:
        # Three passes, three genuinely different result shapes — hence three explicit adapters
        # rather than one clever loop. `ClinGenResult` alone has no `warnings`, no `skipped`, and
        # `rows` of `GeneMetricsRow` (whose source lives on a separate `source_row`), so a generic
        # `getattr` walk would have quietly dropped findings from whichever one it did not fit.
        from just_dna_enricher.pgx import enrich_pgx

        pgx_result = enrich_pgx(
            spec_dir, mode="best_effort", offline=offline, declared_use=declared_use,
            use_pharmvar=use_pharmvar, use_cpic=True, write=False,
            cpic_cache=caches["cpic"], pharmvar_cache=caches["pharmvar"],
        )
        check.skipped.extend(pgx_result.skipped)
        check.skipped.extend(pgx_result.skipped_offline)
        check.warnings.extend(pgx_result.warnings)
        check.routes.update(pgx_result.routes)
        # `routes`, not `rows`. `PgxResult.rows` is the *merged* `sources.csv` — the module's own
        # authored rows plus whatever this run emitted, existing-wins — so reading sources off it
        # reported a source the module happened to declare as one the registry had consulted. A
        # module carrying an authored CPIC row got `sources: [cpic]` on a run whose very next line
        # said cpic was skipped for want of a snapshot, and picked up `ensembl` from the resolution
        # row `enrich()` had just written. `routes` gains an entry only where a client answered.
        sources.update(pgx_result.routes)
        check.conflicts.extend(
            FunctionConflictEntry(
                gene=c.gene, allele=c.allele, authored=c.authored, reported=c.reported,
                source=c.source,
            )
            for c in pgx_result.conflicts
        )
        if not use_pharmvar:
            check.skipped.append(
                "pharmvar: this deployment has neither a built snapshot "
                "(REGISTRY_PHARMVAR_CACHE, `just-dna-enricher pharmvar build`) nor an API key, so "
                "only CPIC was consulted. The key is personal to a PharmVar account (their terms "
                "§2) and its bulk data is therefore never published for pulling — a hosted "
                "deployment builds the snapshot once instead."
            )

        from just_dna_enricher.clinpgx import enrich_clinpgx

        cp = enrich_clinpgx(
            spec_dir, mode="best_effort", declared_use=declared_use,
            snapshot=caches["clinpgx"], offline=offline,
            download=False,  # never provision inside a request; `registry warm-caches` does it
            write=False,
        )
        check.warnings.extend(cp.warnings)
        check.routes.setdefault("clinpgx", "snapshot" if cp.rows or cp.dataset else "skipped")
        sources.update(row.source for row in cp.rows)
        # A different axis from the allele-function conflicts above — an authored *evidence level*
        # the record does not support — so it is rendered rather than forced into the gene/allele
        # shape it does not have.
        check.conflicts.extend(
            FunctionConflictEntry(
                gene=c.rsid or "?", allele=c.drug, authored=c.authored, reported=c.reported,
                source="clinpgx",
            )
            for c in cp.conflicts
        )
        if cp.unmatched:
            check.warnings.append(
                f"clinpgx: {len(cp.unmatched)} authored row(s) matched nothing in the snapshot"
            )
        # Keyed on "did it answer", not on "was a path configured". The earlier condition also
        # required `caches["clinpgx"] is None`, so an operator who pointed REGISTRY_CLINPGX_CACHE at
        # a directory holding no snapshot got silence — the one case where the setting *looks* done
        # and is not.
        if not (cp.rows or cp.dataset) and present["clinpgx"] is None:
            check.skipped.append(
                "clinpgx: no snapshot found (REGISTRY_CLINPGX_CACHE); provision one with "
                "`registry warm-caches --apply --use non_commercial`. It has no live route to fall "
                "back on — the API was retired."
            )

        from just_dna_enricher.clingen import enrich_dosage_sensitivity

        cg = enrich_dosage_sensitivity(
            spec_dir, mode="best_effort", declared_use=declared_use, offline=offline, write=False
        )
        if cg.skipped_offline:
            check.skipped.append(
                "clingen dosage: a CC0 curation TSV fetched live, and this run is offline. There is "
                "no snapshot for it, so re-run without offline to consult it."
            )
        if cg.source_row is not None:
            sources.add(cg.source_row.source)
        if cg.missing:
            check.warnings.append(
                f"clingen dosage: no curation for {len(cg.missing)} gene(s): "
                f"{', '.join(cg.missing[:5])}"
            )
    except LicenseRefusal as exc:
        # `commercial` against a source that forbids sale. A contradiction, not a finding — refused
        # at acquisition, so nothing was fetched.
        raise PublishError("license_refused", errors=[str(exc)])

    check.sources = sorted(sources)
    return check


class EnrichmentGate:
    """A process-wide cap on simultaneous enrichment runs, on top of the per-caller token bucket.

    Three reasons this exists, and only the first is about cost:

    1. The token bucket caps one caller. N accounts × 5/h is unbounded in N, and self-registration
       is one proof-of-work away.
    2. The enricher's outbound pacing lives on the client object (`PacingGate`, ~6s between gnomAD
       requests — exactly gnomAD's published 10-per-60s budget). Concurrent runs holding separate
       bundles egress at N× that. gnomAD is unauthenticated and throttles by IP, so the penalty lands
       on *this server* and everyone using it, and there is no key to buy a higher ceiling.
    3. `PacingGate` is a plain dataclass with no lock, so a shared bundle across threads races it.
       A limit of 1 is what makes sharing one bundle correct.

    Deliberately **not** an `asyncio.Semaphore`. `asyncio.wait_for` cancels the await, not the
    thread — Python cannot kill a thread — so a run that blows its timeout keeps working. The permit
    is therefore acquired by the coroutine (queued callers must not each occupy an anyio worker and
    exhaust Starlette's thread limiter) and released by the worker's own `finally`, so occupancy
    reflects reality rather than who is still waiting for an answer.

    Process-local, like the rate limiter beside it: with two replicas the effective limit is 2×.
    Horizontal scaling needs a shared gate, not just a shared bucket.

    ## Two lanes, because the two callers want opposite things

    `/check` is **interactive**: a person or a CI job is waiting on the answer, so a full gate is a
    fast `503` rather than a queue — queueing behind a multi-minute paced run only turns a quick
    rejection into a slow timeout.

    Publish is **idle**: nothing is watching, the upload already succeeded as far as the publisher
    can tell, and failing it for busy-ness would cost a whole re-upload. So it queues instead, with
    no deadline, and it *defers*: `acquire_idle` will not take a permit while an interactive caller
    has asked for one in the last `quiet_seconds`. That window is short on purpose. It is there to
    stop a publish winning a race against a check that arrived at the same moment, not to hold
    publishes until the server is quiet for a long stretch.

    **What deference cannot do, stated plainly:** once a publish holds the permit it keeps it until
    the enrichment finishes, and a `/check` arriving in that window still gets `503`. Nothing here
    can preempt it — Python cannot interrupt a thread, and `enrich()` is one opaque call with no
    yield point to hand back. The concessions are real but they are all made at *entry* (defer
    before starting) and *outside the permit* (a queued publish costs an event-loop task rather than
    a thread, and runs niced — see `run_at_low_priority`). Genuine preemption would need enrichment
    to be a job queue with a broker, which is the horizontal-scaling answer, not this one.
    """

    def __init__(self, limit: int, *, quiet_seconds: float = 5.0, poll_seconds: float = 0.5) -> None:
        self.limit = max(1, limit)
        self.quiet_seconds = quiet_seconds
        self.poll_seconds = max(0.01, poll_seconds)
        self._active = 0
        self._lock = threading.Lock()
        #: When an interactive caller last *asked*, granted or not. A rejected `/check` counts:
        #: demand is demand, and a stream of them is exactly when a publish should stay out of
        #: the way.
        self._last_interactive = float("-inf")
        #: FIFO among queued publishes. Without it, waiters poll on their own timers and whichever
        #: happens to wake first wins, so a publish can be overtaken indefinitely by later arrivals.
        self._next_ticket = 0
        self._waiting: set[int] = set()

    def try_acquire(self) -> bool:
        """Interactive: take a permit if one is free, else fail immediately. Never blocks."""
        with self._lock:
            self._last_interactive = time.monotonic()
            if self._active >= self.limit:
                return False
            self._active += 1
            return True

    async def acquire_idle(self, *, label: str = "publish") -> None:
        """Idle: wait — for as long as it takes — for a permit no interactive caller wants.

        Awaited in the **coroutine**, never in a worker thread. That is the load-bearing half of
        conceding to `/check`: Starlette's threadpool is a fixed, small pool, so a queued publish
        blocking a worker would starve the very requests it is supposed to yield to. Queued here, a
        publish costs one suspended task.

        Cancellation (the client hanging up) propagates as `CancelledError` and drops the ticket,
        because a caller nobody is waiting for should not hold a place in the queue.
        """
        with self._lock:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiting.add(ticket)

        started = time.monotonic()
        announced = False
        try:
            while True:
                if self._take_idle_permit(ticket):
                    waited = time.monotonic() - started
                    if waited > self.poll_seconds:
                        logger.info("%s waited %.1fs for an enrichment permit", label, waited)
                    return
                if not announced:
                    logger.info(
                        "%s is queued for enrichment behind %d active run(s) and %d waiter(s); "
                        "it will start when the gate is free and no /check has asked within %.0fs. "
                        "There is no deadline on this by design.",
                        label, self.active, self.waiting - 1, self.quiet_seconds,
                    )
                    announced = True
                await asyncio.sleep(self.poll_seconds)
        finally:
            with self._lock:
                self._waiting.discard(ticket)

    def _take_idle_permit(self, ticket: int) -> bool:
        """One non-blocking attempt: my turn, a free permit, and no recent interactive demand."""
        with self._lock:
            if self._active >= self.limit:
                return False
            if self._waiting and ticket != min(self._waiting):
                return False
            if time.monotonic() - self._last_interactive < self.quiet_seconds:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    @property
    def waiting(self) -> int:
        """Queued idle callers. Interactive callers never wait, so they are never counted here."""
        with self._lock:
            return len(self._waiting)
