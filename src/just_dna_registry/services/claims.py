"""The variant-level catalog's projection: what a published version says about each variant (0.31).

Read from the version's own compiled parquets, so the manifest and the artifact stay the source of truth
and the projection can be rebuilt from storage. The design and its review are in docs/ROADMAP.md
("A variant-level catalog, with a gene-level facet"). The rules that shape this module:

* **Columns by presence.** A 0.7-compiled parquet has no `vrs_id`; an older module may carry `state`
  and no `direction`. Nothing here assumes a column exists.
* **Direction is per allele.** `direction` signs `effect_allele`; `state` signs the genotype. Only
  `risk`, `protective` and `neutral` are projected as a direction; `significant`, `alt`, `ref`,
  `unknown` and `contested` are kept as NULL, *not comparable*, and never inferred from a weight's sign
  (weights are per-module scale, `manifest.weighting`).
* **Genes are authored, never assigned by position.** Upstream's MANE spans are query hints, not
  attributions (`just_dna_enricher.gene_spans`).
* **Every table projects as its own kind.** Only `weights` carries direction and weight; pharmacogenomic,
  heteroplasmy and haplotype rows say that a module names the variant, and never enter the conflict marker.
"""

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import polars as pl

#: Bumped whenever what a projection holds changes, so a backfill re-projects what an older one wrote.
PROJECTOR_VERSION = "1"

COMPARABLE_DIRECTIONS: frozenset[str] = frozenset({"risk", "protective", "neutral"})


@dataclass
class Claim:
    kind: str
    variant_key: str
    rsid: str | None = None
    genome_build: str | None = None
    genotype: str | None = None
    effect_allele: str | None = None
    direction: str | None = None
    direction_source: str | None = None
    weight: float | None = None
    trait_efo_id: str | None = None
    clin_sig: str | None = None
    stat_significance: str | None = None
    gene: str | None = None


@dataclass
class Projection:
    claims: list[Claim] = field(default_factory=list)
    #: `(alias, variant_key, genome_build)`: every spelling a variant is known by in this version.
    aliases: list[tuple[str, str, str | None]] = field(default_factory=list)
    #: `(pgs_id, trait_efo_id)`.
    pgs: list[tuple[str, str | None]] = field(default_factory=list)


def _frame(read: Callable[[str], bytes | None], name: str) -> pl.DataFrame | None:
    data = read(name)
    return pl.read_parquet(io.BytesIO(data)) if data else None


def _value(row: dict[str, Any], column: str) -> Any:
    value = row.get(column)
    return None if value == "" else value


def normalise_genotype(genotype: Any) -> str | None:
    """`["G", "A"]` or `"G/A"` to `A/G`: alleles sorted, so two modules' spellings of one genotype meet."""
    if genotype is None:
        return None
    alleles = list(genotype) if isinstance(genotype, list) else str(genotype).replace("|", "/").split("/")
    alleles = [a.strip() for a in alleles if a and a.strip()]
    return "/".join(sorted(alleles)) if alleles else None


def _direction(row: dict[str, Any]) -> tuple[str | None, str | None]:
    authored = _value(row, "direction")
    if authored is not None:
        return (authored, "direction") if authored in COMPARABLE_DIRECTIONS else (None, None)
    state = _value(row, "state")
    if state in COMPARABLE_DIRECTIONS:
        return state, "state"
    return None, None


def project(read: Callable[[str], bytes | None], genome_build: str | None) -> Projection:
    """The claims one version's parquets make. `read(name)` returns a file's bytes, or `None` when the
    version has no such file."""
    out = Projection()
    genes: dict[str, str] = {}
    annotations = _frame(read, "annotations.parquet")
    if annotations is not None and "gene" in annotations.columns:
        for row in annotations.select("variant_key", "gene").iter_rows(named=True):
            if row["gene"] and row["variant_key"] not in genes:
                genes[row["variant_key"]] = row["gene"]

    weights = _frame(read, "weights.parquet")
    if weights is not None:
        for row in weights.iter_rows(named=True):
            key = row.get("variant_key")
            if not key:
                continue
            direction, source = _direction(row)
            out.claims.append(Claim(
                kind="weight", variant_key=key, rsid=_value(row, "rsid"), genome_build=genome_build,
                genotype=normalise_genotype(row.get("genotype")), effect_allele=_value(row, "effect_allele"),
                direction=direction, direction_source=source, weight=row.get("weight"),
                trait_efo_id=_value(row, "trait_efo_id"), clin_sig=_value(row, "clin_sig"),
                stat_significance=_value(row, "stat_significance"), gene=genes.get(key),
            ))
            out.aliases.extend(_aliases(row, key, genome_build))

    for name, kind, genotype_column in (
        ("pharm_variants.parquet", "pharm", "genotype"),
        ("heteroplasmy.parquet", "heteroplasmy", None),
        ("haplotypes.parquet", "haplotype", "allele"),
    ):
        frame = _frame(read, name)
        if frame is None or "variant_key" not in frame.columns:
            continue
        for row in frame.iter_rows(named=True):
            key = row.get("variant_key")
            if not key:
                continue
            out.claims.append(Claim(
                kind=kind, variant_key=key, rsid=_value(row, "rsid"), genome_build=genome_build,
                genotype=normalise_genotype(row.get(genotype_column)) if genotype_column else None,
                clin_sig=_value(row, "clin_sig"), gene=_value(row, "gene") or genes.get(key),
            ))
            out.aliases.extend(_aliases(row, key, genome_build))

    pgs = _frame(read, "pgs.parquet")
    if pgs is not None and "pgs_id" in pgs.columns:
        for row in pgs.iter_rows(named=True):
            if row.get("pgs_id"):
                out.pgs.append((row["pgs_id"], _value(row, "trait_efo_id")))
    out.aliases = sorted(set(out.aliases), key=lambda a: (a[0], a[1], a[2] or ""))
    return out


def _aliases(row: dict[str, Any], key: str, genome_build: str | None) -> list[tuple[str, str, str | None]]:
    """Every spelling of this row's variant: its key, its rsID, its VRS ids and its coordinates, from the
    row and from `resolution_loci` (many-to-many: one rsID can place at several loci)."""
    found = {key}
    if row.get("rsid"):
        found.add(row["rsid"])
    for vrs in row.get("vrs_id") or []:
        if vrs:
            found.add(vrs)
    for locus in row.get("resolution_loci") or []:
        for spelling in (locus.get("rsid"), locus.get("vrs_id")):
            if spelling:
                found.add(spelling)
        if locus.get("chrom") and locus.get("start") and locus.get("ref"):
            found.add(f"{locus['chrom']}:{locus['start']}:{locus['ref']}:{locus.get('alts') or ''}".rstrip(":"))
    return [(alias, key, genome_build) for alias in found]
