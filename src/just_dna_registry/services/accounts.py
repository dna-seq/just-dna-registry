"""
Account-level operator acts (0.28), shared by `POST /admin/accounts/{account}/merge` and
`registry merge-accounts` so the two refuse exactly the same things.
"""

import logging

from just_dna_registry.backup import create_backup
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect
from just_dna_registry.models.api import AccountMerge

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
