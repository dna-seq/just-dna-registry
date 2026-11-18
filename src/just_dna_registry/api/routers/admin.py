"""
Site-admin routes (0.28): acts that cross accounts, so no namespace or org role can authorize them.

Merging an account whose key was lost into the one its owner carried on with, renaming any account's
handle (an org's included, which its owners cannot do themselves), reading maintenance runs (0.28.3), and
moving the box to another release (0.34, `services/deploy.py`). Everything else a site admin does goes through the ordinary routes, elevated in
`deps.effective_role`, which is why this router is short.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from just_dna_registry import __version__
from just_dna_registry.api.deps import (
    Account,
    Pagination,
    get_repo,
    get_storage,
    pagination,
    require_account,
    require_site_admin,
    settings_dep,
)
from just_dna_registry.api.routers.auth import rename_refusal
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.models.api import (
    AccountMerge,
    AccountRename,
    DeployRecord,
    DeployRequest,
    DeployStatus,
    MergeAccountsRequest,
    Page,
    RenameAccountRequest,
    RunDetail,
    RunSummary,
)
from just_dna_registry.services.accounts import RenameRefused, merge_accounts, rename_account
from just_dna_registry.services.deploy import DeployRefused, deploy_status, request_deploy
from just_dna_registry.services.runs import (
    DIAGNOSTIC_COMMANDS,
    list_served_runs,
    run_detail,
    run_log,
)
from just_dna_registry.storage.base import StorageBackend

router = APIRouter(prefix="/admin", tags=["admin"])

RepoDep = Annotated[Repository, Depends(get_repo)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
AccountDep = Annotated[Account, Depends(require_account)]
StorageDep = Annotated[StorageBackend, Depends(get_storage)]


@router.post("/accounts/{account}/merge", response_model=AccountMerge)
def merge(
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    caller: AccountDep,
    account: str,
    body: MergeAccountsRequest,
) -> AccountMerge:
    """Fold `account` into `body.into`: namespaces, roles, authored versions, stars and reviews
    move, and `account`'s API keys are revoked. A dry run unless `apply` is true. Site admins only."""
    require_site_admin(caller)
    try:
        return merge_accounts(repo, settings, account, body.into, apply=body.apply, storage=storage)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/accounts/{account}/rename", response_model=AccountRename)
def rename(
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    caller: AccountDep,
    account: str,
    body: RenameAccountRequest,
) -> AccountRename:
    """Rename `account` (a user or an org; a retired handle resolves) to `body.name`, keep the old
    handle reserved to it, and amend `owner` on every manifest naming it. A dry run unless `apply`
    is true. Site admins only, and not held to `max_handle_aliases`."""
    require_site_admin(caller)
    try:
        return rename_account(
            repo, storage, settings, account, body.name,
            apply=body.apply, allow_test_data=body.allow_test_data, by_admin=True,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account_not_found") from exc
    except RenameRefused as exc:
        raise rename_refusal(exc) from exc


# ── Maintenance runs (0.28.3): the enricher-facing runs' records, sweeps and logs ──────────────────
# Read-only and not rate-limited, like the routes above: a site admin's key is the gate. Paths are
# scrubbed in `services/runs.py`; a run of a command outside `DIAGNOSTIC_COMMANDS` is a 404.


@router.get("/runs", response_model=Page[RunSummary])
def runs(
    settings: SettingsDep,
    caller: AccountDep,
    pages: Annotated[Pagination, Depends(pagination)],
    command: Annotated[str | None, Query(description="One command's runs only")] = None,
) -> Page[RunSummary]:
    """The maintenance runs of the enricher-facing commands (`upgrade`, `replay-upgrade`, `revalidate`,
    `warm-caches`) on this box, newest first. Site admins only."""
    require_site_admin(caller)
    if command is not None and command not in DIAGNOSTIC_COMMANDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"command must be one of {sorted(DIAGNOSTIC_COMMANDS)}",
        )
    items, total = list_served_runs(settings, command=command, page=pages.page, per_page=pages.per_page)
    return Page[RunSummary](items=items, total=total, page=pages.page, per_page=pages.per_page)


@router.get("/runs/{run_id}", response_model=RunDetail)
def run(settings: SettingsDep, caller: AccountDep, run_id: str) -> RunDetail:
    """One run's record and, for a sweep kept from 0.28.3 on, every module's status, code, detail and
    warning counts. Site admins only."""
    require_site_admin(caller)
    detail = run_detail(settings, run_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run_not_found")
    return detail


@router.get("/runs/{run_id}/log", response_class=PlainTextResponse)
def run_log_text(
    settings: SettingsDep,
    caller: AccountDep,
    run_id: str,
    tail: Annotated[int | None, Query(ge=1, description="Only the last N lines")] = None,
) -> PlainTextResponse:
    """The run's `run.log` as text, filesystem paths replaced by labels. Site admins only."""
    require_site_admin(caller)
    text = run_log(settings, run_id, tail=tail)
    if text is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run_not_found")
    return PlainTextResponse(text)


# ── Deploy over the API (0.34): `services/deploy.py` checks and records, `registry supervise` moves ──────
# Not rate-limited, like the routes above: a site admin's key is the gate, and `REGISTRY_DEPLOY` (off by
# default) is the operator's.


@router.get("/deploy", response_model=DeployStatus)
def deploy_state(settings: SettingsDep, caller: AccountDep) -> DeployStatus:
    """What this box runs, what it ran before, a waiting request, and how the last moves went. Site admins
    only."""
    require_site_admin(caller)
    return DeployStatus.model_validate(deploy_status(settings, running=__version__))


@router.post("/deploy", response_model=DeployRecord, status_code=status.HTTP_202_ACCEPTED)
def deploy(settings: SettingsDep, caller: AccountDep, body: DeployRequest, request: Request) -> DeployRecord:
    """Ask the supervisor to move this box to `body.version`: a release tag on a clone, a published version
    on a PyPI install, or `previous`. `202`: the move runs after this answer, and `GET /admin/deploy` reports
    it; a move that does not come up is rolled back. Refused (`409`) when the box is not enabled or not
    supervised, a move is already waiting, a maintenance run or a publish is going, or the version already
    serves; `422` for a version that is no release or predates the route. Site admins only."""
    require_site_admin(caller)
    try:
        record = request_deploy(
            settings, body.version, requested_by=caller.name, running=__version__,
            gate_occupancy=request.app.state.enrichment_gate.occupancy(),
        )
    except DeployRefused as exc:
        raise HTTPException(exc.status, detail={"error": exc.code, "errors": [exc.message]}) from exc
    return DeployRecord.model_validate(record)
