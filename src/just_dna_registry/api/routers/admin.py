"""
Site-admin routes (0.28): acts that cross accounts, so no namespace or org role can authorize them.

Two: merging an account whose key was lost into the one its owner carried on with, and renaming
any account's handle (an org's included, which its owners cannot do themselves). Everything else a site admin does goes through the ordinary routes, elevated in
`deps.effective_role`, which is why this router is short.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from just_dna_registry.api.deps import (
    Account,
    get_repo,
    get_storage,
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
    MergeAccountsRequest,
    RenameAccountRequest,
)
from just_dna_registry.services.accounts import RenameRefused, merge_accounts, rename_account
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
