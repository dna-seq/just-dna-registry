"""Per-upstream egress budgets with a decaying pace — the third layer of cost control (0.25).

There are now three, and they answer three different questions. `ratelimit.RateLimiter` bounds **one
caller's request rate**. `services/enrich.EnrichmentGate` bounds **the process's concurrency** against
a pace that lives on the shared client bundle. Neither can answer *"how much of a budget we cannot
buy has this caller spent today, and against which upstream?"*, which is the question a proxy has to
answer and an ordinary service does not.

**Why a proxy needs a third layer at all.** The upstreams the enricher reaches are unauthenticated
and throttle by **IP**, so every caller of `/api/v1/hint/*` spends the *deployment's* standing rather
than their own. gnomAD publishes ten requests per sixty seconds and offers no API key at any price:
there is no quota to top up, no per-caller scoping, and an overspend throttles the whole box — for
every publisher on it, since `/check?frequencies=true` draws on the same allowance. A token bucket
sized per caller is unbounded in the number of callers, which is exactly the arithmetic that fails.

**The units are not exchangeable, so the ledger does not exchange them.** One fungible "egress unit"
would let a caller spend the unbuyable ten-per-minute gnomAD allowance at the price of a
three-per-second eutils call. Each upstream carries its own budget and its own spacing, both declared
in `UPSTREAMS` beside the remedy sentence a caller is given when they run out — see the docstring
there for why three of the four honest remedies are *not* "get an API key".

**It is process-wide, for the reason `shared_lookup_clients()` is.** A ledger built per request paces
nothing: the pacing state is the whole product. Same honest caveat as `ratelimit.py` carries — this
is process-local, so two replicas is two ledgers and two budgets, a restart forgives a streak, and
horizontal scaling needs a shared store here as much as it does for the buckets. A caller cannot
restart our server, so restart-amnesty is not an exploit; two replicas against one IP is a real
concern and belongs in the deployment notes rather than in this file.

**Not in the catalog DB.** That database is a rebuildable projection of the published manifests, and
a pace ledger is derivable from no manifest — so putting it there means either `reindex` wipes it or
the rebuild has to preserve rows it cannot derive, and the invariant breaks in both directions. If
durability across restarts is ever wanted, it wants a separate store, not a table next to the catalog.
"""

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class UpstreamTerms:
    """One upstream's spacing, its daily allowance, and the honest thing to tell a caller.

    **`remedy` is per upstream because "obtain a personal key" is wrong for three of the four**, and a
    generic version of it sends a caller to buy something that does not exist. gnomAD sells no key at
    any price. NCBI's key is free but paces *the process that holds it*, so ours would not help a
    caller and theirs must not be sent here. PharmVar's is personal and non-transferable under their
    terms §2, so it must never be the operator's on a shared box. Only the general remedy is the same
    everywhere, and it is the point of the whole surface: provision the snapshot, or run this service
    yourself.
    """

    name: str
    #: The upstream's own published spacing. The decay is expressed as a multiple of it so the figure
    #: in a `429` means something — "4x gnomAD's own interval" is actionable where "24 seconds" is
    #: arbitrary — and so one schedule produces gentle behaviour where the budget is cheap and hard
    #: behaviour where it cannot be bought, with no special case per upstream.
    base_interval: float
    #: Units per identity per UTC day before the pace starts decaying.
    free_daily_units: int
    remedy: str


#: Every upstream a hint request can spend, with the terms it is spent under. A closed vocabulary: a
#: charge naming an upstream that is not here is a programming error, never a silently free call.
UPSTREAMS: dict[str, UpstreamTerms] = {
    "ncbi": UpstreamTerms(
        name="ncbi",
        # 3/s without a key, 10/s with one. `EutilsClient` reads `NCBI_API_KEY` at construction.
        base_interval=1.0 / 3.0,
        # The whole sizing case: four simultaneous authors on a 128-row module. 512 calls at 3/s is
        # about 171 seconds of aggregate pacing, which the gate already serializes.
        free_daily_units=512,
        remedy=(
            "NCBI issues a free API key that raises 3/s to 10/s, but it paces the process that holds "
            "it — this proxy cannot spend yours, and sending it here would put your credential on "
            "our IP. Set NCBI_API_KEY where you run just-dna-enricher, or use offline=true against "
            "this registry's snapshots."
        ),
    ),
    "ensembl": UpstreamTerms(
        name="ensembl",
        # Paced by `EnsemblResolver`'s own gate; no hard published figure in this tree, and inventing
        # one would be worse than deriving the decay from a conservative spacing.
        base_interval=1.0,
        free_daily_units=512,
        remedy=(
            "Ensembl issues no key; the pacing is all there is. A provisioned Ensembl snapshot "
            "removes this leg entirely — pull one with `just-dna-enricher cache pull`, or ask this "
            "registry with offline=true, which reads the snapshot it already holds."
        ),
    ),
    "gnomad": UpstreamTerms(
        name="gnomad",
        # 10 per 60s, published, keyed on our IP.
        base_interval=6.0,
        # Deliberately two orders of magnitude below the others. 512 frequency lookups is 51 minutes
        # serialized and 85% of what gnomAD grants the WHOLE deployment in an hour — the same
        # allowance `/check?frequencies=true` needs to gate a publish. A free tier that can eat the
        # publishing capability is not a free tier.
        free_daily_units=20,
        remedy=(
            "gnomAD publishes 10 requests per 60 seconds and sells no API key at any price, so there "
            "is no quota to top up and no per-caller scoping: an overspend throttles this whole "
            "deployment. Your options are offline=true against this registry's snapshot, or running "
            "just-dna-enricher yourself."
        ),
    ),
}


@dataclass
class _Entry:
    """One identity's standing against one upstream. Reset per UTC day, except the tier."""

    day: str
    spent: int = 0
    #: Consecutive days this identity has finished over its allowance. It halves the *next* day's
    #: allowance, which is the cooldown — see `PaceLedger._entry` for why carrying the tier down one
    #: step instead leaves a hole a caller can sit in forever.
    over_streak: int = 0
    #: Monotonic timestamp of the last charged call, or `None` before the first one.
    last_charge: float | None = None


@dataclass(frozen=True)
class PaceVerdict:
    """What one upstream's charge cost, and what the caller has to be told about it.

    `wait_seconds` is a *minimum interval*, not a sentence: a short one is absorbed by the handler
    before it takes a gate permit, a long one becomes a `429` with `Retry-After`. The split lives in
    the router because it is a policy about connections, not about budgets.

    **`charged` is reported even when it is zero**, and that is the field that teaches a client the
    thing this whole surface exists to teach: an `offline=true` answer costs nothing. Without it a
    caller has no way to learn which of their traffic is free, and "you are being throttled" has two
    opposite histories — spent egress, or a plain bucket refusal — with opposite remedies.
    """

    upstream: str
    charged: int
    spent: int
    budget: int
    tier: int
    wait_seconds: float
    #: Present only past the free tier. A remedy attached to every answer would train a reader to
    #: skip it, and this one has to be read the first time it appears.
    remedy: str | None


class PaceLedger:
    """Per-identity, per-upstream daily budgets with an exponentially decaying pace.

    Two schedules, and both are needed because either alone has a hole:

    * **Within the day** — once an identity is past its budget the minimum interval between charged
      calls is `base_interval * 2**tier`, where the tier steps at the budget, twice it, four times it
      and so on. That is "the pace decays": a caller is slowed rather than cut off.
    * **Across days** — a day that ended at tier *k* starts the next day at `max(0, k-1)`, not at 0.
      A pure nightly reset is trivially defeated by spreading ten budgets over ten days at full pace,
      which is precisely the caller this exists for. One step of forgiveness per clean day pardons a
      one-off burst and raises the floor under a persistent one.

    The window is the UTC day rather than a rolling 24 hours: rolling is fairer and needs a
    per-identity event log, a day counter is two integers and a date string, and the fairness
    difference does not survive the fact that this is process-local anyway.

    The clock is injectable so the tests can walk an identity through a week without sleeping.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_tier: int = 6,
        max_interval: float = 300.0,
        min_daily_units: int = 4,
        budgets: Mapping[str, int] | None = None,
        clock=time.monotonic,  # noqa: ANN001 — a callable returning float, matching time.monotonic
        today=None,  # noqa: ANN001 — a callable returning a YYYY-MM-DD str
    ) -> None:
        self.enabled = enabled
        self.max_tier = max_tier
        self.max_interval = max_interval
        self.min_daily_units = min_daily_units
        #: Overrides for `UPSTREAMS[...].free_daily_units`, so a deployment can retune a budget
        #: without editing the terms that carry the licence reasoning beside it.
        self.budgets = dict(budgets or {})
        self._clock = clock
        self._today = today or (lambda: datetime.now(UTC).date().isoformat())
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._lock = threading.Lock()

    def budget_for(self, upstream: str) -> int:
        return self.budgets.get(upstream, UPSTREAMS[upstream].free_daily_units)

    def _entry(self, identity: str, upstream: str) -> _Entry:
        """The identity's row for today, rolling the day over and carrying the tier down one step.

        Called under the lock.
        """
        day = self._today()
        entry = self._entries.get((identity, upstream))
        if entry is None:
            entry = _Entry(day=day)
            self._entries[(identity, upstream)] = entry
            return entry
        if entry.day != day:
            # **The allowance halves for each consecutive day spent over it, and a clean day resets
            # the streak.** A plain nightly reset is trivially defeated: a caller wanting ten budgets
            # spreads them over ten days and never leaves the free tier, which is precisely the caller
            # this exists for. Carrying the *tier* down one step instead — the first thing tried — has
            # a subtler version of the same hole: an identity spending exactly twice its allowance
            # every day ends each day at tier 1, carries 0, and gets its whole free tier back every
            # morning forever. Halving the allowance is what actually ratchets.
            #
            # `spent` resets; `last_charge` does not, because a spacing obligation does not expire at
            # midnight.
            entry.over_streak = entry.over_streak + 1 if entry.spent > self._allowance(entry, upstream) else 0
            entry.day = day
            entry.spent = 0
        return entry

    def _allowance(self, entry: _Entry, upstream: str) -> int:
        """Today's free units for this identity: the budget, halved once per consecutive over day.

        Floored at `min_daily_units` rather than at zero — a cooldown that reaches nothing is a ban,
        and a ban is what the decay exists instead of.
        """
        budget = self.budget_for(upstream)
        return max(self.min_daily_units, budget >> min(entry.over_streak, budget.bit_length()))

    def _tier_for(self, entry: _Entry, upstream: str) -> int:
        """How many doublings this identity is currently at. Called under the lock.

        Tier *k* begins the unit **after** `budget * 2**(k-1)`, so with a budget of 4 the free tier is
        1-4, tier 1 is 5-8, tier 2 is 9-16 and so on. The boundary is strict on purpose: "the first N
        queries at the usual pace" has to include the Nth, and a schedule that decays *at* N spends a
        caller's last free request on a wait they were promised they would not have.

        Computed by doubling rather than through `log2`, because the float version lands on the wrong
        side of an exact power of two often enough to matter and the loop runs at most `max_tier`
        times.
        """
        allowance = self._allowance(entry, upstream)
        if allowance <= 0 or entry.spent <= allowance:
            return 0
        tier = 1
        while tier < self.max_tier and allowance * (2**tier) < entry.spent:
            tier += 1
        return tier

    def charge(self, identity: str, charges: Mapping[str, int]) -> list[PaceVerdict]:
        """Commit units against one or more upstreams and say what the caller now owes in waiting.

        Committed **before** the call rather than measured after it, because nothing downstream
        reports what it actually spent (filed upstream as S92) and a meter that can only look
        backwards cannot refuse anything. The consequence is at most one over-charge per call, on a
        request that turned out to be served from a snapshot; reconciling that downward would invite a
        caller to game their own miss rate, so it is not refunded.

        A zero charge is still a verdict: `charged: 0` is how a client learns its offline traffic is
        free.

        **The wait is a reservation, not a sleep.** Like the enricher's own `PacingGate`, each charge
        claims the next slot — so a caller firing ten requests into a tier-1 gnomAD budget is told 12s,
        24s, 36s and so on rather than 12s ten times over. That is deliberate: the alternative lets a
        burst of concurrent requests all observe the same "last charge" and egress together, which is
        the pacing being per call again. It also means a hammering caller crosses the inline-absorb
        threshold almost immediately and starts receiving `429`s, which is the intended outcome.
        """
        now = self._clock()
        verdicts: list[PaceVerdict] = []
        with self._lock:
            for upstream, units in charges.items():
                terms = UPSTREAMS[upstream]
                entry = self._entry(identity, upstream)
                if units > 0:
                    entry.spent += units
                allowance = self._allowance(entry, upstream)
                tier = self._tier_for(entry, upstream)
                wait = 0.0
                if self.enabled and units > 0 and tier > 0:
                    interval = min(self.max_interval, terms.base_interval * (2**tier))
                    if entry.last_charge is not None:
                        wait = max(0.0, entry.last_charge + interval - now)
                if units > 0:
                    entry.last_charge = now + wait
                verdicts.append(
                    PaceVerdict(
                        upstream=upstream,
                        charged=units,
                        spent=entry.spent,
                        budget=allowance,
                        tier=tier,
                        wait_seconds=wait,
                        remedy=terms.remedy if tier > 0 else None,
                    )
                )
        return verdicts
