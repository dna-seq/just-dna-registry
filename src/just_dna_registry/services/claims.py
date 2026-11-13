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
import json
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


#: The parquet files a projection reads, so a backfill fetches only these from storage.
PROJECTED_FILES: tuple[str, ...] = (
    "weights.parquet", "annotations.parquet", "pharm_variants.parquet", "heteroplasmy.parquet",
    "haplotypes.parquet", "pgs.parquet",
)


@dataclass
class BackfillReport:
    projected: list[str] = field(default_factory=list)
    current: int = 0
    failed: list[str] = field(default_factory=list)


def backfill(repo: Any, storage: Any, *, every: bool = False, namespace: str | None = None) -> BackfillReport:
    """Project each module's latest non-yanked version that has no projection, or one an older projector
    wrote (`every` re-projects all of them). Reads only `PROJECTED_FILES` from storage, latest versions
    only, and stores each version on its own, so a failure leaves that one unprojected and the rest done."""
    from just_dna_registry.storage.base import version_key

    report = BackfillReport()
    rows = repo.conn.execute(
        "SELECT v.id, m.namespace, m.name, v.version, v.claims_projector, v.manifest_json "
        "FROM versions v JOIN modules m ON m.id = v.module_id "
        "WHERE v.version = m.latest_version AND v.yanked = 0 AND (? IS NULL OR m.namespace = ?) "
        "ORDER BY m.namespace, m.name",
        (namespace, namespace),
    ).fetchall()
    for row in rows:
        label = f"{row['namespace']}/{row['name']}@{row['version']}"
        if not every and row["claims_projector"] == PROJECTOR_VERSION:
            report.current += 1
            continue
        key = version_key(row["namespace"], row["name"], row["version"])

        def read(name: str, key: str = key) -> bytes | None:
            return storage.read_file(key, name) if storage.exists(key, name) else None

        try:
            build = json.loads(row["manifest_json"]).get("genome_build")
            repo.store_claims(int(row["id"]), project(read, build), PROJECTOR_VERSION)
        except Exception as exc:  # noqa: BLE001 - one version's failure is reported, the rest go on
            report.failed.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        report.projected.append(label)
    return report


# ── Reading the catalog (0.31) ──────────────────────────────────────────────────────────────────────

#: Opposite directions, for the conflict marker.
_OPPOSITE = {("risk", "protective"), ("protective", "risk")}
_COMPLEMENT = str.maketrans("ACGT", "TGCA")


def _visible_versions_sql(exclude: list[str]) -> tuple[str, list[Any]]:
    """The listing's rules for which modules a reader sees: the latest non-yanked version, never a
    blacklisted namespace, and (on production) never a test/sandbox one."""
    sql = (
        "v.version = m.latest_version AND v.yanked = 0 "
        "AND COALESCE((SELECT blacklisted FROM namespaces n WHERE n.name = m.namespace), 0) = 0"
    )
    params: list[Any] = []
    if exclude:
        sql += f" AND m.namespace NOT IN ({','.join('?' * len(exclude))})"
        params += exclude
    return sql, params


def _oriented(claim: dict[str, Any]) -> tuple[str, str] | None:
    """`(allele, direction)` for a weight claim, signed for one allele so two modules compare: `direction`
    signs `effect_allele`. `None` when the claim names no effect allele or no comparable direction."""
    allele, direction = claim.get("effect_allele"), claim.get("direction")
    if not allele or direction not in ("risk", "protective") or claim.get("direction_source") != "direction":
        return None
    return allele.upper(), direction


def _same_allele(a: str, b: str) -> bool | None:
    """Whether two effect alleles are one allele: equal, or the reverse complement of each other only when
    neither could be read on its own strand (an A/T or C/G pair is ambiguous, so `None`)."""
    if a == b:
        return True
    # A strand flip would make them one allele, but nothing in a row says which strand it was authored on,
    # so a complement is never assumed: the pair is not compared rather than guessed at.
    if a.translate(_COMPLEMENT)[::-1] == b:
        return None
    return False


def conflicts(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """The cross-module disagreement marker over one variant's weight claims, and why each other pair was
    not compared. Two claims conflict only when they come from different modules and share the genotype,
    a non-null trait, and the effect allele, and one says `risk` while the other says `protective`. It is a
    fact about two modules' statements, never a verdict on either."""
    weights = [c for c in claims if c["kind"] == "weight"]
    pairs: list[dict[str, Any]] = []
    incomparable: dict[str, int] = {}
    compared = 0

    def skip(reason: str) -> None:
        incomparable[reason] = incomparable.get(reason, 0) + 1

    for i, a in enumerate(weights):
        for b in weights[i + 1:]:
            if a["module"] == b["module"]:
                continue
            if (a.get("genome_build") or "") != (b.get("genome_build") or ""):
                skip("other_build")
                continue
            if a.get("genotype") != b.get("genotype"):
                continue  # different genotypes are different statements, not a disagreement
            if not a.get("trait_efo_id") or not b.get("trait_efo_id"):
                skip("no_trait")
                continue
            if a["trait_efo_id"] != b["trait_efo_id"]:
                skip("other_trait")
                continue
            oa, ob = _oriented(a), _oriented(b)
            if oa is None or ob is None:
                skip("no_effect_allele_or_direction")
                continue
            same = _same_allele(oa[0], ob[0])
            if same is None:
                skip("allele_not_orientable")
                continue
            if not same:
                skip("other_effect_allele")
                continue
            compared += 1
            if (oa[1], ob[1]) in _OPPOSITE:
                pairs.append({"modules": [a["module"], b["module"]], "genotype": a["genotype"],
                              "trait_efo_id": a["trait_efo_id"], "effect_allele": oa[0],
                              "directions": [oa[1], ob[1]]})
    return {"pairs": pairs, "compared": compared, "incomparable": incomparable}


def variant_claims(repo: Any, key: str, *, exclude_namespaces: list[str]) -> dict[str, Any]:
    """Every visible module's claims about one variant, by any spelling of it (rsID, VRS id, coordinates),
    with the conflict marker and how many visible versions are not yet projected."""
    visible, params = _visible_versions_sql(exclude_namespaces)
    keys = {r[0] for r in repo.conn.execute(
        "SELECT DISTINCT variant_key FROM claim_aliases WHERE alias = ?", (key,)
    ).fetchall()} | {key}
    marks = ",".join("?" * len(keys))
    rows = [dict(r) for r in repo.conn.execute(
        f"SELECT m.namespace || '/' || m.name AS module, v.version AS version, c.* "
        f"FROM version_claims c JOIN versions v ON v.id = c.version_id JOIN modules m ON m.id = v.module_id "
        f"WHERE c.variant_key IN ({marks}) AND {visible} ORDER BY m.namespace, m.name, c.kind",
        [*keys, *params],
    ).fetchall()]
    for row in rows:
        row.pop("version_id", None)
    return {
        "key": key,
        "variant_keys": sorted(keys),
        "claims": rows,
        "modules": sorted({r["module"] for r in rows}),
        "conflicts": conflicts(rows),
        "not_projected": _not_projected(repo, exclude_namespaces),
    }


def gene_claims(repo: Any, symbol: str, *, exclude_namespaces: list[str]) -> dict[str, Any]:
    """Every visible module's claims that name `symbol` as the authored gene (never assigned by position)."""
    visible, params = _visible_versions_sql(exclude_namespaces)
    rows = [dict(r) for r in repo.conn.execute(
        f"SELECT m.namespace || '/' || m.name AS module, v.version AS version, c.* "
        f"FROM version_claims c JOIN versions v ON v.id = c.version_id JOIN modules m ON m.id = v.module_id "
        f"WHERE UPPER(c.gene) = UPPER(?) AND {visible} ORDER BY c.variant_key, m.namespace, m.name",
        [symbol, *params],
    ).fetchall()]
    for row in rows:
        row.pop("version_id", None)
    return {
        "gene": symbol,
        "claims": rows,
        "modules": sorted({r["module"] for r in rows}),
        "variants": len({r["variant_key"] for r in rows}),
        "not_projected": _not_projected(repo, exclude_namespaces),
    }


def _not_projected(repo: Any, exclude_namespaces: list[str]) -> int:
    """Visible latest versions with no projection yet: silence from them is not agreement."""
    visible, params = _visible_versions_sql(exclude_namespaces)
    return int(repo.conn.execute(
        f"SELECT count(*) FROM versions v JOIN modules m ON m.id = v.module_id "
        f"WHERE {visible} AND v.claims_projector IS NULL", params,
    ).fetchone()[0])
