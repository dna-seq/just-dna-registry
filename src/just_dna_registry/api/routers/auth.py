"""Auth endpoints: static-key `whoami` (§8.8) + install-id self-registration (community onboarding)."""

import secrets
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from just_dna_format.identity import is_valid_namespace
from pydantic import BaseModel

from just_dna_registry.api.deps import (
    Account,
    get_repo,
    get_storage,
    rate_limit,
    refund_rate_charge,
    require_account,
    settings_dep,
)
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import HandleReserved, Repository
from just_dna_registry.installid import validate_install_id
from just_dna_registry.jwtauth import issue_jwt, jwt_enabled
from just_dna_registry.models.api import (
    AccountRename,
    ProfileUpdate,
    RenameSelfRequest,
    WhoAmI,
)
from just_dna_registry.services.accounts import RenameRefused, rename_account
from just_dna_registry.storage.base import StorageBackend

router = APIRouter(prefix="/auth", tags=["auth"])

RepoDep = Annotated[Repository, Depends(get_repo)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
StorageDep = Annotated[StorageBackend, Depends(get_storage)]


class RegisterRequest(BaseModel):
    install_id: str
    account: str


class TokenRequest(BaseModel):
    api_key: str


AccountDep = Annotated[Account, Depends(require_account)]


def _whoami(repo: Repository, account: Account) -> WhoAmI:
    row = repo.get_account(account.id)
    return WhoAmI(
        account=account.name,
        namespaces=account.namespaces,
        type=row["type"] if row else "user",
        display_name=row["display_name"] if row else None,
        avatar_url=row["avatar_url"] if row else None,
        funding_url=row["funding_url"] if row else None,
        email=row["email"] if row else None,
        site_admin=account.site_admin,
    )


@router.get("/whoami", response_model=WhoAmI)
def whoami(repo: RepoDep, account: AccountDep) -> WhoAmI:
    return _whoami(repo, account)


@router.patch("/whoami", response_model=WhoAmI)
def update_profile(repo: RepoDep, account: AccountDep, body: ProfileUpdate) -> WhoAmI:
    """Edit the caller's own profile (email / display_name / avatar_url / funding_url). Bearer = the
    account being edited; the `type` discriminator is not self-editable (set at creation)."""
    try:
        repo.set_account_profile(
            account.id, email=body.email, display_name=body.display_name,
            avatar_url=body.avatar_url, funding_url=body.funding_url,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email_taken") from exc
    return _whoami(repo, account)


@router.post("/tokens")
def issue_token(repo: RepoDep, settings: SettingsDep, body: TokenRequest) -> dict:
    """Exchange a static API key for a short-lived JWT session (optional; needs `jwt_secret`)."""
    if not jwt_enabled(settings):
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="jwt_disabled")
    row = repo.account_for_key(body.api_key)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    token, expires_in = issue_jwt(settings, account_id=int(row["id"]), name=row["name"])
    return {"token": token, "token_type": "Bearer", "expires_in": expires_in}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(repo: RepoDep, settings: SettingsDep, body: RegisterRequest) -> dict:
    """Self-service onboarding: a valid install-id (proof-of-work) mints an account + API key.

    Community-first — no admin/email. One account per install-id (re-registering an install-id
    just issues a fresh key for its existing account). The account may then claim up to
    `namespaces_per_account` namespaces.
    """
    if not settings.allow_self_register:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="self_register_disabled")
    if not validate_install_id(body.install_id, settings.install_id_difficulty):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_install_id")

    existing = repo.account_by_install_id(body.install_id)
    if existing is not None:
        account_id, name = int(existing["id"]), existing["name"]
    else:
        if not is_valid_namespace(body.account):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_account")
        # A retired handle is taken too (0.28): it stays reserved to the account that renamed.
        if repo.handle_taken(body.account) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="account_taken")
        try:
            account_id = repo.create_account_with_install_id(body.account, body.install_id)
        except HandleReserved as exc:  # retired between the check and the insert
            raise HTTPException(status.HTTP_409_CONFLICT, detail="account_taken") from exc
        name = body.account

    key = "mk_live_" + secrets.token_urlsafe(24)
    repo.add_api_key(key, account_id)
    return {"token": key, "account": name, "namespaces": repo.namespaces_for_account(account_id)}


def rename_refusal(exc: RenameRefused) -> HTTPException:
    """The one mapping from a refused rename to the wire, shared with the admin route."""
    code = status.HTTP_409_CONFLICT if exc.conflict else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"error": exc.code, "errors": [str(exc)]})


@router.post(
    "/rename", response_model=AccountRename, dependencies=[Depends(rate_limit("rename"))]
)
def rename(
    request: Request,
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    account: AccountDep,
    body: RenameSelfRequest,
) -> AccountRename:
    """Rename the caller's own handle (0.28). The old handle stays reserved to the account, and
    `owner` is amended on every manifest that names any handle of the account (outside the digest,
    so nothing published changes identity). `dry_run` reports and changes nothing.

    An org is renamed by a site admin (`POST /admin/accounts/{account}/rename`), at its owners' ask.
    """
    if repo.account_type(account.id) == "org":
        refund_rate_charge(request)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="org_rename_is_admin_only")
    try:
        report = rename_account(
            repo, storage, settings, account.name, body.name,
            apply=not body.dry_run, allow_test_data=body.allow_test_data,
        )
    except RenameRefused as exc:
        refund_rate_charge(request)  # refused before the work the bucket prices
        raise rename_refusal(exc) from exc
    if body.dry_run:
        refund_rate_charge(request)
    return report
