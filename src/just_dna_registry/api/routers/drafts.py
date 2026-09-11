"""The drafting endpoint (0.25) — the enricher's drafters, run against this box's snapshots.

Not namespace-scoped, because a draft is not about a published module and there is no namespace for a
capability to be about. `require_account` instead: any authenticated caller. Anonymous is refused for
a reason worth stating — drafting reads **licence-gated snapshots this deployment acquired under its
own declared use**, so an anonymous drafter would turn the box into a free panel generator whose
licence acceptance belongs to somebody else.

One route over seven sources rather than seven routes: the only real difference between them is which
lane they read. The cost of that is a union of optional parameters, and the guard that keeps it honest
is `check_params` — a parameter the chosen source does not read is a `422`, never silently dropped.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from just_dna_format.vocab import VALID_DECLARED_USE
from starlette.concurrency import run_in_threadpool

from just_dna_registry.api.deps import Account, rate_limit, require_account, settings_dep
from just_dna_registry.api.routers.publish import _preflight_uploads, _publish_http_error
from just_dna_registry.config import Settings
from just_dna_registry.services import drafting as drafting_service
from just_dna_registry.services import publish as publish_service

router = APIRouter(prefix="/drafts", tags=["drafting"])

SettingsDep = Annotated[Settings, Depends(settings_dep)]
AccountDep = Annotated[Account, Depends(require_account)]


@router.post(
    "",
    dependencies=[Depends(rate_limit("draft"))],
    responses={200: {"content": {"application/gzip": {}}, "description": "The drafted spec"}},
    summary="Draft spec rows from a source this deployment has a snapshot for",
)
async def draft_spec(
    request: Request,
    settings: SettingsDep,
    account: AccountDep,
    source: str = Query(
        ..., description="clinvar | pubmind | civic | mitomap-miss | clinpgx | cpic | strchive"
    ),
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 — FastAPI default, never mutated
    archive: Annotated[UploadFile | None, File()] = None,
    gene: Annotated[list[str], Query(description="Repeatable. CPIC takes exactly one")] = [],  # noqa: B006
    drug: Annotated[list[str], Query(description="Repeatable (clinpgx, cpic)")] = [],  # noqa: B006
    allele: Annotated[list[str], Query(description="Repeatable (cpic)")] = [],  # noqa: B006
    population: str | None = Query(None, description="cpic only"),
    clin_sig: Annotated[list[str], Query(description="Repeatable (clinvar, pubmind)")] = [],  # noqa: B006
    min_review_stars: int | None = Query(None, description="clinvar only"),
    max_citations: int | None = Query(None, description="clinvar only"),
    min_confidence: int | None = Query(None, description="pubmind only"),
    min_evidence_level: str | None = Query(None, description="clinpgx only"),
    declared_use: str | None = Query(None, description="unstated | non_commercial | commercial"),
    dry_run: bool = Query(False, description="Report what would be appended and write nothing"),
) -> Response:
    """Append drafted rows to an uploaded spec from a source this deployment holds a snapshot for.

    **What you get back is a spec that will not validate yet, and that is the design.** Drafted rows
    carry a placeholder where only a curator can decide the value — a genotype, a conclusion — so the
    tree comes back needing exactly the judgement a machine must not supply. `draft-report.json` at
    the archive root says so in `next_step`, along with what was appended, what was already there, and
    what *differs* from the source and was left alone.

    **Stateless, which is the whole safety argument.** A re-draft over an existing spec appends
    corrected rows beside the ones they supersede, so nothing is held here between calls: you upload a
    tree, the drafter appends into that tree, the tree comes back. Draft into a fresh spec directory;
    if you draft into one that already carries drafted rows you get that append-beside-supersede
    behaviour, and the `already_present` / `differs` counts are how you will see it. `?dry_run=true`
    reports without writing.

    Snapshot-only by construction: no download, no live source, therefore no egress and no enrichment
    permit. A lane this deployment has not provisioned is `503 snapshot_unavailable` naming the lane
    and its route — deliberately not `enrichment_unavailable`, which means the tier is missing
    entirely. `GET /caches` answers which lanes are here before you ask.

    A parameter the chosen source does not read is `422 param_not_for_source` rather than ignored: a
    dropped `min_evidence_level` produces a draft answering a different question from the one asked.
    """
    client_format = request.headers.get("X-Format-Version") or None
    try:
        if source not in drafting_service.DRAFT_SOURCES:
            raise publish_service.PublishError(
                "unknown_draft_source",
                errors=[
                    f"?source={source!r} is not one of "
                    f"{', '.join(sorted(drafting_service.DRAFT_SOURCES))}"
                ],
            )
        chosen = drafting_service.DRAFT_SOURCES[source]

        use = declared_use or settings.declared_use
        if use not in VALID_DECLARED_USE:
            # Checked here for the reason `/check` checks it here: `declared_use` decides whether a
            # gated source is read at all, so an unrecognized spelling must never fall through to
            # something that reads as "not commercial, then".
            raise publish_service.PublishError(
                "invalid_declared_use",
                errors=[f"declared_use must be one of {sorted(VALID_DECLARED_USE)}, got {use!r}"],
            )

        sent = {
            name for name, value in (
                ("drugs", drug), ("alleles", allele), ("population", population),
                ("clin_sig", clin_sig), ("min_review_stars", min_review_stars),
                ("max_citations", max_citations), ("min_confidence", min_confidence),
                ("min_evidence_level", min_evidence_level),
            ) if value not in (None, [], ())
        }
        drafting_service.check_params(chosen, sent)
        drafting_service.check_genes(chosen, gene)

        uploads = await _preflight_uploads(files, archive, settings)
        built = await run_in_threadpool(
            drafting_service.run_draft,
            settings=settings,
            uploads=uploads,
            source_name=source,
            request=drafting_service.DraftRequest(
                spec_dir=None,  # type: ignore[arg-type] — filled by the worker's own temp dir
                genes=gene, drugs=drug, alleles=allele, population=population,
                clin_sig=clin_sig, min_review_stars=min_review_stars,
                max_citations=max_citations, min_confidence=min_confidence,
                min_evidence_level=min_evidence_level,
                declared_use=use, dry_run=dry_run,
            ),
        )
    except publish_service.PublishError as exc:
        raise _publish_http_error(exc, client_format) from exc

    return Response(
        content=built.archive,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{built.filename}"'},
    )
