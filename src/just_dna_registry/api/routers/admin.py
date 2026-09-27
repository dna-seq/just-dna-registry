"""
Site-admin routes (0.28): acts that cross accounts, so no namespace or org role can authorize them.

Today that is one: merging an account whose key was lost into the one its owner carried on with.
Everything else a site admin does goes through the ordinary routes, elevated in
`deps.effective_role`, which is why this router is short.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from just_dna_registry.api.deps import (
    Account,
    get_repo,
    require_account,
    require_site_admin,
    settings_dep,
)
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.models.api import AccountMerge, MergeAccountsRequest
from just_dna_registry.services.accounts import merge_accounts

router = APIRouter(prefix="/admin", tags=["admin"])

RepoDep = Annotated[Repository, Depends(get_repo)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
AccountDep = Annotated[Account, Depends(require_account)]


@router.post("/accounts/{account}/merge", response_model=AccountMerge)
def merge(
    repo: RepoDep, settings: SettingsDep, caller: AccountDep, account: str, body: MergeAccountsRequest
) -> AccountMerge:
    """Fold `account` into `body.into`: namespaces, roles, authored versions, stars and reviews
    move, and `account`'s API keys are revoked. A dry run unless `apply` is true. Site admins only."""
    require_site_admin(caller)
    try:
        return merge_accounts(repo, settings, account, body.into, apply=body.apply)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
