"""The variant-level catalog's routes (0.31): what published modules say about one variant or one gene.

An authoring surface: one key per request, no batch and no genotype parameter, so it is never a per-person
annotation service (docs/STRATEGY.md). Visibility follows the listing: latest non-yanked versions, no
blacklisted namespace, and on production no test/sandbox one. It reports what modules say; the conflict
marker is a fact about two modules' statements, never a verdict, and nothing here ranks one claim above
another.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from just_dna_registry import groups
from just_dna_registry.api.deps import get_repo, rate_limit, settings_dep
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.services import claims as claims_service

router = APIRouter(tags=["catalog"])
RepoDep = Annotated[Repository, Depends(get_repo)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]


class Conflicts(BaseModel):
    pairs: list[dict[str, Any]] = Field(
        description="Two modules giving one allele opposite directions, same genotype and trait"
    )
    compared: int = Field(description="Pairs that met every condition and were compared")
    incomparable: dict[str, int] = Field(
        description="Pairs not compared, by reason (no_trait, other_trait, other_effect_allele, ...)"
    )


class VariantClaims(BaseModel):
    key: str
    variant_keys: list[str] = Field(description="Every key the spelling asked for resolves to")
    claims: list[dict[str, Any]]
    modules: list[str]
    conflicts: Conflicts
    not_projected: int = Field(
        description="Visible modules whose latest version has no projection yet: absent here is not 'says nothing'"
    )


class GeneClaims(BaseModel):
    gene: str
    claims: list[dict[str, Any]]
    modules: list[str]
    variants: int
    not_projected: int


def _exclude(repo: Repository, settings: Settings) -> list[str]:
    preset = groups.group_filters(None, repo, settings.test_namespace_pattern, is_test_instance=settings.is_test_instance)
    return list(preset.get("exclude_namespaces") or [])


@router.get("/variants", response_model=VariantClaims, dependencies=[Depends(rate_limit("search"))])
def variant_claims(
    request: Request,
    repo: RepoDep,
    settings: SettingsDep,
    key: Annotated[str, Query(min_length=3, max_length=500, description="rsID, VRS id or chrom:start:ref:alt")],
) -> VariantClaims:
    """What every visible module's latest version says about one variant, by any spelling of it."""
    return VariantClaims(**claims_service.variant_claims(repo, key.strip(), exclude_namespaces=_exclude(repo, settings)))


@router.get("/genes/{symbol}/claims", response_model=GeneClaims, dependencies=[Depends(rate_limit("search"))])
def gene_claims(request: Request, repo: RepoDep, settings: SettingsDep, symbol: str) -> GeneClaims:
    """What every visible module's latest version says about variants it names under this gene (authored genes
    only; a gene is never assigned to a row by its position)."""
    if not symbol.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="gene_needed")
    return GeneClaims(**claims_service.gene_claims(repo, symbol.strip(), exclude_namespaces=_exclude(repo, settings)))
