"""The snapshot-lane dashboard (0.25) — what this deployment holds, and for the rest, why not.

One route, anonymous, read-only. It exists because this service is the box in the ecosystem that
*has* the multi-gigabyte snapshots, and every client that does not — a module author, an agent, a
`just-module-creator` session, a `just-dna-lite` install — has to be able to ask which of them it can
therefore lean on here. A publisher whose `/check` came back with a source skipped has the same
question from the other side.

**Anonymous, on `/health`'s licence.** That endpoint already publishes the enrichment gate's
occupancy with no bearer, and a lane's presence is the same class of operational fact about the box.
The tempting justification — *a caller could enumerate this through `/check` anyway* — is **false**
and must not be written down: `/check` requires the `PUBLISH` capability and an anonymous caller has
none. Paths never appear in the response; see `CacheLaneStatus`.
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from just_dna_registry.api.deps import rate_limit, settings_dep
from just_dna_registry.config import Settings
from just_dna_registry.models.api import CacheStatusReport
from just_dna_registry.services import enrich

router = APIRouter(tags=["ops"])

SettingsDep = Annotated[Settings, Depends(settings_dep)]

#: Seconds a computed report is served from memory. The answer changes only when an operator
#: provisions something, so this is not a staleness trade so much as a refusal to walk every
#: lane's directory per request on a route anonymous callers can hit.
CACHE_TTL_SECONDS = 30.0

_cached: dict[tuple, tuple[float, CacheStatusReport]] = {}


def _cache_key(settings: Settings) -> tuple:
    """Everything the report depends on, so two deployments in one process cannot share an answer.

    **Keyed rather than a single slot**, because a single slot is right until something builds two
    apps — the suite does, one production and one polygon — and then the second reads the first's
    report for thirty seconds. That is a test-visible bug today and a wrong dashboard the day a
    process ever serves two settings.
    """
    return (settings.declared_use, tuple(sorted(
        (name, str(path) if path is not None else None)
        for name, path in enrich.lane_destinations(settings).items()
    )))


def _fresh(settings: Settings) -> CacheStatusReport:
    """The report, recomputed at most every `CACHE_TTL_SECONDS`.

    Deliberately not locked. Two concurrent misses compute the same answer twice and the second
    overwrites the first with an equal value; a lock here would serialize a read-only endpoint to
    protect against a duplicated stat() walk, which is the wrong trade.
    """
    key = _cache_key(settings)
    now = time.monotonic()
    hit = _cached.get(key)
    if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    report = enrich.lane_status(settings)
    _cached[key] = (now, report)
    return report


@router.get(
    "/caches",
    response_model=CacheStatusReport,
    summary="Snapshot lanes this deployment holds",
    dependencies=[Depends(rate_limit("search"))],
)
async def cache_status(settings: SettingsDep) -> CacheStatusReport:
    """Report every snapshot lane: its state, the release on disk, and the route an absent one takes.

    Reads only — nothing is downloaded and nothing is built, so this is safe on a box with no network
    and it is the first thing to run when a `/check` says a source was skipped. Provisioning is
    `registry warm-caches`, deliberately an operator command rather than a request-path concern.

    The walk stats one directory per lane and parses a small JSON file in each, so it runs on a
    threadpool worker behind a short TTL rather than on the event loop.
    """
    return await run_in_threadpool(_fresh, settings)
