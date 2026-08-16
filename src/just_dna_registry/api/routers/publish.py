"""
Publish + yank endpoints (SPEC §8.6–§8.7, §8.9).

Publishing is the trust-bearing path: the client uploads the **spec only** as multipart form-data
(the SPEC-sanctioned MVP alternative to presigned PUT); the server validates + recompiles it,
stores the compiled version, and indexes it. Guards run in order — auth (401), namespace ownership
(403), version format (422), immutability (409) — before any compile work.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from just_dna_format.identity import is_valid_version
from just_dna_format.vocab import VALID_DECLARED_USE
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from just_dna_registry.api.deps import (
    Account,
    get_repo,
    get_storage,
    rate_limit,
    settings_dep,
    require_account,
    require_capability,
)
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.lowpriority import run_at_low_priority
from just_dna_registry.models.api import CheckReport, ValidationReport
from just_dna_registry.permissions import Capability
from just_dna_registry.services import enrich as enrich_service
from just_dna_registry.services import publish as publish_service
from just_dna_registry.specfiles import REQUIRED_SPEC_FILES
from just_dna_registry.storage.base import StorageBackend, version_key

router = APIRouter(prefix="/modules", tags=["publish"])

RepoDep = Annotated[Repository, Depends(get_repo)]
StorageDep = Annotated[StorageBackend, Depends(get_storage)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
AccountDep = Annotated[Account, Depends(require_account)]


#: PublishError details that are not "your spec is unprocessable" and get their own status.
#: `duplicate_content` is a content-identity conflict (this data is already published under another
#: name) — a 409, like `version_exists`. `upload_too_large` is about the request body rather than the
#: spec inside it, which is what 413 means. Everything else, including a too-large *module* that
#: arrived in a perfectly legal body, is 422.
_PUBLISH_ERROR_STATUS: dict[str, int] = {
    "duplicate_content": status.HTTP_409_CONFLICT,
    "upload_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    # Same family as `upload_too_large` — too much payload — so the same status. Distinct name
    # because the fix is different: this one is not solved by compressing harder.
    "archive_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
}


def _publish_http_error(exc: "publish_service.PublishError") -> HTTPException:
    """Map a PublishError to its HTTP status and the registry's structured error body."""
    code = _PUBLISH_ERROR_STATUS.get(exc.detail, status.HTTP_422_UNPROCESSABLE_CONTENT)
    return HTTPException(
        code,
        detail={
            # Spread first, so the four fixed keys win any collision and no refusal can redefine
            # the shape every client branches on.
            **exc.extra,
            "error": exc.detail,
            "errors": exc.errors,
            "warnings": exc.warnings,
            # What the server changed about the spec but accepted — dropped authority keys, a
            # coerced `module.version`. Visible on a failure too, because "we rewrote this" is
            # often the context that explains the error beside it.
            "info": exc.info,
        },
    )


async def _queue_for_enrichment(
    request: Request, settings: Settings, label: str
) -> Optional["enrich_service.EnrichmentGate"]:
    """Wait — with no deadline — for an enrichment permit no `/check` wants. `None` if none is needed.

    A publish is not a dry run, but when `enrich_offline` is false it egresses through exactly the
    same clients on exactly the same IP-scoped budget, so it has to count against the same
    process-wide occupancy. Ungated, two concurrent online publishes would double the outbound rate
    `PacingGate` exists to hold — and, because the bundle is shared, race a dataclass with no lock.

    **It queues rather than failing, and that is the deliberate difference from `/check`.** A dry run
    has someone waiting on the answer, so a full gate is a fast `503`. A publish has nobody waiting
    and an upload already spent, so `503` would mean re-uploading a module for a reason that will
    have evaporated in thirty seconds. There is therefore no cap on how long this waits, and the
    request is not subject to `enrich_timeout_seconds` either.

    Taken *conditionally*: on the default offline deployment a publish reaches nothing, so it neither
    queues nor holds a permit — serializing it behind a limit of 1 would be a throughput cost paid
    against a risk that is not present.
    """
    if not (settings.enrich_enabled and not settings.enrich_offline):
        return None
    gate = request.app.state.enrichment_gate
    await gate.acquire_idle(label=label)
    return gate


async def _run_queued(
    fn, gate: Optional["enrich_service.EnrichmentGate"], settings: Settings, /, **kwargs
):
    """Run a publish on the low-priority thread, holding `gate` until the *worker* releases it.

    The permit is released inside `fn`'s own `finally`, not here, because a client that hangs up
    mid-publish cancels the await and not the thread — releasing on this side would free the gate
    while a run is still spending against it. The one case that leaves nothing to release is the
    worker never starting at all, which is what the `RuntimeError` arm covers: `submit` raises it
    when a thread cannot be created. That would otherwise strand the permit forever, and since
    publishes now queue without a deadline, a stranded permit with a limit of 1 does not degrade
    throughput — it hangs every subsequent publish for the life of the process.
    """
    try:
        return await run_at_low_priority(fn, settings.publish_nice, gate=gate, **kwargs)
    except RuntimeError:
        if gate is not None:
            gate.release()
        raise


class YankRequest(BaseModel):
    yanked: bool = True


class ChangelogPatch(BaseModel):
    changelog: str
    append: bool = False  # append to the existing changelog instead of replacing it


@router.post(
    "/{namespace}/{name}/versions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("publish"))],
)
async def publish(
    request: Request,
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    account: AccountDep,
    namespace: str,
    name: str,
    version: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    changelog: Annotated[str, Form()] = "",
    allow_test_data: Annotated[bool, Form()] = False,
) -> dict:
    """Publish a new version: validate + server-side recompile the uploaded spec, then index it.

    **Publishing runs as the low-priority lane, and has no deadline.** On a deployment that enriches
    online it queues for the same process-wide permit `/check` uses, waits as long as it takes, and
    defers to interactive demand rather than racing it. While queued it costs an event-loop task and
    no threadpool worker; while running it holds a thread of its own, niced, so the compile yields
    CPU to everything else. So this request can legitimately stay open for minutes — put the publish
    client's timeout, and any reverse proxy's, well above `enrich_max_variants / 20 * 6s`.

    On the default offline deployment none of that applies: the publish reaches nothing, takes no
    permit, and runs straight through.
    """
    require_capability(repo, account, namespace, Capability.PUBLISH)
    if not is_valid_version(version):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_version")
    if repo.version_exists(namespace, name, version):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="version_exists")

    try:
        uploads = await publish_service.collect_uploads(files, settings)
        # Awaited in the coroutine so a queue of publishes cannot exhaust the threadpool that
        # `/check` needs; released by the worker's own `finally` inside `publish_version`.
        gate = await _queue_for_enrichment(request, settings, f"publish {namespace}/{name}@{version}")
        # enrich + compile are heavy (seconds→minutes for large modules, and the enricher blocks on
        # I/O), so they go off the event loop — onto a dedicated niced thread rather than the shared
        # pool, because a nice value cannot be lowered again and a reused worker could never recover
        # from one. See `lowpriority.run_at_low_priority`.
        manifest = await _run_queued(
            publish_service.publish_version,
            gate,
            settings,
            repo=repo,
            storage=storage,
            namespace=namespace,
            name=name,
            version=version,
            changelog=changelog,
            owner=account.name,
            published_by=account.id,
            files=uploads,
            settings=settings,
            allow_test_data=allow_test_data,
        )
    except publish_service.PublishError as exc:
        raise _publish_http_error(exc)
    return manifest.model_dump()


@router.post(
    "/{namespace}/{name}/versions/import",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("publish"))],
)
async def import_archive(
    request: Request,
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    account: AccountDep,
    namespace: str,
    name: str,
    version: Annotated[str, Form()],
    archive: Annotated[UploadFile, File()],
    changelog: Annotated[str, Form()] = "",
    allow_test_data: Annotated[bool, Form()] = False,
    title: Annotated[Optional[str], Form()] = None,
    description: Annotated[Optional[str], Form()] = None,
    report_title: Annotated[Optional[str], Form()] = None,
    icon: Annotated[Optional[str], Form()] = None,
    color: Annotated[Optional[str], Form()] = None,
    genome_build: Annotated[Optional[str], Form()] = None,
) -> dict:
    """Publish from a zip/tar.gz archive (in-house packaging / legacy import).

    A spec archive is recompiled directly; a legacy parquet-only archive is reverse-engineered
    with the client-supplied display metadata, then recompiled. Same guards as `publish`.

    **`genome_build` is display metadata's opposite and the form field exists for that reason.**
    Everything else here is out of `artifact.digest`; the build is *in* it, because it decides the
    identity key — `variant_key` is a `ga4gh:VA.…` minted against the assembly's refget accession,
    so reversing a GRCh37 module as GRCh38 mints ids naming a base the module never carried. The
    build lives in no parquet column, so `reverse_module` recovers it from the archive's own
    `manifest.json` and falls back to the format's `GRCh38` default when there is none. Pass this
    only for a bare parquet archive that carries no manifest and is not GRCh38; an explicit value
    always wins.
    """
    require_capability(repo, account, namespace, Capability.PUBLISH)
    if not is_valid_version(version):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_version")
    if repo.version_exists(namespace, name, version):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="version_exists")

    # Bounded before the read, from the spooled part's size, so an oversized archive is rejected
    # without ever being held in memory. (Its *contents* are separately guarded against traversal by
    # `_extract_archive`, which the multipart path lacked until 0.11.)
    if (archive.size or 0) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error": "upload_too_large",
                "errors": [
                    f"{archive.size} bytes uploaded; the limit is {settings.max_upload_bytes}"
                ],
                "warnings": [],
                "info": [],
            },
        )
    data = await archive.read()
    try:
        gate = await _queue_for_enrichment(request, settings, f"import {namespace}/{name}@{version}")
        manifest = await _run_queued(
            publish_service.import_archive,
            gate,
            settings,
            repo=repo,
            storage=storage,
            namespace=namespace,
            name=name,
            version=version,
            changelog=changelog,
            owner=account.name,
            published_by=account.id,
            archive=data,
            display={
                "title": title,
                "description": description,
                "report_title": report_title,
                "icon": icon,
                "color": color,
                "genome_build": genome_build,
            },
            settings=settings,
            allow_test_data=allow_test_data,
        )
    except publish_service.PublishError as exc:
        raise _publish_http_error(exc)
    return manifest.model_dump()


# ── Pre-flight: the publish dry run (0.11) ────────────────────────────────────
#
# Both live under `{namespace}/{name}` even though nothing is published yet, and the module need not
# exist. The alternative — a bare `POST /api/v1/validate` — reads cleaner and answers a strictly
# weaker question: three of the four common publish rejections are namespace-scoped (`403`,
# `409 duplicate_content`, `422 name_mismatch`), so a path with no namespace would be systematically
# optimistic about exactly the thing these endpoints exist to predict. `{name}` is the name you
# intend to publish under; a mismatch against the spec's own `module.name` comes back as a finding.
#
# Both grade findings under `strict=true` by DEFAULT, contradicting the compiler's own default on
# purpose: a dry run whose default disagrees with the publish it is predicting is a trap.


async def _preflight_uploads(
    files: list[UploadFile], archive: Optional[UploadFile], settings: Settings
) -> dict[str, bytes]:
    """Accept a spec as loose multipart parts **or** as one compressed archive, and return the same
    `{name: bytes}` either way.

    The archive form is why this exists. `/versions/import` has always taken one, so a 180 MiB spec
    could be published as a 10 MiB `.tar.gz` — but the dry runs took only raw parts, which the
    transfer bound refuses at that size. The rehearsal has to accept whatever the publish accepts or
    it is not a rehearsal.
    """
    named = [f for f in files if f.filename]
    if archive is not None and archive.filename and named:
        raise publish_service.PublishError(
            "ambiguous_upload",
            errors=["send either `files` or `archive`, not both"],
        )
    if archive is not None and archive.filename:
        uploads = await publish_service.collect_archive(archive, settings)
    else:
        uploads = await publish_service.collect_uploads(files, settings)
    if not any(f in uploads for f in REQUIRED_SPEC_FILES):
        raise publish_service.PublishError(
            "missing_spec_files", errors=[f"missing: {f}" for f in REQUIRED_SPEC_FILES]
        )
    return uploads


def _preflight_spec_dir(uploads: dict[str, bytes], tmp: str) -> Path:
    """Materialize an upload into a spec directory. Names are already containment-checked."""
    spec_dir = Path(tmp) / "spec"
    for rel, data in uploads.items():
        dest = spec_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return spec_dir


@router.post(
    "/{namespace}/{name}/validate",
    response_model=ValidationReport,
    dependencies=[Depends(rate_limit("validate"))],
)
async def validate_spec_endpoint(
    repo: RepoDep,
    settings: SettingsDep,
    account: AccountDep,
    namespace: str,
    name: str,
    files: Annotated[list[UploadFile], File()] = [],
    archive: Annotated[Optional[UploadFile], File()] = None,
    strict: bool = Query(True, description="Grade findings under the mode publish compiles in"),
) -> ValidationReport:
    """Validate a spec server-side without publishing it. Writes nothing; the module need not exist.

    Send the spec as loose `files` parts or as a single `archive` (`.tar.gz` / `.zip`), exactly as
    `/versions/import` takes one. A spec too large to send raw is still rehearsable compressed.

    Offline and fast: no network, no compile, no artifact. Alongside the findings it returns the
    spec's content signature and any versions already built from identical data, so a publisher sees
    a `409 duplicate_content` coming before uploading again.

    A spec that would be rejected still comes back **200** — `valid: false` with the reasons. Only a
    request we cannot assemble a spec directory from is a 4xx.

    `would_publish_module_level` composes the publish gates that do not scale with the variant
    count into the one field a CI job can branch on here. It has no ceiling and costs no egress,
    which is what makes it the answer for a panel too large to check online. It is deliberately not
    called `would_publish`: this endpoint never runs the network tier, so a `true` means nothing
    module-level blocks a publish, not that one would succeed.

    Requires `PUBLISH` on `{namespace}`: it writes nothing, but it runs the real compiler over
    arbitrary uploaded CSVs, which is the same server CPU a publish spends.
    """
    require_capability(repo, account, namespace, Capability.PUBLISH)
    try:
        uploads = await _preflight_uploads(files, archive, settings)
        return await run_in_threadpool(
            _validate_worker, repo, settings, uploads, namespace, name, strict
        )
    except publish_service.PublishError as exc:
        raise _publish_http_error(exc)


def _validate_worker(
    repo: Repository, settings: Settings, uploads: dict[str, bytes],
    namespace: str, name: str, strict: bool,
) -> ValidationReport:
    """`namespace` reaches the dedup pre-check here so it can carve out the same module the way the
    publish gate does (S10) — it took the path's namespace not being threaded down for the two to
    disagree."""
    with tempfile.TemporaryDirectory() as tmp:
        spec_dir = _preflight_spec_dir(uploads, tmp)
        normalization = publish_service.normalize_spec(spec_dir)
        return enrich_service.validation_report(
            spec_dir, repo, namespace, name, strict,
            normalized=normalization.info, extra_warnings=normalization.warnings,
        )


@router.post(
    "/{namespace}/{name}/check",
    response_model=CheckReport,
    dependencies=[Depends(rate_limit("enrich"))],
)
async def check_spec(
    request: Request,
    repo: RepoDep,
    settings: SettingsDep,
    account: AccountDep,
    namespace: str,
    name: str,
    files: Annotated[list[UploadFile], File()] = [],
    archive: Annotated[Optional[UploadFile], File()] = None,
    strict: bool = Query(True, description="Grade findings under the mode publish compiles in"),
    offline: bool = Query(False, description="Clamp to the server's local caches; zero egress"),
    frequencies: bool = Query(False, description="gnomAD frequencies — online only, ~6s/20 variants"),
    literature: bool = Query(False, description="PubMed/EuropePMC/Crossref citation check — online"),
    identifiers: bool = Query(
        False, description="trait_efo_id vs OLS4 and gene vs HGNC — online, no snapshot exists"
    ),
    acmg: bool = Query(False, description="Authored acmg_sf flags vs the ACMG SF list"),
    pgx: bool = Query(False, description="function_status vs PharmVar/CPIC/ClinPGx/ClinGen"),
    declared_use: Optional[str] = Query(
        None,
        description=(
            "unstated | non_commercial | commercial. Gates the PGx-family sources, every one of "
            "which forbids sale: on `unstated` (the server default) each is skipped rather than "
            "queried. Defaults to the deployment's `REGISTRY_DECLARED_USE`."
        ),
    ),
) -> CheckReport:
    """The full publish dry run: validation plus what the network tier finds.

    Takes the spec as loose `files` parts or as a single compressed `archive`, the same two forms
    the publish routes take — a spec that only fits the wire compressed is still rehearsable.

    Checks nothing can catch offline — an authored reference allele against the actual genome, a
    `clin_sig` against ClinVar, an rsID dbSNP has merged away, GA4GH allele identity coverage — and
    returns `would_publish`, which is the single field a CI job should branch on.

    **Expensive, and the cost is the operator's.** gnomAD is paced at roughly six seconds per twenty
    variants, so this can legitimately take minutes; it is the tightest rate bucket in the service
    and is additionally capped to `enrich_max_concurrency` runs process-wide.

    `enrich_max_variants` bounds that pacing, so it bounds **online** runs only: `?offline=true` has
    no ceiling, because it issues no request for a ceiling to bound. Above it an online run is
    `422 too_many_variants`, and that body carries the `validation` report plus
    `would_publish_module_level` — the half the server had already computed before refusing, so the
    refusal still answers what it can rather than binning it.

    The enricher always runs in `best_effort`, whatever `?strict=` says: strict enrichment *raises*,
    and an endpoint whose purpose is to report cannot run in a mode that refuses to finish. `strict`
    grades the validation findings and decides whether unresolved positions count against
    `would_publish`.

    `?identifiers=true` adds trait-CURIE (OLS4) and gene-symbol (HGNC) currency — the generalization
    of "is the source stale?" from datasets to identifiers, since an EFO retirement or an HGNC rename
    leaves a module well-formed and quietly out of date. Neither registry publishes a snapshot, so
    offline the pass reports that nothing was asked rather than that nothing was found. It never
    moves `would_publish`: a publish does not run it, so a finding predicts nothing about one.

    `?pgx=true` adds the PGx-family cross-checks. They are gated by `declared_use`, a third axis
    orthogonal to strict/offline: every PGx upstream is CC BY-SA *plus* a no-sale clause, so on
    `unstated` each source is **skipped with a reason** rather than queried — the registry will not
    declare a purpose on your behalf. Pass `non_commercial` to actually run them; `commercial` is a
    direct contradiction and comes back `422 license_refused` having fetched nothing.

    `503 enrichment_unavailable` when the network tier cannot run **at all** — today that means
    `just-dna-enricher` is not installed on this server. Deliberately without `Retry-After`:
    retrying does not help until an operator changes the deployment. A *missing snapshot* is not
    this. It degrades per pass, with the reason in `enrichment.notes`, because an online run
    resolves through live Ensembl without one and a 503 there would refuse the one configuration
    that works.
    """
    require_capability(repo, account, namespace, Capability.PUBLISH)
    gate = request.app.state.enrichment_gate
    try:
        # Checked here rather than left to the enricher. `declared_use` decides whether a source
        # that forbids sale is queried at all, so an unrecognized spelling must never fall through
        # to something that reads as "not commercial, then" — `non-commercial` (the enricher CLI's
        # hyphenated user-facing spelling) is the likely typo, and the vocabulary member is
        # `non_commercial`.
        if declared_use is not None and declared_use not in VALID_DECLARED_USE:
            raise publish_service.PublishError(
                "invalid_declared_use",
                errors=[
                    f"declared_use must be one of {sorted(VALID_DECLARED_USE)}, got "
                    f"{declared_use!r}"
                ],
            )
        uploads = await _preflight_uploads(files, archive, settings)

        # Acquired here, in the coroutine, so queued callers do not each occupy an anyio worker and
        # exhaust the threadpool; released by the worker's own `finally`, because a run that blows
        # the timeout below keeps its thread (Python cannot kill one) and must keep counting.
        if not gate.try_acquire():
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="enrichment_busy",
                headers={"Retry-After": "60"},
            )
        try:
            return await asyncio.wait_for(
                run_in_threadpool(
                    enrich_service.dry_run,
                    settings=settings, repo=repo, uploads=uploads,
                    namespace=namespace, name=name, strict=strict,
                    offline=offline, frequencies=frequencies, literature=literature,
                    identifiers=identifiers, acmg=acmg, pgx=pgx,
                    declared_use=declared_use or settings.declared_use, gate=gate,
                ),
                timeout=settings.enrich_timeout_seconds,
            )
        except TimeoutError:
            # Frees the client and the connection. It does NOT stop the work: the worker runs to
            # completion and only then releases its gate permit, which is why occupancy stays honest.
            raise HTTPException(
                status.HTTP_504_GATEWAY_TIMEOUT, detail="enrichment_timeout"
            )
    except enrich_service.EnrichmentUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enrichment_unavailable",
                "missing": exc.missing,
                "errors": [str(exc)],
            },
        )
    except publish_service.PublishError as exc:
        raise _publish_http_error(exc)


@router.patch("/{namespace}/{name}/versions/{version}")
def amend_changelog(
    repo: RepoDep,
    account: AccountDep,
    namespace: str,
    name: str,
    version: str,
    body: ChangelogPatch,
) -> dict:
    """Amend a published version's changelog. Metadata only — the artifact/digest are immutable
    and untouched. Requires amend rights (own version for a member; any for admin+). `append=true`
    adds to the existing changelog."""
    require_capability(
        repo, account, namespace, Capability.AMEND_ANY,
        resource_author=repo.version_author(namespace, name, version),
    )
    current = repo.get_version_changelog(namespace, name, version)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    changelog = f"{current}\n{body.changelog}" if (body.append and current) else body.changelog
    repo.set_version_changelog(namespace, name, version, changelog)
    return {"namespace": namespace, "name": name, "version": version, "changelog": changelog}


@router.post("/{namespace}/{name}/versions/{version}/logo")
async def amend_logo(
    repo: RepoDep,
    storage: StorageDep,
    account: AccountDep,
    namespace: str,
    name: str,
    version: str,
    logo: Annotated[UploadFile, File()],
) -> dict:
    """Replace a published version's logo (png/jpg/jpeg). Requires amend rights (own version for a
    member; any for admin+). Out-of-digest metadata: the artifact/digest — and any signature over
    it — stay immutable, so no version bump is needed."""
    require_capability(
        repo, account, namespace, Capability.AMEND_ANY,
        resource_author=repo.version_author(namespace, name, version),
    )
    data = await logo.read()
    try:
        manifest = await run_in_threadpool(
            publish_service.amend_logo,
            repo=repo,
            storage=storage,
            namespace=namespace,
            name=name,
            version=version,
            filename=logo.filename or "",
            data=data,
        )
    except publish_service.PublishError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.detail == "version_not_found"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(code, detail={"error": exc.detail, "errors": exc.errors})
    return {
        "namespace": namespace, "name": name, "version": version,
        "logo": manifest.logo.model_dump() if manifest.logo else None,
    }


@router.post("/{namespace}/{name}/versions/{version}/readme")
async def amend_readme(
    repo: RepoDep,
    storage: StorageDep,
    account: AccountDep,
    namespace: str,
    name: str,
    version: str,
    readme: Annotated[UploadFile, File()],
) -> dict:
    """Replace a published version's readme — the prose on the module's card (S5).

    Requires amend rights (own version for a member; any for admin+). Out-of-digest metadata, like
    the logo and the changelog: the artifact, its digest and any signature over it stay immutable,
    so no version bump is needed. That matters more here than for a logo — a readme is where a
    module says what it is *not*, and a badly phrased caveat must be fixable without burning a
    version number and a `content_hash` that `yank` would not release.

    Sent as a file part rather than a JSON string: a readme is a document with newlines and non-ASCII
    prose, and this is the same shape publish accepts it in.
    """
    require_capability(
        repo, account, namespace, Capability.AMEND_ANY,
        resource_author=repo.version_author(namespace, name, version),
    )
    raw = await readme.read()
    try:
        text = await run_in_threadpool(
            publish_service.amend_readme,
            repo=repo,
            storage=storage,
            namespace=namespace,
            name=name,
            version=version,
            text=raw.decode("utf-8", errors="replace"),
        )
    except publish_service.PublishError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.detail == "version_not_found"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(code, detail={"error": exc.detail, "errors": exc.errors})
    return {"namespace": namespace, "name": name, "version": version, "readme": text}


@router.post("/{namespace}/{name}/versions/{version}/yank")
def yank(
    repo: RepoDep,
    account: AccountDep,
    namespace: str,
    name: str,
    version: str,
    body: YankRequest | None = None,
) -> dict:
    """Set (or clear) the yanked flag on a version. Reversible, so it's own-scoped for a member
    (yank your own versions) and any for admin+."""
    require_capability(
        repo, account, namespace, Capability.YANK_ANY,
        resource_author=repo.version_author(namespace, name, version),
    )
    yanked = body.yanked if body is not None else True
    if not repo.set_yanked(namespace, name, version, yanked):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    return {"namespace": namespace, "name": name, "version": version, "yanked": yanked}


# ── The polygon's delete verb (0.12) ──────────────────────────────────────────
#
# Mounted only when `mode == "test"` — see `api/app.py`. On production the verb is refused by the router
# rather than by a handler (`405 Method Not Allowed`: the paths exist and serve GET/POST, so "method not
# allowed" is the accurate answer, not "no such module"). That is the property worth having — a
# misconfigured client cannot delete production data by presenting a valid token, because there is no
# handler to authorize it.
#
# Why the polygon needs it. A published `(namespace, name, version)` is immutable and its authored data
# is claimed by a name-independent `content_hash` that `yank` does not release — so on a test box every
# rehearsal permanently burns both a version number and the right to publish that data anywhere else.
# Without a delete verb the only cure is shell access and `registry remove-version`, which a CI job
# driving the polygon over HTTPS does not have. That is the "strange situation of burner-tests".
#
# Authenticated and namespace-scoped, deliberately, even here. The polygon answers on a public DNS name,
# so "open" means the verb is available, never that it is unauthenticated: the same bearer token and the
# same `Capability.PUBLISH` that put the version there can take it away.


#: A separate router so the mounting can be conditional — `app.py` includes it only on the polygon.
#: Same prefix and tags, so the paths and the OpenAPI grouping are identical to the publish routes they
#: sit beside; the only difference is that on production this router is never handed to the app.
testops_router = APIRouter(prefix="/modules", tags=["publish"])


def _require_test_instance(settings: Settings) -> None:
    """Belt to the router's braces. The route is not mounted on production; if a future refactor mounts
    it unconditionally, this turns that mistake into a 404 rather than a deleted catalog. Not reachable
    today, and deliberately kept: the cost is four lines and the failure it guards is unrecoverable."""
    if not settings.is_test_instance:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")


@testops_router.delete("/{namespace}/{name}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    account: AccountDep,
    namespace: str,
    name: str,
    version: str,
) -> Response:
    """**Test instance only.** Hard-delete one version: rows, artifacts, and its content claim.

    Not `yank`. Yank is the production answer — it withdraws a version while keeping it verifiable for
    anyone who already installed it. This removes it, which is only defensible where nothing downstream
    is entitled to keep working, and frees the `content_hash` so the same data can be published again.
    """
    _require_test_instance(settings)
    require_capability(repo, account, namespace, Capability.PUBLISH)
    if not repo.delete_version(namespace, name, version):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    storage.remove(version_key(namespace, name, version))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@testops_router.delete("/{namespace}/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_module(
    repo: RepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    account: AccountDep,
    namespace: str,
    name: str,
) -> Response:
    """**Test instance only.** Hard-delete every version of a module, its artifacts, and its content
    claims. The whole-module form exists because a rehearsal usually leaves several versions behind and
    deleting them one at a time is how a cleanup job half-finishes."""
    _require_test_instance(settings)
    require_capability(repo, account, namespace, Capability.PUBLISH)
    versions = repo.delete_module(namespace, name)
    if not versions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="module_not_found")
    storage.remove(f"{namespace}/{name}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
