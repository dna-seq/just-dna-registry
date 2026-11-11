"""What the caching proxy serves, read off the routes, against what upstream offers (0.30).

The caching proxy (0.25) was built per surface, and a lane or a pass that no surface reached was simply
not there: by 0.29 three of upstream's 17 snapshot lanes answered a keyed lookup through the registry and
three of its 16 producers ran here. Nothing compared the two rosters, so the gap grew with every upstream
release. The person, 2026-11-11: "we have a goddamn CACHING PROXY feature, not a transit". The pm's
requirements are in docs/ROADMAP.md, section 0.30.

Two rosters, both upstream's, never a list of ours:

* **Lanes**: `just_dna_enricher.caches.CACHE_LANES`. A lane is *proxied* when a route answers a keyed
  lookup of its rows, the same rows for the same key the snapshot gives on a caller's own machine.
* **Producers**: `just_dna_enricher.producers.DERIVED_PRODUCERS`, as `(table, command)` pairs, because two
  tables have two producers each and a guard keyed on tables passes with half a table served.

A route says what it serves with the `proxies(...)` dependency, and the guards in
`tests/test_proxy_coverage.py` read the app's routes for it, as the rate-limit guard reads
`rate_category`, so the served set is never kept by hand. Everything not served needs an entry in
`EXEMPT_LANES` / `EXEMPT_PRODUCERS` whose reason a reader can check: upstream's own text, a setting's
name, or a condition with its query beside it.

This module imports nothing from the enricher at module level: `client_cli` may not import `services/`,
and the dependency below is attached to routes on the server tier only.
"""

from collections.abc import Callable

#: The producers `enrich()` runs, which is everything `POST .../derived` hands back today: upstream's
#: roster names `enrich` as the command for these three tables (a test holds the two equal).
ENRICH_PRODUCERS: tuple[tuple[str, str], ...] = (
    ("resolution.csv", "enrich"),
    ("clin_sig_concordance.csv", "enrich"),
    ("clin_sig_authority_calls.csv", "enrich"),
)

#: Lanes no route serves, each with a reason somebody can check. Empty is the goal.
EXEMPT_LANES: dict[str, str] = {}

#: `(table, command)` producers no route runs, each with a checkable reason. Empty is the goal.
EXEMPT_PRODUCERS: dict[tuple[str, str], str] = {}


def proxies(
    *, lanes: tuple[str, ...] = (), producers: tuple[tuple[str, str], ...] = ()
) -> Callable[[], None]:
    """A route dependency that does nothing at request time and says what the route serves.

    `lanes`: lanes whose rows the route returns for a key. `producers`: `(table, command)` pairs whose
    table the route hands back. Read by the coverage guards off `app.routes`."""

    def _marker() -> None:
        return None

    _marker.proxied_lanes = tuple(lanes)  # type: ignore[attr-defined]
    _marker.proxied_producers = tuple(producers)  # type: ignore[attr-defined]
    return _marker


def _walk(routes: list) -> list:
    """FastAPI includes a router as one `_IncludedRouter` entry (`original_router`) rather than
    flattening it, so a flat scan of `app.routes` misses the whole API (as `test_ratelimit` found)."""
    out = []
    for route in routes:
        inner = getattr(route, "original_router", None)
        out.extend(_walk(inner.routes) if inner is not None else [route])
    return out


def served(app: object) -> tuple[set[str], set[tuple[str, str]]]:
    """Every lane and producer some route of `app` declares it serves."""
    lanes: set[str] = set()
    producers: set[tuple[str, str]] = set()
    for route in _walk(list(getattr(app, "routes", []))):
        dependant = getattr(route, "dependant", None)
        stack = list(dependant.dependencies) if dependant is not None else []
        while stack:
            dep = stack.pop()
            lanes.update(getattr(dep.call, "proxied_lanes", ()))
            producers.update(getattr(dep.call, "proxied_producers", ()))
            stack.extend(dep.dependencies)
    return lanes, producers
