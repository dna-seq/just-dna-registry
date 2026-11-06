"""`GET /stats` (0.28): catalog totals in one request, where `RegistryClient.catalog_stats()` used to
page the whole listing. Kept off `/health`, which stays cheap and probeable."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from just_dna_registry.api.deps import get_repo, rate_limit, settings_dep
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.models.api import CatalogStats
from just_dna_registry.services import catalog

router = APIRouter(tags=["modules"])

RepoDep = Annotated[Repository, Depends(get_repo)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]


@router.get("/stats", response_model=CatalogStats, dependencies=[Depends(rate_limit("search"))])
def stats(
    repo: RepoDep,
    settings: SettingsDep,
    namespace: str | None = None,
    group: str | None = Query(None, pattern="^(all|featured|curated|popular|new|test)$"),
) -> CatalogStats:
    """Totals over the modules `GET /modules` lists with the same `namespace` and `group`."""
    return catalog.catalog_stats(
        repo, namespace=namespace, group=group,
        test_pattern=settings.test_namespace_pattern, is_test_instance=settings.is_test_instance,
    )
