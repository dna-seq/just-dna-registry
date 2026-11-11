"""Upstream's derived-table passes, run by the caching proxy for a caller who has no snapshot (0.30).

Through 0.29 `POST .../derived` ran `enrich()` and so produced three of upstream's sixteen derived
tables; the other passes ran only on an author's own machine, against snapshots this box holds. A pass
here is one of upstream's `DerivedProducer.command`s, run over the uploaded spec after `enrich_spec`,
with the rules every pass on this server keeps:

* the **configured** cache, never the resolved one, and `download=False`, since a request path never
  pulls a snapshot (a missing one is a skip with its reason);
* `mode=settings.enrich_mode`, never strict, so a refusal still leaves the table to diagnose from;
* one `try` per pass, the `*Unavailable` subclass caught **above** its parent (the AST guard in
  `tests/test_enrich_service.py` walks this file too), and one pass's failure never drops another's table;
* every pass reports what happened to it (`PassOutcome`), because a table missing from the archive has
  two opposite histories and `files_absent` alone cannot tell them apart.

The enricher is imported lazily, as in `services/enrich.py`: a client install has none.
"""

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from just_dna_registry.config import Settings

logger = logging.getLogger("registry.passes")

#: The order passes run in. `assertions` and `frequencies` read the `resolution.csv` that `enrich` wrote;
#: `opentargets enrich` fills columns on the rows `gwas` wrote; `gene-metrics` and `dosage` share one table.
PASS_ORDER: tuple[str, ...] = (
    "gwas", "opentargets enrich", "assertions", "frequencies", "gene-metrics", "dosage",
    "gene-validity", "ld-pairs", "literature",
)

#: The passes this server runs on request. Grows to `PASS_ORDER` (0.30); the coverage guard reads the
#: routes, and a route marks what it serves from this.
SERVED_PASSES: tuple[str, ...] = (
    "gwas", "opentargets enrich", "assertions", "frequencies", "gene-metrics", "dosage",
    "gene-validity", "ld-pairs", "literature",
)

#: Which `pacing.UPSTREAMS` budget each pass's live leg spends, for the charge taken before it runs.
PASS_UPSTREAMS: dict[str, tuple[str, ...]] = {
    "gwas": ("gwas_catalog",),
    "frequencies": ("gnomad",),
    "gene-metrics": ("gnomad",),
    "dosage": ("clingen",),
    "gene-validity": ("clingen", "gencc"),
    "ld-pairs": ("ensembl",),
    "literature": ("ncbi", "literature"),
}


@dataclass
class PassOutcome:
    """What one requested pass did: `ran`, `skipped` (it could not ask, with why), `unavailable` (it
    asked and the source did not answer), or `failed` (the answer was a problem)."""

    command: str
    status: str
    detail: str = ""
    tables: list[str] = field(default_factory=list)


def served_producers() -> tuple[tuple[str, str], ...]:
    """The `(table, command)` pairs `SERVED_PASSES` produce, for the route's coverage marker. Empty where
    the enricher is not installed: the route then answers `503 enrichment_unavailable` anyway."""
    try:
        return producers_of(SERVED_PASSES)
    except ImportError:
        return ()


def producers_of(commands: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """`(table, command)` for every table upstream says these commands produce."""
    from just_dna_enricher.producers import DERIVED_PRODUCERS

    return tuple(
        (p.table, p.command)
        for entries in DERIVED_PRODUCERS.values() for p in entries if p.command in commands
    )


def _opentargets(spec_dir: Path, settings: Settings, offline: bool) -> PassOutcome:
    from just_dna_enricher.opentargets import OpenTargetsError, enrich_opentargets

    try:
        result = enrich_opentargets(
            spec_dir, mode=settings.enrich_mode, write=True, snapshot=settings.opentargets_cache,
            declared_use=settings.declared_use,
        )
    except OpenTargetsError as exc:
        return PassOutcome("opentargets enrich", "failed", str(exc))
    if result.skipped:
        return PassOutcome("opentargets enrich", "skipped", str(result.skipped))
    counts = {
        "locus_to_gene": len(result.locus_to_gene), "colocalisations": len(result.colocalisations),
        "consequences": len(result.consequences), "gwas_effects": len(result.gwas_effects),
    }
    return PassOutcome(
        "opentargets enrich", "ran", ", ".join(f"{k} {v}" for k, v in counts.items()),
    )


def _assertions(spec_dir: Path, settings: Settings, offline: bool) -> PassOutcome:
    from just_dna_enricher.assertions import ClinicalAssertionError, enrich_clinical_assertions

    try:
        result = enrich_clinical_assertions(
            spec_dir, mode=settings.enrich_mode, offline=offline, clinvar_cache=settings.clinvar_cache,
            download=False, write=True,
        )
    except ClinicalAssertionError as exc:
        return PassOutcome("assertions", "failed", str(exc))
    if result.skipped_no_snapshot:
        return PassOutcome("assertions", "skipped", "this deployment holds no ClinVar snapshot")
    return PassOutcome(
        "assertions", "ran",
        f"{len(result.rows)} assertion(s); {len(result.covered)} variant(s) covered, "
        f"{len(result.missing)} with none",
    )


def _gene_metrics(spec_dir: Path, settings: Settings, offline: bool, clients: Any) -> PassOutcome:
    from just_dna_enricher.gene_metrics import (
        GeneMetricsEnrichmentError,
        GeneMetricsUnavailable,
        enrich_gene_metrics,
    )

    # The live leg is gnomAD's API, whose allowance is the deployment's and cannot be bought, so it is
    # used only where the operator opened it for the proxy (`hint_allow_gnomad`) and the caller asked
    # online; otherwise the constraint snapshot answers alone.
    live = not offline and settings.hint_allow_gnomad
    try:
        result = enrich_gene_metrics(
            spec_dir, mode=settings.enrich_mode, offline=not live,
            constraint_cache=settings.constraint_cache, download=False, write=True,
            client=clients.gnomad if live and clients is not None else None,
        )
    except GeneMetricsUnavailable as exc:
        return PassOutcome("gene-metrics", "unavailable", str(exc))
    except GeneMetricsEnrichmentError as exc:
        return PassOutcome("gene-metrics", "failed", str(exc))
    return PassOutcome(
        "gene-metrics", "ran",
        f"{len(result.rows)} row(s); {len(result.covered)} gene(s) covered, {len(result.missing)} missing"
        + ("" if live else "; snapshot only (the gnomAD API leg is off for this proxy)"),
    )


def _csv_column(data: bytes | None, column: str) -> set[str]:
    """The distinct non-empty values of one column of an uploaded CSV, for estimating a charge."""
    if not data:
        return set()
    rows = csv.DictReader(io.StringIO(data.decode("utf-8", errors="replace")))
    return {value.strip() for row in rows if (value := (row.get(column) or "").strip())}


def estimate_charges(uploads: dict[str, bytes], commands: list[str], settings: Settings) -> dict[str, int]:
    """What the requested passes' live legs will spend, per `pacing.UPSTREAMS` budget, read off the spec
    before anything runs, so a caller past their allowance is told before the work rather than after.

    An upper bound by construction: a variant the snapshot answers costs nothing upstream, and the
    estimate charges it anyway, which is the same side `/hint/variants` errs on."""
    def table(name: str) -> bytes | None:
        return next((data for rel, data in uploads.items() if rel.rsplit("/", 1)[-1] == name), None)

    rsids = _csv_column(table("variants.csv"), "rsid")
    genes = _csv_column(table("variants.csv"), "gene")
    proxies = _csv_column(table("studies.csv"), "proxy_rsid")
    pmids = _csv_column(table("studies.csv"), "pmid")
    charges: dict[str, int] = {}

    def add(upstream: str, units: int) -> None:
        if units:
            charges[upstream] = charges.get(upstream, 0) + units

    if "gwas" in commands:
        add("gwas_catalog", len(rsids))
    if "frequencies" in commands and settings.hint_allow_gnomad:
        add("gnomad", len(rsids))
    if "gene-metrics" in commands and settings.hint_allow_gnomad:
        add("gnomad", len(genes))
    if "dosage" in commands:
        add("clingen", 1)
    if "gene-validity" in commands:
        add("clingen", 1)
        add("gencc", 1)
    if "ld-pairs" in commands:
        add("ensembl", len(proxies))
    if "literature" in commands:
        add("ncbi", len(pmids))
        add("literature", len(pmids))
    return charges


def _skipped_or(result: Any, command: str, ran: str) -> PassOutcome:
    if getattr(result, "skipped_offline", False):
        return PassOutcome(command, "skipped", "offline: this pass needs a live source (ask with offline=false)")
    return PassOutcome(command, "ran", ran)


def _gwas(spec_dir: Path, settings: Settings, offline: bool) -> PassOutcome:
    from just_dna_enricher.gwas import GwasError, GwasNotFound, GwasRetired, enrich_gwas

    try:
        result = enrich_gwas(
            spec_dir, mode=settings.enrich_mode, offline=offline, write=True,
            declared_use=settings.declared_use,
        )
    except (GwasRetired, GwasNotFound) as exc:
        return PassOutcome("gwas", "unavailable", str(exc))
    except GwasError as exc:
        return PassOutcome("gwas", "failed", str(exc))
    return _skipped_or(
        result, "gwas",
        f"{len(result.rows)} association(s); {len(result.covered)} variant(s) covered, "
        f"{len(result.missing)} with none",
    )


def _frequencies(spec_dir: Path, settings: Settings, offline: bool, clients: Any) -> PassOutcome:
    from just_dna_enricher.frequencies import (
        FrequencyEnrichmentError,
        FrequencyUnavailable,
        enrich_frequencies,
    )

    if not offline and not settings.hint_allow_gnomad:
        return PassOutcome(
            "frequencies", "skipped",
            "gnomAD's allowance is this deployment's and cannot be bought; the operator has not opened it "
            "to the proxy (REGISTRY_HINT_ALLOW_GNOMAD)",
        )
    try:
        result = enrich_frequencies(
            spec_dir, mode=settings.enrich_mode, offline=offline, write=True,
            client=clients.gnomad if clients is not None and not offline else None,
        )
    except FrequencyUnavailable as exc:
        return PassOutcome("frequencies", "unavailable", str(exc))
    except FrequencyEnrichmentError as exc:
        return PassOutcome("frequencies", "failed", str(exc))
    return _skipped_or(
        result, "frequencies", f"{len(result.rows)} row(s); {len(result.covered)} variant(s) covered",
    )


def _dosage(spec_dir: Path, settings: Settings, offline: bool) -> PassOutcome:
    from just_dna_enricher.clingen import (
        ClinGenError,
        ClinGenRetired,
        ClinGenUnavailable,
        enrich_dosage_sensitivity,
    )

    try:
        result = enrich_dosage_sensitivity(
            spec_dir, mode=settings.enrich_mode, declared_use=settings.declared_use, offline=offline,
            write=True,
        )
    except (ClinGenUnavailable, ClinGenRetired) as exc:
        return PassOutcome("dosage", "unavailable", str(exc))
    except ClinGenError as exc:
        return PassOutcome("dosage", "failed", str(exc))
    return _skipped_or(result, "dosage", f"{len(result.rows)} gene(s) with a dosage call")


def _gene_validity(spec_dir: Path, settings: Settings, offline: bool) -> PassOutcome:
    from just_dna_enricher.gene_validity import (
        GeneValidityError,
        GeneValidityRetired,
        GeneValidityUnavailable,
        enrich_gene_validity,
    )

    # Both authorities upstream names for the table, one run each; each run merges into the table.
    said: list[str] = []
    for source in ("clingen", "gencc"):
        try:
            result = enrich_gene_validity(
                spec_dir, source=source, mode=settings.enrich_mode, offline=offline, write=True,
            )
        except (GeneValidityUnavailable, GeneValidityRetired) as exc:
            return PassOutcome("gene-validity", "unavailable", f"{source}: {exc}")
        except GeneValidityError as exc:
            return PassOutcome("gene-validity", "failed", f"{source}: {exc}")
        if getattr(result, "skipped_offline", False):
            return _skipped_or(result, "gene-validity", "")
        said.append(f"{source} {len(result.rows)} assertion(s)")
    return PassOutcome("gene-validity", "ran", "; ".join(said))


def _ld_pairs(spec_dir: Path, settings: Settings, offline: bool) -> PassOutcome:
    from just_dna_enricher.ld_pairs import LdError, LdRetired, LdUnavailable, enrich_ld_pairs

    try:
        result = enrich_ld_pairs(spec_dir, offline=offline, write=True)
    except (LdUnavailable, LdRetired) as exc:
        return PassOutcome("ld-pairs", "unavailable", str(exc))
    except LdError as exc:
        return PassOutcome("ld-pairs", "failed", str(exc))
    return _skipped_or(result, "ld-pairs", f"{len(result.rows)} pair(s)")


def _literature(spec_dir: Path, settings: Settings, offline: bool, clients: Any) -> PassOutcome:
    from just_dna_enricher.literature import (
        FulltextRetired,
        FulltextUnavailable,
        LiteratureEnrichmentError,
        LiteratureRetired,
        LiteratureUnavailable,
        enrich_literature,
    )

    shared = {} if clients is None or offline else {
        "eutils": clients.eutils, "europepmc": clients.europepmc, "crossref": clients.crossref,
    }
    try:
        result = enrich_literature(
            spec_dir, mode=settings.enrich_mode, offline=offline, write=True, **shared,
        )
    except (LiteratureUnavailable, LiteratureRetired, FulltextUnavailable, FulltextRetired) as exc:
        return PassOutcome("literature", "unavailable", str(exc))
    except LiteratureEnrichmentError as exc:
        return PassOutcome("literature", "failed", str(exc))
    return PassOutcome(
        "literature", "ran",
        f"{len(result.rows)} citation row(s)" + ("; offline: nothing was looked up" if offline else ""),
    )


def run_passes(
    spec_dir: Path, settings: Settings, commands: list[str], *, offline: bool, clients: Any = None
) -> list[PassOutcome]:
    """Run each requested pass in `PASS_ORDER`, each on its own, and say what happened to every one."""
    runners = {
        "gwas": lambda: _gwas(spec_dir, settings, offline),
        "opentargets enrich": lambda: _opentargets(spec_dir, settings, offline),
        "assertions": lambda: _assertions(spec_dir, settings, offline),
        "frequencies": lambda: _frequencies(spec_dir, settings, offline, clients),
        "gene-metrics": lambda: _gene_metrics(spec_dir, settings, offline, clients),
        "dosage": lambda: _dosage(spec_dir, settings, offline),
        "gene-validity": lambda: _gene_validity(spec_dir, settings, offline),
        "ld-pairs": lambda: _ld_pairs(spec_dir, settings, offline),
        "literature": lambda: _literature(spec_dir, settings, offline, clients),
    }
    outcomes = []
    for command in PASS_ORDER:
        if command in commands:
            outcome = runners[command]()
            outcome.tables = [table for table, cmd in producers_of((command,))]
            logger.info("pass %s: %s %s", command, outcome.status, outcome.detail)
            outcomes.append(outcome)
    return outcomes
