"""The authoring hint proxy (0.25) — the enricher's lookups, over HTTP, metered per upstream.

**Three tiers, and the free one is the point.** Anonymous callers may ask anything with
`offline=true`: a thin client with no Ensembl snapshot getting an rsID placed onto a coordinate, for
free, at zero egress to anyone, is this whole surface working as designed. Anonymous *online* is
refused on both instances and does not vary by `REGISTRY_MODE` — gnomAD's limit is keyed on our IP and
cannot be bought at any price, so one anonymous caller could throttle every publisher on the box, and
the pace ledger needs a stable identity to mean anything. gnomAD sits behind its own switch on top of
that, default off, because 512 frequency lookups is 85% of what the whole deployment gets in an hour
and `/check?frequencies=true` needs the same allowance to gate a publish.

Order in every handler, and the sleep comes **before** the permit: request bucket, then the ledger
(absorbed or `429`), then the work. A paced sleep inside an enrichment permit would block `/check` for
its duration, which is the opposite of yielding.
"""

import asyncio
import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

from just_dna_registry.api.deps import (
    Account,
    _rate_identity,
    optional_account,
    rate_limit,
    settings_dep,
)
from just_dna_registry.config import Settings
from just_dna_registry.models.api import (
    CitationHintReport,
    GeneHintReport,
    HintCost,
    OldAssemblyHintReport,
    TraitHintReport,
    VariantHintBatch,
    VariantHintBatchResponse,
    VariantHintReport,
)
from just_dna_registry.services import hints as hint_service
from just_dna_registry.services.enrich import enricher_available

router = APIRouter(prefix="/hint", tags=["hints"])

SettingsDep = Annotated[Settings, Depends(settings_dep)]
MaybeAccountDep = Annotated[Account | None, Depends(optional_account)]


def _require_enabled(settings: Settings) -> None:
    if not settings.hint_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hint_disabled")
    if not enricher_available():
        # The tier is missing entirely, which is a deployment fact rather than a per-source one and
        # is never fixed by retrying — hence no `Retry-After`, exactly as for `enrichment_unavailable`.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enrichment_unavailable",
                "missing": ["just-dna-enricher"],
                "errors": ["the network tier is not installed (install the `server` extra)"],
            },
        )


def _resolve_offline(settings: Settings, account: Account | None, offline: bool) -> bool:
    """Which tier this caller is in, and refuse the online one when they are not entitled to it."""
    if offline:
        return True
    if account is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "online_hint_needs_a_token",
                "errors": [
                    "anonymous callers may use offline=true, which is answered from this "
                    "deployment's snapshots at no cost to anyone. An online hint spends this "
                    "server's standing with upstreams that rate-limit by IP and sell no key, so it "
                    "needs an account the budget can be attributed to."
                ],
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return False


async def _meter(request: Request, settings: Settings, charges: dict[str, int]) -> HintCost:
    """Commit the charge, then absorb a short wait here or refuse a long one.

    Absorbed **in the coroutine**: an `asyncio.sleep` costs a task, while sleeping on a threadpool
    worker would occupy the pool an interactive request needs. Past `hint_inline_wait_seconds` the
    honest answer is a `429` with `Retry-After` — holding a connection open for minutes delivers a
    worse version of the same information.
    """
    ledger = request.app.state.pace_ledger
    verdicts = ledger.charge(_rate_identity(request), charges)
    waits = [v for v in verdicts if v.wait_seconds > 0]
    cost = HintCost(charged={v.upstream: v.charged for v in verdicts if v.charged})
    if not waits:
        return cost

    longest = max(waits, key=lambda v: v.wait_seconds)
    cost.remedy = longest.remedy
    cost.limit = "pace"
    if longest.wait_seconds > settings.hint_inline_wait_seconds:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "hint_pace_decayed",
                "upstream": longest.upstream,
                "spent": longest.spent,
                "budget": longest.budget,
                "tier": longest.tier,
                "remedy": longest.remedy,
                "errors": [
                    f"you are past today's {longest.upstream} allowance ({longest.spent} of "
                    f"{longest.budget}), so your pace is being decayed rather than cut off"
                ],
            },
            headers={"Retry-After": str(max(1, math.ceil(longest.wait_seconds)))},
        )
    await asyncio.sleep(longest.wait_seconds)
    cost.waited_seconds = longest.wait_seconds
    return cost


@router.get("/variant", response_model=VariantHintReport,
            dependencies=[Depends(rate_limit("hint"))])
async def hint_variant(
    request: Request,
    settings: SettingsDep,
    account: MaybeAccountDep,
    rsid: str | None = Query(None),
    chrom: str | None = Query(None),
    start: int | None = Query(None),
    ref: str | None = Query(None),
    alts: str | None = Query(None),
    frequencies: bool = Query(False, description="gnomAD allele counts; paced at one per six seconds"),
    offline: bool = Query(True, description="Snapshot only — free, and the default"),
) -> VariantHintReport:
    """What is known about one variant: validity, coordinates, alleles, clinical calls, frequencies.

    **Nothing is written and nothing is decided.** A one-to-many rsID returns every locus rather than
    picking one; a position matching several rsIDs returns every candidate. Each entry in
    `alterations` carries `applied: false` and a `refusal` saying why the value is yours to type —
    almost every fact here is cross-examined later by a check that only works because you wrote it
    independently, and filling the cell from the same oracle the checker consults turns that check
    into a tautology.

    `offline=true` is the default and costs nothing: it reads this deployment's snapshots, which is
    the reason to ask a registry rather than provision your own. Going online needs a
    token, and `frequencies=true` additionally needs the deployment to have enabled gnomAD.
    """
    _require_enabled(settings)
    resolved_offline = _resolve_offline(settings, account, offline)
    if frequencies and not settings.hint_allow_gnomad:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error": "gnomad_not_enabled",
                "errors": [
                    "this deployment does not proxy gnomAD. Its limit is ten requests per sixty "
                    "seconds keyed on this server's IP, with no key purchasable at any price, and it "
                    "is the same allowance publish rehearsals draw on."
                ],
            },
        )
    if not (rsid or (chrom and start)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "hint_needs_a_key", "errors": ["give an rsid, or a chrom and start"]},
        )

    scrub = hint_service.HintScrubber.build(settings)
    cost = await _meter(request, settings, hint_service.variant_charges(
        rsid=rsid, frequencies=frequencies, offline=resolved_offline,
    ))
    answer = await run_in_threadpool(
        hint_service.run_variant,
        settings=settings, scrub=scrub, rsid=rsid, chrom=chrom, start=start,
        ref=ref, alts=alts, frequencies=frequencies, offline=resolved_offline,
    )
    cost.served_from = answer.served_from
    return VariantHintReport(**answer.payload, cost=cost)


@router.post("/variants", response_model=VariantHintBatchResponse,
             dependencies=[Depends(rate_limit("hint"))])
async def hint_variants(
    request: Request,
    settings: SettingsDep,
    account: MaybeAccountDep,
    body: VariantHintBatch,
    frequencies: bool = Query(False),
    offline: bool = Query(True),
) -> VariantHintBatchResponse:
    """Resolve many variants at once — snapshot first for every key, live only for what missed.

    **This is the caching proxy, and the single-key routes cannot do it.** An online single lookup
    egresses unconditionally, because dbSNP merge status has no snapshot in this tree and that leg
    runs whatever the cache said. A batch runs the offline pass over every key at no cost and goes
    online only for the misses, so on a well-provisioned deployment a whole module's worth of keys
    comes back charging nothing at all — which is the number that makes this worth deploying.

    The online cap is far below the offline one, and deliberately: an online batch runs its misses
    sequentially at the upstream's own pace, so the bound is what can finish inside one request rather
    than a round number.
    """
    _require_enabled(settings)
    resolved_offline = _resolve_offline(settings, account, offline)
    cap = settings.hint_max_batch if resolved_offline else settings.hint_max_batch_online
    if len(body.keys) > cap:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "too_many_variants",
                "limit": cap,
                "errors": [
                    f"{len(body.keys)} keys exceeds the {'offline' if resolved_offline else 'online'}"
                    f" batch limit of {cap}"
                ],
            },
        )
    if frequencies and not resolved_offline:
        # Refused outright rather than capped smaller: 128 keys at gnomAD's six-second pace is 12.8
        # minutes against a request that will not live that long, and a batch that cannot finish is
        # worse than one that says so.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "frequencies_not_batchable",
                "errors": [
                    "gnomAD is paced at one request per six seconds, so a batch of frequencies "
                    "cannot finish inside a request. Ask for them one variant at a time."
                ],
            },
        )

    scrub = hint_service.HintScrubber.build(settings)
    answers = await run_in_threadpool(
        hint_service.run_variant_batch,
        settings=settings, scrub=scrub,
        keys=[key.model_dump() for key in body.keys],
        frequencies=False, offline=resolved_offline,
    )

    # Charged after the fact for this route alone, because the whole point is that the charge depends
    # on how many keys the snapshot answered — which is not knowable from the request's shape.
    total: dict[str, int] = {}
    for answer in answers:
        for upstream, units in answer.charges.items():
            total[upstream] = total.get(upstream, 0) + units
    cost = await _meter(request, settings, total)

    results = []
    for answer in answers:
        each = HintCost(charged=dict(answer.charges), served_from=answer.served_from)
        results.append(VariantHintReport(**answer.payload, cost=each))
    cost.served_from = sorted({label for a in answers for label in a.served_from})
    return VariantHintBatchResponse(
        results=results, total_charged={k: v for k, v in total.items() if v}, cost=cost,
    )


@router.get("/citation", response_model=CitationHintReport,
            dependencies=[Depends(rate_limit("hint"))])
async def hint_citation(
    request: Request,
    settings: SettingsDep,
    account: MaybeAccountDep,
    pmid: str | None = Query(None),
    doi: str | None = Query(None),
    pmcid: str | None = Query(None),
    offline: bool = Query(False, description="Report that nothing was asked, rather than asking"),
) -> CitationHintReport:
    """Does this citation exist, and what is its other identifier?

    **Existence is not identity, which is why the answer names the paper.** PMIDs are densely
    allocated, so a recalled or invented number is very likely to be a real record — for a different
    paper — and `pmid_exists: true` alone cannot catch a fabricated citation. The title, journal, year
    and first author arrive in the same response that answers existence, so comparing what was found
    against what you meant costs nothing extra.

    There is no snapshot for this family, so `offline=true` reports that nothing was asked rather than
    that nothing was found — which is the distinction, not a technicality.
    """
    _require_enabled(settings)
    resolved_offline = _resolve_offline(settings, account, offline)
    if not (pmid or doi or pmcid):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "hint_needs_a_key", "errors": ["give a pmid, a doi, or a pmcid"]},
        )
    charges: dict[str, int] = {}
    if not resolved_offline:
        if pmid or pmcid:
            charges["ncbi"] = 1
        if doi:
            charges["literature"] = 1
    cost = await _meter(request, settings, charges)
    scrub = hint_service.HintScrubber.build(settings)
    answer = await run_in_threadpool(
        hint_service.run_citation,
        scrub=scrub, pmid=pmid, doi=doi, pmcid=pmcid, offline=resolved_offline,
    )
    return CitationHintReport(**answer.payload, cost=cost)


@router.get("/gene", response_model=GeneHintReport, dependencies=[Depends(rate_limit("hint"))])
async def hint_gene(
    request: Request, settings: SettingsDep, account: MaybeAccountDep, symbol: str = Query(...)
) -> GeneHintReport:
    """Is this gene symbol approved or retired? HGNC's exact endpoints, never the fuzzy search.

    Online only — there is no snapshot for HGNC — so this needs a token whatever `offline` would have
    meant, and a deployment with no egress cannot answer it at all.
    """
    _require_enabled(settings)
    _resolve_offline(settings, account, False)
    cost = await _meter(request, settings, {"ontology": 1})
    answer = await run_in_threadpool(hint_service.run_gene, symbol=symbol)
    return GeneHintReport(**answer.payload, cost=cost)


@router.get("/trait", response_model=TraitHintReport, dependencies=[Depends(rate_limit("hint"))])
async def hint_trait(
    request: Request, settings: SettingsDep, account: MaybeAccountDep, curie: str = Query(...)
) -> TraitHintReport:
    """Is this trait CURIE current, obsolete or unknown? OLS4, online only for the same reason."""
    _require_enabled(settings)
    _resolve_offline(settings, account, False)
    cost = await _meter(request, settings, {"ontology": 1})
    answer = await run_in_threadpool(hint_service.run_trait, curie=curie)
    return TraitHintReport(**answer.payload, cost=cost)


@router.get("/old-assembly", response_model=OldAssemblyHintReport,
            dependencies=[Depends(rate_limit("hint"))])
async def hint_old_assembly(
    request: Request,
    settings: SettingsDep,
    account: MaybeAccountDep,
    chrom: str = Query(...),
    start: int = Query(...),
    ref: str | None = Query(None),
    alts: str | None = Query(None),
    offline: bool = Query(False),
) -> OldAssemblyHintReport:
    """I have an hg19 coordinate — what is its rs-number?

    **Recovery, not liftover**, and the difference is the whole design. An rs-number authored into
    `variants.csv` resolves through the ordinary chain into a coordinate a later check can
    cross-examine; a lifted-over position becomes the row's sole identity with nothing to check it
    against. So candidates come back as advisories you type yourself, and several candidates are
    reported rather than picked — `ref` and `alts` narrow them, and a pick among equals is not a
    finding.
    """
    _require_enabled(settings)
    resolved_offline = _resolve_offline(settings, account, offline)
    cost = await _meter(request, settings, {} if resolved_offline else {"ncbi": 1})
    scrub = hint_service.HintScrubber.build(settings)
    answer = await run_in_threadpool(
        hint_service.run_old_assembly,
        scrub=scrub, chrom=chrom, start=start, ref=ref, alts=alts, offline=resolved_offline,
    )
    return OldAssemblyHintReport(**answer.payload, cost=cost)
