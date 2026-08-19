"""
Read/catalog + download endpoints (SPEC §8.1–§8.5). All anonymous.
"""

import io
import tarfile
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from just_dna_format.manifest import ModuleManifest

from just_dna_registry.api.deps import (
    Account,
    Pagination,
    get_repo,
    get_storage,
    optional_account,
    pagination,
    rate_limit,
    require_account,
    settings_dep,
)
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.groups import GROUPS, GroupInfo
from just_dna_registry.models.api import (
    LookupBatch,
    LookupBatchResponse,
    LookupMatch,
    ModuleCard,
    ModuleDetail,
    Page,
    StarStatus,
    VersionRef,
    VersionSummary,
)
from just_dna_registry.services import catalog
from just_dna_registry.storage.base import StorageBackend, version_key

router = APIRouter(prefix="/modules", tags=["catalog"])

RepoDep = Annotated[Repository, Depends(get_repo)]
StorageDep = Annotated[StorageBackend, Depends(get_storage)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
PageDep = Annotated[Pagination, Depends(pagination)]
CallerDep = Annotated[Account | None, Depends(optional_account)]
AccountDep = Annotated[Account, Depends(require_account)]


def _refs(rows) -> list[VersionRef]:
    return [
        VersionRef(
            namespace=r["namespace"], name=r["name"], version=r["version"], yanked=bool(r["yanked"])
        )
        for r in rows
    ]


def _lookup_one(repo: Repository, *, digest: str | None, signature: str | None) -> LookupMatch:
    """Resolve one identity. Exactly one of `digest`/`signature` is set (the route enforces it)."""
    rows = (
        repo.find_versions_by_digest(digest)
        if digest is not None
        else repo.find_versions_by_content(signature or "")
    )
    return LookupMatch(digest=digest, signature=signature, matches=_refs(rows))


@router.get("", response_model=Page[ModuleCard], dependencies=[Depends(rate_limit("search"))])
def list_modules(
    repo: RepoDep,
    settings: SettingsDep,
    page: PageDep,
    caller: CallerDep,
    q: str | None = None,
    category: str | None = None,
    gene: str | None = None,
    genome_build: str | None = None,
    owner: str | None = None,
    license: str | None = None,
    namespace: str | None = None,
    featured: bool | None = None,
    include_blacklisted: bool = False,
    # Format-0.6 fact tables (0.17). Tri-state: omitted means "do not filter", which is not `false`.
    # Scoped to each module's current version, like `gene` and `category`.
    has_gene_validity: bool | None = Query(
        None, description="Modules whose latest version carries a ClinGen/GenCC validity table"
    ),
    has_clinical_assertions: bool | None = Query(
        None, description="Modules whose latest version carries a ClinVar clinical-assertion table"
    ),
    has_gwas_effects: bool | None = Query(
        None,
        description=(
            "Modules whose latest version carries published GWAS effect sizes. Read the detail's "
            "`gwas_effects.units` and `.without_effect_allele` before using them — more than one "
            "unit means the betas are on different scales and must not be pooled."
        ),
    ),
    has_frequencies: bool | None = Query(
        None, description="Modules whose latest version carries an allele-frequency table"
    ),
    weighting_declared: bool | None = Query(
        None,
        description=(
            "Modules that state what their authored `weight` column means. `false` finds the ones "
            "that have not said — which is not the same as saying their weights are comparable."
        ),
    ),
    group: str | None = Query(None, pattern="^(all|featured|curated|popular|new|test)$"),
    sort: str = Query("name", pattern="^(downloads|recent|name|stars|popular)$"),
) -> Page[ModuleCard]:
    return catalog.list_modules(
        repo,
        page=page.page,
        per_page=page.per_page,
        starred_by=caller.id if caller else None,
        group=group,
        test_pattern=settings.test_namespace_pattern,
        q=q,
        category=category,
        gene=gene,
        genome_build=genome_build,
        owner=owner,
        license=license,
        namespace=namespace,
        featured=featured,
        include_blacklisted=include_blacklisted,
        has_gene_validity=has_gene_validity,
        has_clinical_assertions=has_clinical_assertions,
        has_gwas_effects=has_gwas_effects,
        has_frequencies=has_frequencies,
        weighting_declared=weighting_declared,
        sort=sort,
    )


@router.get("/groups", response_model=list[GroupInfo])
def list_groups() -> list[GroupInfo]:
    """The listing groups (tabs) the catalog defines, for a UI to render — membership is server-owned
    policy (see `?group=` on the module listing). Static: `all|featured|popular|new|test`."""
    return GROUPS


@router.get("/lookup", response_model=LookupMatch, dependencies=[Depends(rate_limit("search"))])
def lookup(
    repo: RepoDep, digest: str | None = None, signature: str | None = None
) -> LookupMatch:
    """Find published versions by artifact digest **or** by content signature. Exactly one.

    Two identities, because they answer different questions and only one of them can answer the
    question a publisher actually has:

    * `digest` names the **compiled bytes** (SPEC §6) — "is this exact artifact published". It moves
      when the same spec is recompiled against a different reference, and it embeds the module name,
      so it moves on a rename too.
    * `signature` names the **authored data** — "is this module already published, under any name,
      compiled against any reference". This is what publish gates `409 duplicate_content` on, so it
      is the pre-check that can predict a rejection. A client computes it locally with
      `just_dna_compiler.compiler.content_signature(spec_dir)` — no upload and no recompile — which
      is what makes a pre-flight check possible at all.

    Anonymous, like the rest of the catalog reads: a content signature is not a secret, and someone
    about to publish a duplicate should not need an account to find that out.
    """
    if (digest is None) == (signature is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="lookup_needs_one_key"
        )
    return _lookup_one(repo, digest=digest, signature=signature)


@router.post(
    "/lookup", response_model=LookupBatchResponse, dependencies=[Depends(rate_limit("search"))]
)
def lookup_batch(
    repo: RepoDep, settings: SettingsDep, body: LookupBatch
) -> LookupBatchResponse:
    """Batch lookup — classify a whole local corpus in one request.

    Digests and signatures may be mixed in one call, which is usually what you want: a client
    holding both compiled modules and unpublished spec directories can ask about all of them at
    once. Each list is independently capped at `lookup_batch_max`.
    """
    digests = body.digests[: settings.lookup_batch_max]
    signatures = body.signatures[: settings.lookup_batch_max]
    return LookupBatchResponse(
        results=[_lookup_one(repo, digest=d, signature=None) for d in digests]
        + [_lookup_one(repo, digest=None, signature=s) for s in signatures]
    )


@router.get("/{namespace}/{name}", response_model=ModuleDetail)
def get_module(repo: RepoDep, caller: CallerDep, namespace: str, name: str) -> ModuleDetail:
    detail = catalog.module_detail(repo, namespace, name, starred_by=caller.id if caller else None)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="module_not_found")
    repo.increment_views(namespace, name)  # popularity: a real detail view is a view (anon counts)
    return detail


@router.get("/{namespace}/{name}/versions", response_model=Page[VersionSummary])
def list_versions(
    repo: RepoDep, page: PageDep, namespace: str, name: str
) -> Page[VersionSummary]:
    result = catalog.version_page(
        repo, namespace, name, page=page.page, per_page=page.per_page
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="module_not_found")
    return result


@router.get("/{namespace}/{name}/versions/{version}/manifest")
def get_manifest(repo: RepoDep, namespace: str, name: str, version: str) -> dict:
    manifest = catalog.get_manifest(repo, namespace, name, version)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    return manifest.model_dump()


@router.get("/{namespace}/{name}/versions/{version}/logs")
def list_logs(repo: RepoDep, namespace: str, name: str, version: str) -> dict:
    """List a version's optional provenance/run logs (§ manifest.logs), with fetch URLs."""
    manifest = catalog.get_manifest(repo, namespace, name, version)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    base = f"/api/v1/modules/{namespace}/{name}/versions/{version}/files"
    return {
        "items": [
            {"name": e.name, "sha256": e.sha256, "size": e.size, "url": f"{base}/{e.name}"}
            for e in manifest.logs
        ]
    }


@router.get("/{namespace}/{name}/versions/{version}/files/{file_path:path}")
def get_file(
    repo: RepoDep,
    storage: StorageDep,
    namespace: str,
    name: str,
    version: str,
    file_path: str,
) -> Response:
    """Serve (or redirect to) any file recorded in the manifest — artifact parquet, provenance
    log (e.g. `logs/reviewer.log`), or input — validated against the manifest listing.

    **The rule is "what the manifest attests", not a list maintained here**, which is why three
    files became reachable at 0.17 without this guard's logic changing: format 0.6 gave `readme`
    (S5) and `derived` (RM49) manifest entries, so the readme and the machine-written sidecars are
    now hashed records like everything else. Upstream endorsed keeping this refusal exactly as it
    is — the fix for prose a client could not verify was the missing attestation, not serving
    unhashed bytes — so the new names are added to `allowed` and nothing else moves.
    """
    manifest = catalog.get_manifest(repo, namespace, name, version)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    allowed = (
        {f.name for f in manifest.artifact.files}
        | {e.name for e in manifest.logs}
        | {e.name for e in manifest.inputs}
        | {e.name for e in manifest.derived or []}
    )
    if manifest.logo is not None:
        allowed.add(manifest.logo.name)
    if manifest.readme is not None:
        allowed.add(manifest.readme.name)
    if manifest.provenance is not None and manifest.provenance.file:
        allowed.add(manifest.provenance.file)
    if file_path not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file_not_found")

    # Count the real byte transfer of an artifact file (the parquet), whether served inline or via
    # a presigned/CDN redirect. Log/provenance/logo fetches are not downloads.
    if file_path in {f.name for f in manifest.artifact.files}:
        repo.increment_downloads(namespace, name)
        repo.increment_version_downloads(namespace, name, version)

    key = version_key(namespace, name, version)
    external = storage.file_url(key, file_path)
    if external is not None:
        return RedirectResponse(external, status_code=status.HTTP_302_FOUND)
    data = storage.read_file(key, file_path)
    return Response(content=data, media_type="application/octet-stream")


def _build_tarball(storage: StorageBackend, key: str, manifest: ModuleManifest) -> bytes:
    """Build a streamable tar.gz of the whole module version (manifest + artifact + logs + inputs).

    `manifest.json` comes from the DB manifest (authoritative); every other file is read from
    storage, skipping any optional ones (logs/inputs) not present. Deterministic (no mtimes).

    **"Whole" got closer to true at 0.17**, and only because the manifest can now say more. The
    entry list is deliberately the manifest's own — anything it does not attest is not shipped, so
    this tarball gained the readme and the machine-written sidecars the release format 0.6 gave them
    entries. Before that a tarball of a module was missing the very files needed to recompile it,
    which is the registry half of S26.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:

        def _add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        _add("manifest.json", manifest.model_dump_json(indent=2).encode("utf-8") + b"\n")
        entries = [
            *manifest.artifact.files,
            *manifest.logs,
            *manifest.inputs,
            *(manifest.derived or []),
        ]
        if manifest.logo is not None:
            entries.append(manifest.logo)
        if manifest.readme is not None:
            entries.append(manifest.readme)
        for entry in entries:
            if storage.exists(key, entry.name):
                _add(entry.name, storage.read_file(key, entry.name))
    return buf.getvalue()


@router.get(
    "/{namespace}/{name}/versions/{version}/download",
    dependencies=[Depends(rate_limit("download"))],
)
def download(
    repo: RepoDep,
    storage: StorageDep,
    namespace: str,
    name: str,
    version: str,
    format: str = Query("files", pattern="^(files|tarball)$"),
) -> Response:
    """
    `format=files` (default): per-file descriptors `{name, url, sha256, size}` for
    verify-then-install. `format=tarball`: a streamable `tar.gz` of the whole module version.
    """
    manifest = catalog.get_manifest(repo, namespace, name, version)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    repo.increment_downloads(namespace, name)
    repo.increment_version_downloads(namespace, name, version)
    key = version_key(namespace, name, version)

    if format == "tarball":
        data = _build_tarball(storage, key, manifest)
        return Response(
            content=data,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{name}-{version}.tar.gz"'},
        )

    base = f"/api/v1/modules/{namespace}/{name}/versions/{version}/files"
    files = [
        {
            "name": f.name,
            "url": storage.file_url(key, f.name) or f"{base}/{f.name}",
            "sha256": f.sha256,
            "size": f.size,
        }
        for f in manifest.artifact.files
    ]
    return JSONResponse({"digest": manifest.artifact.digest, "files": files})


def _star_status(repo: Repository, namespace: str, name: str, account_id: int) -> StarStatus:
    row = repo.get_module_row(namespace, name)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="module_not_found")
    return StarStatus(
        namespace=namespace, name=name, stars=int(row["stars"]),
        starred_by_me=repo.is_starred(int(row["id"]), account_id),
    )


@router.put(
    "/{namespace}/{name}/star",
    response_model=StarStatus,
    dependencies=[Depends(rate_limit("social"))],
)
def star_module(repo: RepoDep, account: AccountDep, namespace: str, name: str) -> StarStatus:
    """Star a module (GitHub-style favourite). Idempotent — starring twice keeps one star."""
    row = repo.get_module_row(namespace, name)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="module_not_found")
    repo.star_module(int(row["id"]), account.id)
    return _star_status(repo, namespace, name, account.id)


@router.delete(
    "/{namespace}/{name}/star",
    response_model=StarStatus,
    dependencies=[Depends(rate_limit("social"))],
)
def unstar_module(repo: RepoDep, account: AccountDep, namespace: str, name: str) -> StarStatus:
    """Remove the caller's star from a module. Idempotent."""
    row = repo.get_module_row(namespace, name)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="module_not_found")
    repo.unstar_module(int(row["id"]), account.id)
    return _star_status(repo, namespace, name, account.id)
