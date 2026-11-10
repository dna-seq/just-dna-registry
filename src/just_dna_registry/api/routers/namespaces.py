"""Namespace availability + self-service claim (community onboarding, 0.3)."""

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
    require_capability,
    settings_dep,
)
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import NamespaceReserved, Repository
from just_dna_registry.models.api import (
    ALIAS_HEADER,
    AddMemberRequest,
    MemberEntry,
    MemberList,
    NamespaceRename,
    NamespaceRenameRequest,
)
from just_dna_registry.permissions import VALID_NS_ROLES, Capability
from just_dna_registry.services.namespaces import NamespaceRenameRefused, rename_namespace
from just_dna_registry.storage.base import StorageBackend
from just_dna_registry.testdata import accepted_anyway, override_hint, test_data_refusal

router = APIRouter(prefix="/namespaces", tags=["namespaces"])

RepoDep = Annotated[Repository, Depends(get_repo)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
AccountDep = Annotated[Account, Depends(require_account)]
StorageDep = Annotated[StorageBackend, Depends(get_storage)]


class ClaimRequest(BaseModel):
    namespace: str
    #: Claim a `test-`prefixed namespace on production deliberately (0.14). Default off, so the guard
    #: still catches the typo it was built for; explicit, so holding test data in production is
    #: something a caller says rather than something that happens.
    allow_test_data: bool = False


@router.get("/{namespace}")
def availability(repo: RepoDep, settings: SettingsDep, namespace: str) -> dict:
    """Whether a namespace is free to claim (public).

    `valid` is about the *name*, `available` about who holds it — two different refusals
    (`422 invalid_namespace` vs `409 namespace_taken`), which is why they stay two fields.

    **`warnings` is the third thing, and it exists because this pre-flight used to contradict the
    operation it predicts (S6).** A `test-`prefixed name on production answered `valid: true,
    available: true` and then met `422 test_data_on_prod` — the read-only check for an irreversible
    act reporting the opposite of what the act would do.

    It is a warning rather than `valid: false` — which is what the report asked for — because the
    policy moved underneath it in the same release: since 0.14 such a name *is* claimable here, with
    `allow_test_data=true`. Calling it invalid would be the same contradiction rewritten backwards.
    """
    warnings = [w for w in (test_data_refusal(namespace, "", settings),) if w]
    return {
        "namespace": namespace,
        "valid": is_valid_namespace(namespace),
        "available": repo.namespace_owner(namespace) is None,
        # Machine-readable, so a caller branches on this rather than on the prose beside it.
        "requires_allow_test_data": bool(warnings),
        "warnings": [f"{w} {override_hint()}" for w in warnings],
        # The names this namespace renamed away from (0.29). Asked by one of them, the path was
        # already resolved to this namespace, so `namespace` names the current one and
        # `X-Namespace-Current` says so; `available` is then false, as the claim would be refused.
        "aliases": repo.namespace_aliases_of(namespace),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def claim(repo: RepoDep, settings: SettingsDep, account: AccountDep, body: ClaimRequest) -> dict:
    """Claim an available namespace for the caller's account (up to `namespaces_per_account`)."""
    namespace = body.namespace
    if not is_valid_namespace(namespace):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_namespace")
    # A production instance refuses to *create* test-prefixed namespaces as well as to publish into
    # them (0.12). Blocking only the publish would leave the name claimed and the caller's quota spent
    # on a namespace nothing can ever be pushed to.
    #
    # Since 0.14 the refusal is overridable rather than absolute: it stays the default so a typo is
    # still caught, and `allow_test_data=true` is how a caller who means it proceeds.
    refusal = test_data_refusal(namespace, "", settings)
    warnings: list[str] = []
    if refusal is not None:
        if not body.allow_test_data:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "test_data_on_prod", "errors": [f"{refusal} {override_hint()}"]},
            )
        warnings.append(accepted_anyway(refusal))

    if repo.namespace_name_taken(namespace) == "alias":
        # A name another namespace renamed away from (0.29). The detail stays the string clients
        # compare; the current name rides in a header, as every new fact about a refusal does.
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="namespace_taken",
            headers={ALIAS_HEADER: repo.resolve_namespace(namespace)},
        )
    owner = repo.namespace_owner(namespace)
    if owner is not None:
        if int(owner["account_id"]) == account.id:
            return {
                "namespace": namespace, "owner": account.name, "already_owned": True,
                "warnings": warnings,
            }
        raise HTTPException(status.HTTP_409_CONFLICT, detail="namespace_taken")

    if repo.count_namespaces_for_account(account.id) >= settings.namespaces_per_account:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="namespace_limit_reached")

    try:
        repo.add_namespace(namespace, account.id)
    except NamespaceReserved as exc:  # renamed into an alias since the check above
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="namespace_taken", headers={ALIAS_HEADER: exc.current}
        ) from exc
    return {
        "namespace": namespace, "owner": account.name, "already_owned": False, "warnings": warnings,
    }


@router.get("/{namespace}/members", response_model=MemberList)
def list_members(repo: RepoDep, account: AccountDep, namespace: str) -> MemberList:
    """List a namespace's members. Any member may read the roster."""
    require_capability(repo, account, namespace, Capability.PUBLISH)  # any role has PUBLISH
    return MemberList(
        namespace=namespace,
        members=[MemberEntry(account=r["account"], role=r["role"]) for r in repo.list_members(namespace)],
    )


@router.post("/{namespace}/members", status_code=status.HTTP_201_CREATED, response_model=MemberList)
def add_member(
    repo: RepoDep, account: AccountDep, namespace: str, body: AddMemberRequest
) -> MemberList:
    """Add or re-role an account in a namespace. Adding a `member` needs manage-members (admin+);
    granting `admin`/`owner` needs manage-roles (owner)."""
    require_capability(repo, account, namespace, Capability.MANAGE_MEMBERS)
    if body.role not in VALID_NS_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_role")
    if body.role in ("owner", "admin"):
        require_capability(repo, account, namespace, Capability.MANAGE_ROLES)
    target = repo.account_by_name(body.account)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account_not_found")
    repo.add_member(namespace, int(target["id"]), body.role)
    return MemberList(
        namespace=namespace,
        members=[MemberEntry(account=r["account"], role=r["role"]) for r in repo.list_members(namespace)],
    )


@router.delete("/{namespace}/members/{member}", response_model=MemberList)
def remove_member(
    repo: RepoDep, account: AccountDep, namespace: str, member: str
) -> MemberList:
    """Revoke an account's access to a namespace (removes the membership row — namespace-scoped, not
    a global key revocation). Needs manage-members (admin+); removing an **owner** needs manage-roles
    (owner). Refuses to remove the last owner."""
    require_capability(repo, account, namespace, Capability.MANAGE_MEMBERS)
    target = repo.account_by_name(member)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account_not_found")
    target_role = repo.namespace_role(namespace, int(target["id"]))
    if target_role == "owner":
        require_capability(repo, account, namespace, Capability.MANAGE_ROLES)  # only owners remove owners
        if repo.count_namespace_owners(namespace) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="last_owner")
    if not repo.remove_member(namespace, int(target["id"])):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_a_member")
    return MemberList(
        namespace=namespace,
        members=[MemberEntry(account=r["account"], role=r["role"]) for r in repo.list_members(namespace)],
    )


@router.post(
    "/{namespace}/rename", response_model=NamespaceRename, dependencies=[Depends(rate_limit("rename"))]
)
def rename(
    request: Request,
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    account: AccountDep,
    namespace: str,
    body: NamespaceRenameRequest,
) -> NamespaceRename:
    """Rename a namespace (0.29). Its owner may, and a site admin may rename any (an owner everywhere).

    Every version moves: its files are copied to the new storage path and its manifest's
    `identity.namespace` and `canonical_id` amended (registry-stamped, outside `artifact.digest`,
    `content_signature` and the signature, so nothing published changes identity). The old name stays
    an alias: reads and publishes addressed to it land here, and nobody else may claim it. The old
    copies are kept. `dry_run` (the default) reports and changes nothing.
    """
    # The path was already resolved through any alias (`NamespaceAliasMiddleware`).
    require_capability(repo, account, namespace, Capability.MANAGE_ROLES)
    try:
        report = rename_namespace(
            repo, storage, settings, namespace, body.name,
            apply=not body.dry_run, allow_test_data=body.allow_test_data, by_admin=account.site_admin,
        )
    except NamespaceRenameRefused as exc:
        refund_rate_charge(request)  # refused before the work the bucket prices
        code = status.HTTP_409_CONFLICT if exc.conflict else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(code, detail={"error": exc.code, "errors": [str(exc)]}) from exc
    if body.dry_run:
        refund_rate_charge(request)
    if report.failed:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"error": "storage_failed", "errors": report.failed},
        )
    return report
