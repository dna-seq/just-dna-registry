"""
Ingest: project a `ModuleManifest` into the catalog DB (module row + version row + facet rows).

Used by the publish finalize path (M4) and by seeding/tests. Kept separate from HTTP so a
manifest produced by the server-side compile can be indexed with one call.
"""

from datetime import UTC, datetime

from just_dna_format.manifest import ModuleManifest

from just_dna_registry.db.repository import Repository


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a trailing Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ingest_manifest(
    repo: Repository,
    manifest: ModuleManifest,
    *,
    changelog: str = "",
    created_at: str | None = None,
    published_by: int | None = None,
    readme: str | None = None,
) -> int:
    """
    Insert a published version into the projection and refresh the module's latest pointer.
    Returns the new version id. Assumes immutability was already checked upstream. `published_by`
    is the authoring account (RBAC own-scoping + author funding); None for seeds/legacy imports.

    `readme` is the spec's `README.md` text, threaded through because the manifest has no field to
    carry it (S5). `None` leaves any existing readme alone rather than clearing it — see
    `Repository.upsert_module`.
    """
    stamp = created_at or now_iso()
    module_id = repo.upsert_module(manifest, updated_at=stamp, readme=readme)
    version_id = repo.insert_version(
        module_id, manifest, changelog=changelog, created_at=stamp, published_by=published_by
    )
    repo.recompute_latest(module_id)
    return version_id
