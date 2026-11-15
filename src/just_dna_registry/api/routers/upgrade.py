"""`GET /upgrade/status` (0.32): which current versions `registry upgrade` has not brought up to date.

**Anonymous, codes only.** Which published module is behind, and by which code a sweep left it, is a
catalog fact about modules anyone can list; the run's sentences, detail and id stay behind
`GET /admin/runs/{id}` (site admins, the person's 2026-11-07 ruling). The module set is the listing's
own (`Repository.current_versions_for_status`), so nothing the listing hides is named here. The logic,
and why there are two witnesses, is `services/upgrade_status.py`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from just_dna_registry.api.deps import get_repo, rate_limit, settings_dep
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.models.api import UpgradeStatusReport
from just_dna_registry.services.upgrade_status import STATES, upgrade_status

router = APIRouter(tags=["ops"])

SettingsDep = Annotated[Settings, Depends(settings_dep)]
RepoDep = Annotated[Repository, Depends(get_repo)]


@router.get(
    "/upgrade/status",
    response_model=UpgradeStatusReport,
    summary="Which current versions the upgrade sweep has not brought up to date",
    dependencies=[Depends(rate_limit("search"))],
)
async def upgrade_status_route(
    settings: SettingsDep,
    repo: RepoDep,
    state: str | None = Query(None, pattern=f"^({'|'.join(STATES)})$",
                              description="Only items in this state; `counts` always covers all"),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=100),
) -> UpgradeStatusReport:
    """Every listed module's current version with its state: `held`, `would_upgrade`, `behind`, `unknown`
    or `current`, the newest recorded sweep's verdict on it, and the compiler comparison.

    Reads the catalog and the run records on this box (one small JSON per `upgrade` run), never storage,
    on a threadpool worker."""
    return await run_in_threadpool(
        upgrade_status, settings, repo, state=state, page=page, per_page=per_page
    )
