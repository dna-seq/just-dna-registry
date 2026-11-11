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
SERVED_PASSES: tuple[str, ...] = ("opentargets enrich", "assertions", "gene-metrics")


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


def run_passes(
    spec_dir: Path, settings: Settings, commands: list[str], *, offline: bool, clients: Any = None
) -> list[PassOutcome]:
    """Run each requested pass in `PASS_ORDER`, each on its own, and say what happened to every one."""
    runners = {
        "opentargets enrich": lambda: _opentargets(spec_dir, settings, offline),
        "assertions": lambda: _assertions(spec_dir, settings, offline),
        "gene-metrics": lambda: _gene_metrics(spec_dir, settings, offline, clients),
    }
    outcomes = []
    for command in PASS_ORDER:
        if command in commands:
            outcome = runners[command]()
            outcome.tables = [table for table, cmd in producers_of((command,))]
            logger.info("pass %s: %s %s", command, outcome.status, outcome.detail)
            outcomes.append(outcome)
    return outcomes
