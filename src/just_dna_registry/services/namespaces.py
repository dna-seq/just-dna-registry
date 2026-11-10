"""
Renaming a namespace (0.29), shared by its HTTP route and its `registry` command so the two refuse
exactly the same things.

A namespace was immutable through 0.28 ("a namespace is never renamed", S28's decline). The person,
2026-11-10: "rename old to new, leave old one as alias pointer". What makes it possible is that the
namespace is registry-stamped: `_finalize` writes `identity.namespace` and `canonical_id` after the
compile, no compiled parquet carries it, and `artifact.digest`, `content_signature` and the signature
all leave it out. So a stored manifest is amended in place, as `amend_owner` amends `owner`.

Four rules keep the old name meaning what it meant:

* **The old name is an alias for good** (`namespace_aliases`). Every request addressed to it lands
  on the new name (`api/namespace_alias.py`), and every door that claims a namespace refuses it.
* **Storage first, then one transaction.** Each version's files are copied to the new key with the
  manifest amended; only when every copy landed do the catalog rows move, in one transaction. A
  failed copy moves nothing, and running the same rename again converges (copies overwrite).
* **Nothing is deleted.** The old copies stay where they were (the person's 3a), so a rename back is
  clean and an install holding a direct storage URL keeps working.
* **Renaming an alias renames its target**, and renaming back to one of its own aliases reclaims it.
"""

import logging
import sqlite3

from just_dna_format.identity import canonical_id, is_valid_namespace
from just_dna_format.manifest import ModuleManifest

from just_dna_registry.backup import create_backup
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import NamespaceChanged, NamespaceReserved, Repository
from just_dna_registry.db.schema import connect
from just_dna_registry.models.api import NamespaceRename, NamespaceVersionMove
from just_dna_registry.services.ingest import now_iso
from just_dna_registry.services.publish import _COMMIT_LOCK
from just_dna_registry.storage.base import StorageBackend, version_key
from just_dna_registry.testdata import accepted_anyway, override_hint, test_data_refusal

logger = logging.getLogger("registry.namespaces")


class NamespaceRenameRefused(ValueError):
    """A namespace rename this registry will not make. `code` is the wire's `detail`; `conflict` says
    whether it is a `409` (the name is somebody's) rather than a `422` (the request is refused)."""

    def __init__(self, code: str, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.conflict = conflict


def _amended(raw: str, new: str) -> str:
    manifest = ModuleManifest.model_validate_json(raw)
    manifest.identity.namespace = new
    manifest.identity.canonical_id = canonical_id(new, manifest.identity.name, manifest.identity.version)
    return manifest.model_dump_json(indent=2)


def rename_namespace(
    repo: Repository,
    storage: StorageBackend,
    settings: Settings,
    namespace: str,
    new: str,
    *,
    apply: bool,
    allow_test_data: bool = False,
    by_admin: bool = False,
) -> NamespaceRename:
    """Give namespace `namespace` the name `new`, keep the old name as its alias, and move every
    version: files copied to the new storage key, manifests amended, catalog rows renamed.

    `namespace` may be an alias; it resolves to the namespace it points to. Renaming to the current
    name moves nothing. Raises `LookupError` for an unknown namespace and `NamespaceRenameRefused` for a
    rename this registry will not make. A self-service caller (`by_admin=False`) is capped at
    `max_handle_aliases` aliases per namespace, as a handle is."""
    current = repo.resolve_namespace(namespace)
    if repo.namespace_owner(current) is None:
        raise LookupError(namespace)
    if not is_valid_namespace(new):
        raise NamespaceRenameRefused("invalid_namespace", f"{new!r} is not a valid namespace")
    held = repo.namespace_aliases_of(current)
    taken = repo.namespace_name_taken(new)
    if new != current and taken == "namespace":
        raise NamespaceRenameRefused("namespace_taken", f"{new!r} is taken", conflict=True)
    if taken == "alias" and repo.resolve_namespace(new) != current:
        raise NamespaceRenameRefused(
            "namespace_taken", f"{new!r} was renamed to {repo.resolve_namespace(new)}", conflict=True
        )
    # A name with catalogue rows or stored files and no grant (an account deleted with its versions
    # disowned) is not free either: the move would merge two catalogues, or overwrite the orphan's
    # files before the transaction refused. One of this namespace's own old names holds the copies it
    # kept, which is why renaming back is the exception.
    # Files an earlier attempt of this same rename copied there are its own and are overwritten.
    ours = {f"{v['name']}/{v['version']}" for v in repo.namespace_versions(current)}
    stray = [
        f for f in (storage.list_files(new) if new != current and new not in held else [])
        if "/".join(f.split("/", 2)[:2]) not in ours
    ]
    if new != current and new not in held and (repo.modules_in_namespace(new) or stray):
        raise NamespaceRenameRefused(
            "namespace_taken", f"{new!r} holds modules or stored files without an owner", conflict=True
        )
    warnings: list[str] = []
    if (
        new != current and test_data_refusal(current, "", settings) is not None
        and test_data_refusal(new, "", settings) is None
    ):
        warnings.append(
            f"{current} is a test- name and {new} is not: its modules become production-named, and "
            f"`purge-test-data` no longer reaches them"
        )
    refusal = test_data_refusal(new, "", settings) if new != current else None
    if refusal is not None:
        if not allow_test_data:
            raise NamespaceRenameRefused("test_data_on_prod", f"{refusal} {override_hint()}")
        warnings.append(accepted_anyway(refusal))

    renaming = new != current
    aliases_after = sorted({*held, current} - {new}) if renaming else held
    if renaming and not by_admin and len(aliases_after) > settings.max_handle_aliases:
        raise NamespaceRenameRefused(
            "alias_limit_reached",
            f"{current} already answers to {len(held)} older name(s) ({', '.join(held)}); each rename "
            f"keeps one reserved, and at most {settings.max_handle_aliases} may be. Renaming back to "
            f"one of them is allowed; anything else needs a site admin.",
            conflict=True,
        )

    rows = repo.namespace_versions(current) if renaming else []
    files = {
        (v["name"], v["version"]): storage.list_files(version_key(current, v["name"], v["version"]))
        for v in rows
    }
    report = NamespaceRename(
        namespace=current,
        name=new,
        applied=apply,
        aliases=aliases_after,
        modules=sorted({f"{new}/{v['name']}" for v in rows}),
        versions=[
            NamespaceVersionMove(
                version=f"{current}/{v['name']}@{v['version']}",
                to=f"{new}/{v['name']}@{v['version']}",
                files=len(files[(v["name"], v["version"])]),
            )
            for v in rows
        ],
        warnings=warnings,
    )
    if not apply or not renaming:
        return report

    if settings.auto_backup:
        taken_backup = create_backup(settings, reason=f"rename-namespace-{current}-to-{new}")
        report.snapshot = taken_backup.name if taken_backup is not None else None  # never a path

    # Storage first. A copy that fails leaves the catalog naming the old namespace, which still holds
    # every file, so nothing is lost and the same rename run again finishes it.
    manifests: dict[tuple[str, str], str] = {}
    for v in rows:
        name, version = v["name"], v["version"]
        old_key, new_key = version_key(current, name, version), version_key(new, name, version)
        body = _amended(v["manifest_json"], new)
        try:
            storage.copy_module(old_key, new_key, {"manifest.json": body.encode("utf-8") + b"\n"})
        except Exception as exc:  # noqa: BLE001 - any backend failure is one version's, reported
            logger.warning("namespace %s -> %s: %s not copied: %s", current, new, old_key, exc)
            report.failed.append(f"{current}/{name}@{version}: {type(exc).__name__}")
            continue
        manifests[(name, version)] = body
        report.copied += 1
    if report.failed:
        return report

    # Its own connection: the rename is one transaction, and the app's connection is shared across
    # threads (see `merge_accounts`).
    # Under the publish commit lock, so a publish in this process either committed under the old name
    # before (and the version check below refuses the move) or resolves the new one after.
    own = connect(settings.db_path)
    try:
        with _COMMIT_LOCK:
            Repository(own).rename_namespace_rows(current, new, manifests, retired_at=now_iso())
    except (NamespaceReserved, sqlite3.IntegrityError) as exc:  # claimed or renamed since the check
        raise NamespaceRenameRefused("namespace_taken", f"{new!r} is taken", conflict=True) from exc
    except NamespaceChanged as exc:
        # The copies already made stay under the new key and are overwritten by the re-run.
        raise NamespaceRenameRefused(
            "namespace_changed", f"{exc}; nothing in the catalog moved. Run the same rename again.",
            conflict=True,
        ) from exc
    finally:
        own.close()
    logger.warning("renamed namespace %s to %s (%d versions)", current, new, len(rows))
    return report
