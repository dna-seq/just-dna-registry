"""
Catalog service: reads the projection and builds API models (cards, detail, versions, manifest).
Card stats are pulled from each module's latest-version manifest (the source of truth).
"""

import sqlite3
from typing import Optional

from just_dna_format.manifest import ModuleManifest

from just_dna_registry import groups
from just_dna_registry.config import API_PREFIX
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.facets import is_trusted, version_facets
from just_dna_registry.models.api import (
    CardStats,
    FactTablesInfo,
    GwasEffectsInfo,
    LicensingInfo,
    ModuleCard,
    ModuleDetail,
    Page,
    ResolutionInfo,
    VerificationCheck,
    VerificationInfo,
    VersionSummary,
    WeightingInfo,
)

_CARD_GENES: int = 3  # genes shown on a card; the full list lives in the manifest


def _manifest_url(namespace: str, name: str, version: str) -> str:
    return f"{API_PREFIX}/modules/{namespace}/{name}/versions/{version}/manifest"


def _logo_url(namespace: str, name: str, version: str, manifest: Optional[ModuleManifest]) -> Optional[str]:
    if manifest is None or manifest.logo is None:
        return None
    return f"{API_PREFIX}/modules/{namespace}/{name}/versions/{version}/files/{manifest.logo.name}"


def _latest_manifest(repo: Repository, row: sqlite3.Row) -> Optional[ModuleManifest]:
    if not row["latest_version"]:
        return None
    raw = repo.get_manifest_json(row["namespace"], row["name"], row["latest_version"])
    return ModuleManifest.model_validate_json(raw) if raw else None


def _featured(repo: Repository, row: sqlite3.Row) -> bool:
    if "featured" in row.keys():  # search rows carry it (no extra query)
        return bool(row["featured"])
    flags = repo.namespace_flags(row["namespace"])
    return bool(flags["featured"]) if flags else False


def _resolution_from_manifest(manifest: Optional[ModuleManifest]) -> ResolutionInfo:
    """The trust facet, from a manifest. Used on the card, where the manifest is already loaded."""
    if manifest is None:
        return ResolutionInfo()
    compilation = manifest.compilation
    alleles = compilation.vrs_alleles
    return ResolutionInfo(
        mode=compilation.resolution_mode,
        fully_resolved=compilation.fully_resolved,
        trusted=is_trusted(manifest),
        vrs_alleles=alleles,
        vrs_alleles_identified=compilation.vrs_alleles_identified,
        vrs_complete=(compilation.vrs_alleles_identified == alleles) if alleles else None,
        **_counters_from_manifest(manifest),
        sources=list(compilation.resolution_sources),
        signature=compilation.resolution_signature,
    )


def _resolution_from_row(row: sqlite3.Row) -> ResolutionInfo:
    """The trust facet, from the projected columns — no manifest parse.

    The version list renders one of these per row, so it must not reparse `manifest_json` N times.
    `resolution_signature`/`sources` are deliberately absent here: they are payload rather than
    filters, so they stay in the manifest and surface on the detail endpoint's inline copy.
    """
    keys = row.keys()
    if "trusted" not in keys:
        return ResolutionInfo()
    alleles = int(row["vrs_alleles"] or 0)
    identified = int(row["vrs_identified"] or 0)
    return ResolutionInfo(
        mode=row["resolution_mode"],
        fully_resolved=bool(row["fully_resolved"]),
        trusted=None if row["trusted"] is None else bool(row["trusted"]),
        vrs_alleles=alleles,
        vrs_alleles_identified=identified,
        vrs_complete=(identified == alleles) if alleles else None,
        # Read straight through, `None` included: these columns are nullable precisely so the row
        # path can say "not measured" in the same words the manifest path does. `int(x or 0)` — the
        # idiom two lines up, correct for a counter with a meaningful zero — would be wrong here.
        **{
            name: (None if row[name] is None else int(row[name]))
            for name in _COUNTER_COLUMNS
            if name in keys
        },
    )


#: The 0.6 counters, by the name they share across the manifest, the column and the API field. One
#: spelling in three places is what keeps the row path and the manifest path from drifting.
_COUNTER_COLUMNS: tuple[str, ...] = (
    "resolution_subjects",
    "positional_rows",
    "positional_rows_placed",
    "expanded_keys",
    "expanded_rows",
)


def _counters_from_manifest(manifest: ModuleManifest) -> dict[str, Optional[int]]:
    """The same counters `version_facets` projects, for the card's manifest-side path.

    Delegated rather than re-read off `manifest.compilation`, so the era gate that turns a pre-0.6
    `resolution_subjects: 0` into `None` is applied once and cannot be forgotten on one path only.
    """
    facets = version_facets(manifest)
    return {name: facets[name] for name in _COUNTER_COLUMNS}


def _licensing(manifest: Optional[ModuleManifest]) -> LicensingInfo:
    """What the module's sources permit. Tri-state throughout: `None` means undetermined, and an
    undetermined permission has not been shown to exist."""
    sources = manifest.sources if manifest else None
    if sources is None:
        return LicensingInfo()
    return LicensingInfo(
        commercial_use=sources.commercial_use,
        redistribution=sources.redistribution,
        share_alike_layers=list(sources.share_alike_layers),
        noncommercial_layers=list(sources.noncommercial_layers),
        nonredistributable_layers=list(sources.nonredistributable_layers),
        unknown_terms_sources=list(sources.unknown_terms_sources),
        licenses=list(sources.licenses),
        attributions=list(sources.attributions),
        declared_uses=list(sources.declared_uses),
    )


def _facts(manifest: Optional[ModuleManifest]) -> FactTablesInfo:
    """Which derived fact tables the version carries. Presence only — see `FactTablesInfo`.

    Read off the manifest blocks rather than off `artifact.files`: a block is present exactly when
    the compile had the table, which is the same question asked one level up and does not depend on
    how a parquet came to be named.
    """
    if manifest is None:
        return FactTablesInfo()
    return FactTablesInfo(
        gene_validity=manifest.gene_validity is not None,
        clinical_assertions=manifest.clinical_assertions is not None,
        gwas_effects=manifest.gwas_effects is not None,
        frequencies=manifest.frequency is not None,
        weighting_declared=manifest.weighting is not None,
    )


def _facts_from_row(row: sqlite3.Row) -> FactTablesInfo:
    """The same facets from the projected columns, for list rows that must not reparse a manifest.

    A card built by `list_modules` already loads the latest manifest for its stats, so it could use
    `_facts`; this exists so the *filters* and the columns they read cannot disagree with what the
    card renders. Missing columns mean a DB that has not migrated yet, which reads as all-absent —
    the honest answer, since nothing has been projected.
    """
    keys = row.keys()
    if "has_gwas_effects" not in keys:
        return FactTablesInfo()
    return FactTablesInfo(
        gene_validity=bool(row["has_gene_validity"]),
        clinical_assertions=bool(row["has_clinical_assertions"]),
        gwas_effects=bool(row["has_gwas_effects"]),
        frequencies=bool(row["has_frequencies"]),
        weighting_declared=bool(row["weighting_declared"]),
    )


def _verification(manifest: Optional[ModuleManifest]) -> Optional[VerificationInfo]:
    """The publisher's attestation, or `None` when the module said nothing.

    `None` and an empty block are **not** collapsed: absent means no attestation survived into the
    manifest, which is a different statement from an attestation that recorded no checks. Both read
    as "nothing was verified", but only one of them is a claim someone made.
    """
    if manifest is None or manifest.verification is None:
        return None
    block = manifest.verification
    closure = block.closure
    return VerificationInfo(
        closed=closure is not None,
        closed_at=closure.closed_at if closure else None,
        closed_by=closure.closed_by if closure else None,
        producer=block.producer,
        produced_at=block.produced_at,
        checks=[
            VerificationCheck(
                check=record.check,
                subjects=record.subjects,
                findings=record.findings,
                skipped=record.skipped,
                detail=record.detail,
                source=record.source,
                release=record.release,
                checked_at=record.checked_at,
            )
            for record in block.checks
        ],
    )


def _weighting(manifest: Optional[ModuleManifest]) -> Optional[WeightingInfo]:
    """What the module says its weights mean — verbatim, or `None` if it has not said."""
    if manifest is None or manifest.weighting is None:
        return None
    return WeightingInfo(
        scale=manifest.weighting.scale,
        method=manifest.weighting.method,
        note=manifest.weighting.note,
    )


def _gwas_effects(manifest: Optional[ModuleManifest]) -> Optional[GwasEffectsInfo]:
    """The GWAS sidecar's facets, with the two that decide usability carried alongside the count."""
    if manifest is None or manifest.gwas_effects is None:
        return None
    block = manifest.gwas_effects
    return GwasEffectsInfo(
        row_count=block.row_count,
        variant_count=block.variant_count,
        with_effect_allele=block.with_effect_allele,
        without_effect_allele=block.without_effect_allele,
        measures=list(block.measures),
        units=list(block.units),
        traits=list(block.traits),
        sources=list(block.sources),
        datasets=list(block.datasets),
    )


def _card(repo: Repository, row: sqlite3.Row, starred_by: Optional[int] = None) -> ModuleCard:
    manifest = _latest_manifest(repo, row)
    stats = manifest.stats if manifest else None
    card_stats = CardStats(
        variant_count=stats.variant_count if stats else 0,
        study_count=stats.study_count if stats else 0,
        gene_count=stats.gene_count if stats else 0,
        genes=stats.genes[:_CARD_GENES] if stats else [],
        categories=stats.categories if stats else [],
        clinvar_count=stats.clinvar_count if stats else 0,
        pathogenic_count=stats.pathogenic_count if stats else 0,
        benign_count=stats.benign_count if stats else 0,
    )
    starred = starred_by is not None and repo.is_starred(int(row["id"]), starred_by)
    reviews = repo.review_summary(int(row["id"]))
    funding = repo.funding_for_module(row["namespace"], row["name"])
    return ModuleCard(
        namespace=row["namespace"],
        name=row["name"],
        title=row["title"],
        description=row["description"],
        icon=manifest.display.icon if manifest else row["icon"],
        icon_set=manifest.display.icon_set if manifest else "fomantic",
        color=row["color"],
        logo_url=_logo_url(row["namespace"], row["name"], row["latest_version"], manifest)
        if row["latest_version"]
        else None,
        latest_version=row["latest_version"],
        genome_build=row["genome_build"],
        license=row["license"],
        owner=row["owner"],
        stats=card_stats,
        downloads=row["downloads"],
        stars=row["stars"],
        views=row["views"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        starred_by_me=bool(starred),
        featured=_featured(repo, row),
        review_count=reviews["review_count"],
        avg_rating=reviews["avg_rating"],
        curated=reviews["highlighted_count"] > 0,
        author_funding_url=funding["author_funding_url"],
        org_funding_url=funding["org_funding_url"],
        resolution=_resolution_from_manifest(manifest),
        licensing=_licensing(manifest),
        facts=_facts(manifest),
    )


def _version_summary(row: sqlite3.Row, namespace: str, name: str) -> VersionSummary:
    return VersionSummary(
        version=row["version"],
        artifact_digest=row["digest"],
        compile_success=bool(row["compile_success"]),
        yanked=bool(row["yanked"]),
        signed=_version_signed(row),
        needs_upgrade=bool(row["needs_upgrade"]) if "needs_upgrade" in row.keys() else False,
        resolution=_resolution_from_row(row),
        downloads=int(row["downloads"]) if "downloads" in row.keys() else 0,
        created_at=row["created_at"],
        changelog=row["changelog"],
        manifest_url=_manifest_url(namespace, name, row["version"]),
    )


def _version_signed(row: sqlite3.Row) -> bool:
    """Whether a version's stored manifest carries a signature (projected from manifest_json)."""
    if "manifest_json" not in row.keys() or not row["manifest_json"]:
        return False
    manifest = ModuleManifest.model_validate_json(row["manifest_json"])
    return manifest.signature is not None


def list_modules(
    repo: Repository,
    *,
    page: int,
    per_page: int,
    starred_by: Optional[int] = None,
    group: Optional[str] = None,
    test_pattern: str,
    **filters: object,
) -> Page[ModuleCard]:
    # A named group (all/featured/popular/new/test) is a preset over sort/featured/namespace-scope;
    # it wins over those raw filters. An explicit `namespace` still reaches a test/sandbox space by
    # exact name (so the exclusion the non-test groups apply is dropped in that case).
    preset = groups.group_filters(group, repo, test_pattern)
    if filters.get("namespace"):
        preset.pop("exclude_namespaces", None)
    filters.update(preset)
    rows, total = repo.search_modules(
        limit=per_page, offset=(page - 1) * per_page, **filters  # type: ignore[arg-type]
    )
    # Popularity: every module that surfaced in this result page takes one search-hit.
    repo.increment_search_hits([int(r["id"]) for r in rows])
    return Page[ModuleCard](
        items=[_card(repo, r, starred_by) for r in rows], total=total, page=page, per_page=per_page
    )


def module_detail(
    repo: Repository, namespace: str, name: str, starred_by: Optional[int] = None
) -> Optional[ModuleDetail]:
    row = repo.get_module_row(namespace, name)
    if row is None:
        return None
    card = _card(repo, row, starred_by)
    versions = repo.get_versions(row["id"])
    manifest = _latest_manifest(repo, row)
    data = card.model_dump()
    if manifest is not None:
        # Detail carries the FULL gene list (SPEC §8.3); only cards truncate.
        data["stats"] = manifest.stats.model_dump(include=set(CardStats.model_fields))
    return ModuleDetail(
        **data,
        readme=row["readme"],
        versions=[_version_summary(v, namespace, name) for v in versions],
        latest_manifest=manifest,
        verification=_verification(manifest),
        weighting=_weighting(manifest),
        gwas_effects=_gwas_effects(manifest),
    )


def version_page(
    repo: Repository, namespace: str, name: str, *, page: int, per_page: int
) -> Optional[Page[VersionSummary]]:
    row = repo.get_module_row(namespace, name)
    if row is None:
        return None
    all_versions = repo.get_versions(row["id"])
    start = (page - 1) * per_page
    window = all_versions[start : start + per_page]
    return Page[VersionSummary](
        items=[_version_summary(v, namespace, name) for v in window],
        total=len(all_versions),
        page=page,
        per_page=per_page,
    )


def get_manifest(
    repo: Repository, namespace: str, name: str, version: str
) -> Optional[ModuleManifest]:
    raw = repo.get_manifest_json(namespace, name, version)
    return ModuleManifest.model_validate_json(raw) if raw else None
