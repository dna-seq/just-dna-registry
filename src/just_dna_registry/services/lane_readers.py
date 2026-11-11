"""Which parts of this server open each snapshot lane, read off the places that open them (0.28.4).

`warm-caches` and `drop-caches` tagged a lane with its `/check` group or `[not read here]`, from
`LANE_GROUPS`, which covers the publish and `/check` passes and nothing else. So `pubmind`, `civic` and
`clinvar_gkm`, which every enrichment opens, and `strchive` and `mitomap_miss`, which `POST /drafts`
opens, were all "not read here", and `drop-caches` removed them without `--force`. The answer is now
assembled from the tuples the call sites themselves use:

* `publish` — `enrich.ENRICH_LANES`, the `<lane>_cache` arguments `enrich_spec` hands `enrich()`; every
  publish, `/check` and `POST .../derived` runs it.
* `check: <group>` — `enrich.LANE_GROUPS`, the `/check` passes beyond enrichment (PGx, ACMG, metrics).
* `proxy: hints` — `hints.HINT_LANES`; `proxy: drafts` — every `drafting.DRAFT_SOURCES` entry's lanes;
  `proxy: derived` — `ENRICH_LANES` again, since that route is an enrichment.
* `builds: <lane>` — a parent of a derived lane something here reads (`mitomap` for `mitomap_miss`).

The same answer reaches `GET /caches` as each lane's `readers` (0.28.5), and both render through
`lane_tags.reader_tag`. A lane with none is read by nothing in this server. That is a statement about this server only: the
same box may run `just-dna-enricher` by hand, which is why `warm-caches --all` still offers every lane.
"""

from just_dna_registry.lane_tags import LOOKUP, PROXY_PREFIX, PUBLISH
from just_dna_registry.services.drafting import DRAFT_SOURCES
from just_dna_registry.services.enrich import ENRICH_LANES, LANE_GROUPS, cache_lanes
from just_dna_registry.services.hints import HINT_LANES
from just_dna_registry.services.passes import PASS_LANES


def lane_readers() -> dict[str, tuple[str, ...]]:
    """`{lane: readers}` for every lane the installed enricher knows; `()` means nothing here reads it."""
    lanes = cache_lanes()
    readers: dict[str, list[str]] = {name: [] for name in lanes}

    def add(lane: str, reader: str) -> None:
        if lane in readers and reader not in readers[lane]:
            readers[lane].append(reader)

    for lane in ENRICH_LANES:
        add(lane, PUBLISH)
    for lane, group in LANE_GROUPS.items():
        add(lane, f"check: {group}")
    for lane in ENRICH_LANES:
        add(lane, f"{PROXY_PREFIX}derived")
    for lane in HINT_LANES:
        add(lane, f"{PROXY_PREFIX}hints")
    for source in DRAFT_SOURCES.values():
        for lane in source.lanes:
            add(lane, f"{PROXY_PREFIX}drafts")
    for name, lane in lanes.items():
        if readers[name]:
            for parent in lane.parents:
                add(parent, f"builds: {name}")
    # The derived passes that read a snapshot on this box (0.30, `POST .../derived?passes=`).
    for lane in PASS_LANES.values():
        add(lane, f"{PROXY_PREFIX}passes")
    # The keyed lookup route answers every lane (0.30): `POST /lanes/{lane}/{table}`.
    for name in lanes:
        add(name, LOOKUP)
    return {name: tuple(found) for name, found in readers.items()}


def proxy_lanes() -> frozenset[str]:
    """The lanes the caching proxy's routes open (hints, drafts, derived), and the parents they build from."""
    readers = lane_readers()
    # The keyed lookup answers every lane, held or not (it reads a published repo remotely), so it is not
    # a reason to provision one; `--proxy` keeps meaning the routes that need the lane on this box.
    direct = {
        name for name, found in readers.items()
        if any(r.startswith(PROXY_PREFIX) and r != LOOKUP for r in found)
    }
    lanes = cache_lanes()
    return frozenset(direct | {parent for name in direct for parent in lanes[name].parents})
