"""
Sweep test data out of a live catalog: `registry purge-test-data`.

Planning is separated from applying because the plan is the safety feature. A dry run prints exactly
what would go, and `apply_purge` consumes that same object — so what an operator reads and what the
command does cannot drift, which they would if the CLI computed its own list a second time on `--apply`.

**The prefix never matches everything.** An empty or whitespace prefix returns an empty plan rather
than the whole catalog; the repository helpers refuse it independently. That is the one bug in this file
that would be indistinguishable from `reset-db` on a production box.

**The production guard does not make this command redundant, and never will.** `testdata.test_data_refusal`
refuses *new* test-prefixed publishes on a production instance; it prohibits nothing that is already
there. Everything published before the guard existed, everything on a box that was a polygon before it
was promoted, and everything a future prefix change reclassifies still has to be swept by hand. The two
are prospective and retrospective halves of the same job.

**Three populations, and only two are swept by default.** A prefixed *namespace* is unambiguously test
data and goes wholesale. A prefixed *module name* inside a **production** namespace is not: `test-panel`
under `just-dna-seq` may be someone's published module with users, and deleting it because of its name
would be unrecoverable. Those are collected, reported, and left alone unless `include_prod_namespaces`
says otherwise. The third population is the awkward one — a test *account* that published into a
production namespace — see `PurgePlan.disowned_versions`.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from just_dna_registry.storage.base import StorageBackend

logger = logging.getLogger("registry.purge")

#: What counts as test data by default. A prefix rather than a regex on purpose: an operator has to be
#: able to predict what a destructive command matches by reading the flag.
DEFAULT_PREFIX = "test-"


def module_name_prefix(prefix: str) -> str:
    """The same prefix as a **module name** can actually spell it.

    Namespaces and account handles allow hyphens (`test-sandbox`, `just-dna-seq`), but a module name is
    validated `lowercase alphanumeric with underscores` — so `test-panel` is not a module that exists to
    be purged, it is a `422` at publish. A single `--prefix test-` would therefore silently match no
    module ever, and the flag-gated production case would be unreachable rather than merely rare.

    Normalising here rather than asking operators to pass the prefix twice: one flag, applied to each
    identifier in the spelling that identifier permits.
    """
    return prefix.replace("-", "_")


@dataclass
class PurgePlan:
    """What a purge would remove. Printed verbatim by the dry run and applied unchanged by `--apply`."""

    prefix: str
    include_prod_namespaces: bool = False

    #: Namespaces whose *name* is prefixed. Swept wholesale — every module under them, then the grant.
    namespaces: list[str] = field(default_factory=list)
    #: `(namespace, name)` to hard-delete: everything under a prefixed namespace, plus prefixed module
    #: names in a prefixed namespace. Always safe to remove by the prefix rule.
    modules: list[tuple[str, str]] = field(default_factory=list)
    #: `(namespace, name, why)` — matched by name or by owner, but living in a **production** namespace.
    #: Reported and skipped unless `include_prod_namespaces`; moved into `modules` when it is set.
    modules_in_prod: list[tuple[str, str, str]] = field(default_factory=list)
    #: Accounts (users *and* orgs) whose handle is prefixed.
    accounts: list[tuple[int, str]] = field(default_factory=list)
    #: Production versions authored by an account being deleted. The module survives; only
    #: `versions.published_by` is set to NULL. Called out separately because it is the one case where a
    #: purge *mutates a production row* rather than removing test data, and an operator must see it.
    disowned_versions: list[tuple[str, str, str]] = field(default_factory=list)
    #: Artifact prefixes to remove, one per module actually being deleted.
    storage_keys: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.namespaces or self.modules or self.accounts)

    def describe(self) -> list[str]:
        """Human-readable, one finding per line — what the dry run prints."""
        lines: list[str] = []
        for ns in self.namespaces:
            lines.append(f"namespace   {ns} (freed)")
        for ns, name in self.modules:
            lines.append(f"module      {ns}/{name} + artifacts")
        for _id, name in self.accounts:
            lines.append(f"account     {name} (keys, memberships, org links)")
        for ns, name, version in self.disowned_versions:
            lines.append(
                f"disown      {ns}/{name}@{version} — kept, `published_by` cleared (production row)"
            )
        for ns, name, why in self.modules_in_prod:
            verdict = "WOULD REMOVE" if self.include_prod_namespaces else "SKIPPED"
            lines.append(f"prod module {ns}/{name} — {why} [{verdict}]")
        return lines


def plan_purge(
    repo: Any, *, prefix: str = DEFAULT_PREFIX, include_prod_namespaces: bool = False
) -> PurgePlan:
    """Work out what a purge would touch, without touching anything."""
    prefix = (prefix or "").strip()
    plan = PurgePlan(prefix=prefix, include_prod_namespaces=include_prod_namespaces)
    if not prefix:
        logger.warning("empty purge prefix — nothing matched (refusing to treat it as match-all)")
        return plan

    plan.namespaces = repo.namespaces_with_prefix(prefix)
    test_namespaces = set(plan.namespaces)

    # Everything inside a prefixed namespace, whatever the module is called.
    swept: set[tuple[str, str]] = set()
    for ns in plan.namespaces:
        for row in repo.modules_in_namespace(ns):
            swept.add((ns, row["name"]))

    # A prefixed module *name* is only safe to sweep when it sits in a prefixed namespace too. Matched
    # on the underscore spelling, since that is the only one a module name can have.
    for row in repo.modules_with_prefix(module_name_prefix(prefix)):
        key = (row["namespace"], row["name"])
        if key in swept:
            continue
        if row["namespace"] in test_namespaces:
            swept.add(key)
        else:
            plan.modules_in_prod.append((*key, f"name starts with {prefix!r}, namespace does not"))

    plan.accounts = [(int(r["id"]), r["name"]) for r in repo.accounts_with_prefix(prefix)]

    # Modules a test account owns via a namespace grant, and versions it published anywhere. An owned
    # namespace that is not prefixed is still that account's, so its modules are production data.
    for account_id, account_name in plan.accounts:
        for ns in repo.namespaces_for_account(account_id):
            if ns in test_namespaces:
                continue
            for row in repo.modules_in_namespace(ns):
                key = (ns, row["name"])
                if key not in swept:
                    plan.modules_in_prod.append(
                        (*key, f"namespace owned by {account_name!r}, which is being purged")
                    )

    if include_prod_namespaces:
        for ns, name, _why in plan.modules_in_prod:
            swept.add((ns, name))

    plan.modules = sorted(swept)
    plan.storage_keys = [f"{ns}/{name}" for ns, name in plan.modules]

    # Versions still authored by a purged account after the sweep — their module survives, so the
    # authorship pointer is cleared rather than the row deleted. Computed last, against the final sweep
    # set, or a module that is about to be deleted would be listed as needing to be disowned.
    doomed = set(plan.modules)
    for account_id, _name in plan.accounts:
        for row in repo.versions_published_by(account_id):
            key = (row["namespace"], row["name"])
            if key not in doomed:
                plan.disowned_versions.append((row["namespace"], row["name"], row["version"]))
    plan.disowned_versions.sort()
    return plan


def apply_purge(repo: Any, storage: Optional[StorageBackend], plan: PurgePlan) -> PurgePlan:
    """Execute `plan`. Ordered so no step leaves a foreign key dangling.

    Modules first (which cascades versions, facets, stars and reviews), then namespace grants, then the
    accounts — `delete_account` refuses to run while a version still points at it, so the order is not a
    style choice. Storage last, and only for modules whose rows are already gone: a failure there leaves
    orphaned bytes, which an operator can clean up, where the reverse order leaves rows pointing at
    artifacts that no longer exist.
    """
    if plan.is_empty:
        return plan

    for ns, name in plan.modules:
        repo.delete_module(ns, name)
    for ns in plan.namespaces:
        repo.delete_namespace_grant(ns)
    for account_id, name in plan.accounts:
        # `disown_versions` is safe here precisely because the plan already decided which modules die:
        # anything still pointing at this account is production data we are deliberately keeping.
        repo.delete_account(account_id, disown_versions=True)
        logger.info("purged account %s", name)
    if storage is not None:
        for key in plan.storage_keys:
            storage.remove(key)
    logger.info(
        "purge applied: %d module(s), %d namespace(s), %d account(s), %d version(s) disowned",
        len(plan.modules), len(plan.namespaces), len(plan.accounts), len(plan.disowned_versions),
    )
    return plan
