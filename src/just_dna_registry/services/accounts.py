"""
Account-level acts (0.28), each shared by its HTTP route and its `registry` command so the two
refuse exactly the same things: merging accounts (site admin) and renaming a handle (the account
itself, or a site admin).
"""

import logging
import sqlite3

from just_dna_format.identity import is_valid_namespace
from just_dna_format.manifest import ModuleManifest

from just_dna_registry.backup import create_backup
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import HandleReserved, Repository
from just_dna_registry.db.schema import connect
from just_dna_registry.models.api import AccountMerge, AccountRename
from just_dna_registry.services.ingest import now_iso
from just_dna_registry.storage.base import StorageBackend, version_key
from just_dna_registry.testdata import accepted_anyway, override_hint, test_data_refusal

logger = logging.getLogger("registry.auth")


def merge_accounts(
    repo: Repository, settings: Settings, source: str, into: str, *, apply: bool
) -> AccountMerge:
    """Fold `source` into `into` (see `Repository.merge_accounts`), snapshotting first on apply.

    Raises `LookupError` for an unknown account and `ValueError` for a pair that cannot merge."""
    source_row, into_row = repo.account_by_name(source), repo.account_by_name(into)
    for name, row in ((source, source_row), (into, into_row)):
        if row is None:
            raise LookupError(name)
    source_id, into_id = int(source_row["id"]), int(into_row["id"])
    if source_id == into_id:
        raise ValueError("same_account")
    # An org's roster is its members, so folding one into a person (or two orgs together) is a
    # different operation with different questions, and not what a lost key calls for.
    if repo.account_type(source_id) != "user" or repo.account_type(into_id) != "user":
        raise ValueError("not_a_user_account")
    snapshot = None
    if apply and settings.auto_backup:
        taken = create_backup(settings, reason=f"merge-{source}-into-{into}")
        snapshot = taken.name if taken is not None else None  # a name, never a path off the box
    # Its own connection, never the app's. The server shares one connection across threads, and
    # sqlite's transaction is per connection, so a dry run's rollback there would also undo whatever
    # another request had written and not yet committed — a publish could lose its row mid-flight.
    own = connect(settings.db_path)
    try:
        report = Repository(own).merge_accounts(source_id, into_id, apply=apply)
    finally:
        own.close()
    if apply:
        logger.warning("merged account %s into %s: %s", source, into, report)
    return AccountMerge(source=source, into=into, applied=apply, snapshot=snapshot, **report)


class RenameRefused(ValueError):
    """A rename this registry will not make. `code` is the wire's `detail`; `conflict` says whether
    it is a `409` (the handle is somebody's) rather than a `422` (the request itself is refused)."""

    def __init__(self, code: str, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.conflict = conflict


def rename_account(
    repo: Repository,
    storage: StorageBackend,
    settings: Settings,
    account: str,
    new: str,
    *,
    apply: bool,
    allow_test_data: bool = False,
    by_admin: bool = False,
) -> AccountRename:
    """Give `account` the handle `new`, keep the old one reserved to it, and amend `owner` on every
    stored manifest that names any handle of the account.

    `account` may be a retired handle; it resolves to the account that holds it now. Renaming to the
    current handle changes no row and still runs the amendment, which is how a sweep a storage error
    interrupted is finished: the amend set is *every manifest naming any of this account's handles*,
    so re-running converges, and it also catches a publish that stamped the old handle mid-rename.

    Raises `LookupError` for an unknown account and `RenameRefused` for a rename this registry will
    not make. The self-service caller (`by_admin=False`) is capped at `max_handle_aliases`.
    """
    row = repo.resolve_handle(account)
    if row is None:
        raise LookupError(account)
    account_id, current = int(row["id"]), row["name"]

    if not is_valid_namespace(new):
        raise RenameRefused("invalid_account", f"{new!r} is not a valid handle")
    holder = repo.handle_taken(new)
    if holder is not None and holder != account_id:
        raise RenameRefused("account_taken", f"{new!r} is taken", conflict=True)
    warnings: list[str] = []
    refusal = test_data_refusal(new, "", settings) if new != current else None
    if refusal is not None:
        if not allow_test_data:
            raise RenameRefused("test_data_on_prod", f"{refusal} {override_hint()}")
        warnings.append(accepted_anyway(refusal))

    held = repo.aliases_of(account_id)
    renaming = new != current
    aliases_after = sorted({*held, current} - {new}) if renaming else held
    if renaming and not by_admin and len(aliases_after) > settings.max_handle_aliases:
        raise RenameRefused(
            "alias_limit_reached",
            f"{current} already holds {len(held)} retired handle(s) ({', '.join(held)}); each rename "
            f"keeps one reserved, and at most {settings.max_handle_aliases} may be. Renaming back to "
            f"one of them is allowed; anything else needs a site admin.",
            conflict=True,
        )

    # Every handle the account has answered to except the one it is about to have. Read from the
    # manifests, not from `published_by`: `registry upgrade` publishes with none.
    names = sorted({*held, current} - {new})
    owned = repo.versions_owned_as(names) if names else []
    mine = [v for v in owned if v["published_by"] in (None, account_id)]

    def label(v: dict) -> str:
        return f"{v['namespace']}/{v['name']}@{v['version']}"

    report = AccountRename(
        account=current,
        name=new,
        applied=apply,
        aliases=aliases_after,
        versions=[label(v) for v in mine],
        versions_unattributed=[label(v) for v in mine if v["published_by"] is None],
        conflicts=[label(v) for v in owned if v["published_by"] not in (None, account_id)],
        modules=repo.modules_owned_as(names) if names else [],
        namespaces_kept=sorted(
            n for n in (*names, new) if repo.namespace_owner(n) is not None
        ),
        warnings=warnings,
    )
    if not apply:
        return report

    if settings.auto_backup and (renaming or mine):
        taken = create_backup(settings, reason=f"rename-{current}-to-{new}")
        report.snapshot = taken.name if taken is not None else None  # a name, never a path
    if renaming:
        # Its own connection: the rename is one transaction, and the app's connection is shared
        # across threads (see `merge_accounts`).
        own = connect(settings.db_path)
        try:
            Repository(own).rename_handle(account_id, new, retired_at=now_iso())
        except HandleReserved as exc:  # retired by somebody else since the check above
            raise RenameRefused("account_taken", f"{new!r} is taken", conflict=True) from exc
        except sqlite3.IntegrityError as exc:  # registered by somebody else since the check
            raise RenameRefused("account_taken", f"{new!r} is taken", conflict=True) from exc
        finally:
            own.close()
        logger.warning("renamed account %s (id %s) to %s", current, account_id, new)

    for v in mine:
        raw = repo.get_manifest_json(v["namespace"], v["name"], v["version"])
        if raw is None:  # deleted since the listing
            continue
        manifest = ModuleManifest.model_validate_json(raw)
        manifest.owner = new
        body = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
        # Storage first, then the projection: the amend set is read from the projection, so a
        # storage failure leaves the row naming the old handle and the next run picks it up again.
        try:
            storage.store_module(version_key(v["namespace"], v["name"], v["version"]),
                                 {"manifest.json": body})
        except Exception as exc:  # noqa: BLE001 - any backend failure is one version's, reported
            logger.warning("rename %s -> %s: %s not amended: %s", current, new, label(v), exc)
            report.failed.append(f"{label(v)}: {type(exc).__name__}")
            continue
        repo.set_version_manifest(v["namespace"], v["name"], v["version"], manifest)
        report.amended += 1
    if names:
        repo.set_modules_owner(names, new)
    return report
