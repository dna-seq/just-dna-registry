"""
In-memory token-bucket rate limiting (SPEC §7). Per-caller (API key if present, else client IP)
× category. MVP: process-local, no external store — good enough for a single-instance deployment;
swap for Redis buckets when horizontally scaled.

A token bucket bounds **one caller**, which is the right tool for fairness and the wrong tool on its
own for an endpoint whose cost is borne by the whole deployment. The upstreams the enricher talks to
are unauthenticated and rate-limit by **IP**, so overspending gets *this server* throttled rather than
the caller who did it. N accounts × 5/h is unbounded in N, and the pacing that keeps us inside those
limits lives on a client object rather than in this process, so concurrency also has to be capped —
see `EnrichmentGate` in `services/enrich.py`, which sits on top of the `enrich` bucket rather than
replacing it. Both are process-local, so with two replicas each limit is 2×;
horizontal scaling needs a shared store for the gate as much as for the buckets.
"""

import math
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateVerdict:
    """What `RateLimiter.take` decided, and — for a refusal — how long until it would not.

    `retry_after` is the seconds until one whole token is back, `(1 - tokens) / refill_per_sec`.
    It is what a `Retry-After` header should carry: through 0.25.2 every `429` said `60`, which on
    the 5/h `enrich` bucket (one token per 720s) sent a caller back twice inside the wait it
    described (S23). An unmetered category answers `allowed=True` with zeros.
    """

    allowed: bool
    retry_after: float
    capacity: float
    refill_per_sec: float


class RateLimiter:
    """Token buckets keyed by (identity, category). `limits[category] = (capacity, refill_per_sec)`."""

    def __init__(self, limits: dict[str, tuple[float, float]], enabled: bool = True) -> None:
        self.limits = limits
        self.enabled = enabled
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, identity: str, category: str) -> RateVerdict:
        """Spend one token, or say how long until one is there to spend."""
        # NB: an unknown category is allowed unconditionally, so a route that asks for a bucket
        # nobody registered in `default_limiter` is silently unlimited. `test_ratelimit.py` reads
        # the buckets routes ask for off the app for that reason — a typo here fails loudly
        # instead of opening a door.
        if not self.enabled or category not in self.limits:
            return RateVerdict(allowed=True, retry_after=0.0, capacity=0.0, refill_per_sec=0.0)
        capacity, refill = self.limits[category]
        now = time.monotonic()
        with self._lock:
            tokens, updated = self._buckets.get((identity, category), (capacity, now))
            tokens = min(capacity, tokens + (now - updated) * refill)
            if tokens < 1.0:
                self._buckets[(identity, category)] = (tokens, now)
                # A bucket configured with no refill (`rate_x_per_hour=0`) refuses forever; say
                # `inf` rather than divide by it, and let the route send no `Retry-After` at all.
                wait = (1.0 - tokens) / refill if refill > 0 else math.inf
                return RateVerdict(
                    allowed=False, retry_after=wait, capacity=capacity, refill_per_sec=refill,
                )
            self._buckets[(identity, category)] = (tokens - 1.0, now)
            return RateVerdict(allowed=True, retry_after=0.0, capacity=capacity, refill_per_sec=refill)

    def refund(self, identity: str, category: str) -> None:
        """Hand back the token `take` spent, for a request refused before it did the work the
        bucket prices.

        The bucket is a route *dependency*, so it resolves before the handler reaches the
        concurrency gate — and a `503 enrichment_busy` was spending an `enrich` token for a run that
        never happened. S23's batch was the arithmetic: one run, four busy refusals, and the caller's
        whole hour was gone. Bounded by `capacity`, so a refund never mints credit.
        """
        if not self.enabled or category not in self.limits:
            return
        capacity, _ = self.limits[category]
        with self._lock:
            entry = self._buckets.get((identity, category))
            if entry is None:
                return
            tokens, updated = entry
            self._buckets[(identity, category)] = (min(capacity, tokens + 1.0), updated)


#: Every bucket the service defines. Named here (rather than only inside `default_limiter`) so a
#: test can assert the set matches what the routes actually ask for.
CATEGORIES: frozenset[str] = frozenset(
    {"publish", "download", "search", "social", "validate", "enrich", "draft", "hint"}
)


def default_limiter(settings) -> RateLimiter:
    """Build a limiter from settings.

    Defaults: publish 10/h, download 1000/h, search 60/min, social 30/min, validate 60/h, enrich 5/h,
    draft 10/h, hint 600/h.

    The two pre-flight buckets are sized by who pays. `validate` costs server CPU — cheaper than a
    publish, since nothing is stored, but not free: it runs the real compiler over uploaded CSVs.
    `enrich` spends the deployment's shared standing with gnomAD and NCBI — both keyed on our IP, and
    gnomAD offers no API key at any price — plus minutes of paced waiting. Hence the tightest bucket
    in the service, and a concurrency gate behind it.
    """
    return RateLimiter(
        limits={
            "publish": (settings.rate_publish_per_hour, settings.rate_publish_per_hour / 3600.0),
            "download": (settings.rate_download_per_hour, settings.rate_download_per_hour / 3600.0),
            "search": (settings.rate_search_per_min, settings.rate_search_per_min / 60.0),
            "social": (settings.rate_social_per_min, settings.rate_social_per_min / 60.0),
            "validate": (settings.rate_validate_per_hour, settings.rate_validate_per_hour / 3600.0),
            "enrich": (settings.rate_enrich_per_hour, settings.rate_enrich_per_hour / 3600.0),
            # Drafting spends no egress — it is snapshot-only by construction — but it is duckdb over
            # a whole gene panel and it reads licence-gated snapshots this deployment acquired under
            # its own declared use. Tighter than `validate` for the first reason and authenticated
            # for the second.
            "draft": (settings.rate_draft_per_hour, settings.rate_draft_per_hour / 3600.0),
            # Burst control only: the bound on hint *egress* is the per-upstream pace ledger. Absent
            # from this dict through 0.25.2 while six routes asked for it and `rate_hint_per_hour`
            # sat unread in settings — so the hint proxy shipped unlimited. `CATEGORIES` matched
            # this dict exactly, which is why the guard that pinned the two to each other never
            # noticed; it now reads the route side off the app.
            "hint": (settings.rate_hint_per_hour, settings.rate_hint_per_hour / 3600.0),
        },
        enabled=settings.rate_limit_enabled,
    )
