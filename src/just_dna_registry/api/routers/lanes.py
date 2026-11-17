"""Keyed lookups of every snapshot lane, local or remote (0.30). See `services/lanes.py`."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from just_dna_registry.api.deps import rate_limit, refund_rate_charge, settings_dep
from just_dna_registry.config import Settings
from just_dna_registry.proxy_coverage import proxies
from just_dna_registry.services import lanes as lane_service

router = APIRouter(prefix="/lanes", tags=["hints"])
SettingsDep = Annotated[Settings, Depends(settings_dep)]


def _all_lanes() -> tuple[str, ...]:
    """Every lane upstream registers: the route answers any of them (held, or read from its repo)."""
    try:
        from just_dna_enricher.caches import CACHE_LANES
    except ImportError:
        return ()
    return tuple(lane.name for lane in CACHE_LANES)


class LaneLookup(BaseModel):
    keys: dict[str, list[Any]] = Field(
        description="Key column -> values, ANDed across columns: rsid, gene, chrom+start, ..."
    )


_TERMS = (
    "The lane source's terms as the enricher's lane registry states them (0.32): licence, licence URL, "
    "attribution, notice, and the `share_alike` / `commercial_use` / `redistribution` axes. `null` means the "
    "registry states no terms for this lane, which is not a statement that it is unrestricted: read "
    "`unpublished` beside it. A keyed read is served whatever the terms; honouring them is the caller's."
)
_UNPUBLISHED = (
    "Why no snapshot of this lane is published, in the enricher's own sentence (0.32): `refused: ...` "
    "where the source's terms forbid passing the snapshot on, `unestablished: ...` where nobody has "
    "established that they allow it. `null` when the lane's snapshot is published."
)


_RELEASE = (
    "The lane's release label, read exactly as `GET /caches` reads a local lane's (0.33): from this box's "
    "copy, or from the published repo's `release.json` at `revision`. `null` where none is stated. A label "
    "names a release, never the bytes: a stale copy under the hub's newer `release.json` reads the new label."
)
_RELEASE_UNREADABLE = (
    "A `release.json` is there and could not be read (it does not parse, or the published repo's copy could not "
    "be fetched): the release is unknown, the rows still usable."
)
_REVISION = (
    "The hub commit every file of a remote read was read at (0.33), resolved once per request, so one answer "
    "never straddles a commit. `null` for a local copy, which keeps no commit."
)


class LaneRowsResponse(BaseModel):
    lane: str
    table: str
    served_from: str = Field(description="`local`, or `remote:<repo>` when read from the published repo")
    rows: list[dict[str, Any]]
    truncated: bool = Field(description="More rows matched than this server returns per request")
    terms: dict[str, Any] | None = Field(default=None, description=_TERMS)
    unpublished: str | None = Field(default=None, description=_UNPUBLISHED)
    release: str | None = Field(default=None, description=_RELEASE)
    release_unreadable: bool = Field(default=False, description=_RELEASE_UNREADABLE)
    revision: str | None = Field(default=None, description=_REVISION)


class LaneTablesResponse(BaseModel):
    lane: str
    served_from: str
    tables: list[dict[str, Any]]
    terms: dict[str, Any] | None = Field(default=None, description=_TERMS)
    unpublished: str | None = Field(default=None, description=_UNPUBLISHED)
    release: str | None = Field(default=None, description=_RELEASE)
    release_unreadable: bool = Field(default=False, description=_RELEASE_UNREADABLE)
    revision: str | None = Field(default=None, description=_REVISION)


def _refusal(request: Request, exc: lane_service.LaneLookupError) -> HTTPException:
    refund_rate_charge(request)
    return HTTPException(exc.status, detail={"error": exc.code, "errors": [str(exc)]})


@router.get("/{lane}", response_model=LaneTablesResponse, dependencies=[Depends(rate_limit("hint"))])
async def lane_tables(request: Request, settings: SettingsDep, lane: str) -> LaneTablesResponse:
    """What a lane holds, as tables with the key columns each can be asked by."""
    try:
        source, tables = await run_in_threadpool(lane_service.lane_tables, lane, settings)
    except lane_service.LaneLookupError as exc:
        raise _refusal(request, exc) from exc
    said = lane_service.lane_terms(lane)
    return LaneTablesResponse(
        lane=lane, served_from=source.served_from, tables=tables, terms=said.terms, unpublished=said.unpublished,
        release=source.release, release_unreadable=source.release_unreadable, revision=source.revision,
    )


@router.post(
    "/{lane}/{table}", response_model=LaneRowsResponse,
    dependencies=[Depends(rate_limit("hint")), Depends(proxies(lanes=_all_lanes()))],
)
async def lane_rows(
    request: Request, settings: SettingsDep, lane: str, table: str, body: LaneLookup
) -> LaneRowsResponse:
    """The rows of one lane table matching identifier keys, from this box's snapshot or, when it does not
    hold the lane, from the lane's published repo. Keyed and bounded: nothing enumerates a lane."""
    try:
        found = await run_in_threadpool(lane_service.lookup, lane, table, body.keys, settings)
    except lane_service.LaneLookupError as exc:
        raise _refusal(request, exc) from exc
    said = lane_service.lane_terms(found.lane)
    return LaneRowsResponse(
        lane=found.lane, table=found.table, served_from=found.served_from, rows=found.rows,
        truncated=found.truncated, terms=said.terms, unpublished=said.unpublished,
        release=found.release, release_unreadable=found.release_unreadable, revision=found.revision,
    )
