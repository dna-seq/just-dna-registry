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

import threading
import time


class RateLimiter:
    """Token buckets keyed by (identity, category). `limits[category] = (capacity, refill_per_sec)`."""

    def __init__(self, limits: dict[str, tuple[float, float]], enabled: bool = True) -> None:
        self.limits = limits
        self.enabled = enabled
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, identity: str, category: str) -> bool:
        # NB: an unknown category is allowed unconditionally, so a route that asks for a bucket
        # nobody registered in `default_limiter` is silently unlimited. `test_ratelimit.py` pins the
        # exact bucket set for that reason — a typo here fails loudly instead of opening a door.
        if not self.enabled or category not in self.limits:
            return True
        capacity, refill = self.limits[category]
        now = time.monotonic()
        with self._lock:
            tokens, updated = self._buckets.get((identity, category), (capacity, now))
            tokens = min(capacity, tokens + (now - updated) * refill)
            if tokens < 1.0:
                self._buckets[(identity, category)] = (tokens, now)
                return False
            self._buckets[(identity, category)] = (tokens - 1.0, now)
            return True


#: Every bucket the service defines. Named here (rather than only inside `default_limiter`) so a
#: test can assert the set matches what the routes actually ask for.
CATEGORIES: frozenset[str] = frozenset(
    {"publish", "download", "search", "social", "validate", "enrich"}
)


def default_limiter(settings) -> RateLimiter:
    """Build a limiter from settings.

    Defaults: publish 10/h, download 1000/h, search 60/min, social 30/min, validate 60/h, enrich 5/h.

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
        },
        enabled=settings.rate_limit_enabled,
    )
