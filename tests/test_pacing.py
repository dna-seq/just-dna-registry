"""The per-upstream pace ledger (0.25) — budgets, decay, and the day-to-day cooldown.

Every test drives a real `PaceLedger` with an injected clock and calendar, so a week of behaviour is
asserted without a single `sleep`. Nothing here mocks the schedule it is checking.
"""

import math

import pytest

from just_dna_registry import pacing


class FakeTime:
    """A monotonic clock and a UTC calendar the test drives by hand."""

    def __init__(self, day: str = "2026-09-11") -> None:
        self.now = 0.0
        self.day = day

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def next_day(self) -> None:
        year, month, dayno = (int(part) for part in self.day.split("-"))
        self.day = f"{year:04d}-{month:02d}-{dayno + 1:02d}"
        self.advance(86_400.0)


@pytest.fixture
def clock() -> FakeTime:
    return FakeTime()


def ledger(clock: FakeTime, **kwargs) -> pacing.PaceLedger:
    kwargs.setdefault("budgets", {"gnomad": 4, "ncbi": 8, "ensembl": 8})
    return pacing.PaceLedger(clock=lambda: clock.now, today=lambda: clock.day, **kwargs)


def spend(led: pacing.PaceLedger, clock: FakeTime, upstream: str, times: int,
          *, gap: float = 10_000.0) -> list[pacing.PaceVerdict]:
    """Charge `times` units, leaving a long gap so no reservation is outstanding."""
    out = []
    for _ in range(times):
        clock.advance(gap)
        out.append(led.charge("author", {upstream: 1})[0])
    return out


def test_the_free_tier_costs_nothing_and_says_so(clock: FakeTime) -> None:
    """Under budget there is no wait, no tier and no remedy — and `charged` is still reported."""
    led = ledger(clock)
    verdicts = spend(led, clock, "gnomad", 4)

    assert [v.tier for v in verdicts] == [0, 0, 0, 0]
    assert [v.wait_seconds for v in verdicts] == [0.0, 0.0, 0.0, 0.0]
    assert {v.remedy for v in verdicts} == {None}
    assert [v.spent for v in verdicts] == [1, 2, 3, 4]


def test_an_offline_answer_is_charged_zero_and_still_returns_a_verdict(clock: FakeTime) -> None:
    """`charged: 0` is the field that teaches a client which of its traffic is free."""
    led = ledger(clock)
    (verdict,) = led.charge("author", {"gnomad": 0})

    assert verdict.charged == 0
    assert verdict.spent == 0
    assert verdict.wait_seconds == 0.0
    assert verdict.budget == 4


def test_the_tier_steps_at_the_budget_and_at_each_doubling(clock: FakeTime) -> None:
    """Tier boundaries are N, 2N, 4N, 8N — asserted as the whole mapping, not a spot check."""
    led = ledger(clock)
    verdicts = spend(led, clock, "gnomad", 32)
    budget = led.budget_for("gnomad")

    observed = {v.spent: v.tier for v in verdicts}
    expected = {
        spent: (0 if spent <= budget else math.ceil(math.log2(spent / budget)))
        for spent in observed
    }
    assert observed == expected
    # The boundary is strict: the Nth request is still free, the (N+1)th is not.
    assert observed[budget] == 0
    assert observed[budget + 1] == 1
    assert observed[budget * 2] == 1
    assert observed[budget * 2 + 1] == 2
    assert observed[budget * 4] == 2


def test_the_interval_is_a_multiple_of_the_upstreams_own_spacing(clock: FakeTime) -> None:
    """A decayed wait is `base_interval * 2**tier`, so the number in a 429 means something."""
    led = ledger(clock)
    spend(led, clock, "gnomad", 5)          # one past budget, tier 1 from here

    clock.advance(10_000.0)
    led.charge("author", {"gnomad": 1})     # takes the slot
    clock.advance(0.0)
    (verdict,) = led.charge("author", {"gnomad": 1})

    base = pacing.UPSTREAMS["gnomad"].base_interval
    assert verdict.tier == 1
    assert verdict.wait_seconds == pytest.approx(base * 2)
    assert verdict.remedy is not None


def test_the_wait_is_a_reservation_so_a_burst_queues_instead_of_colliding(clock: FakeTime) -> None:
    """Each charge claims the next slot. Without this a concurrent burst all egresses at once."""
    led = ledger(clock)
    spend(led, clock, "gnomad", 5)          # past budget

    clock.advance(10_000.0)
    burst = [led.charge("author", {"gnomad": 1})[0] for _ in range(4)]
    waits = [v.wait_seconds for v in burst]

    assert waits == sorted(waits)
    assert len(set(waits)) == len(waits), "a burst that all waits the same amount is not paced"

    # Each successive reservation is one interval further out, at whatever tier that charge landed
    # on — the tier can rise mid-burst, so the gaps are not constant and must not be asserted as if
    # they were.
    base = pacing.UPSTREAMS["gnomad"].base_interval
    gaps = [round(b - a, 6) for a, b in zip(waits[:-1], waits[1:], strict=True)]
    expected = [round(base * (2**v.tier), 6) for v in burst[1:]]
    assert gaps == expected
    assert burst[-1].tier >= burst[0].tier


def test_budgets_are_per_upstream_and_never_exchangeable(clock: FakeTime) -> None:
    """Exhausting gnomAD must not slow NCBI — one fungible counter is the failure this prevents."""
    led = ledger(clock)
    spend(led, clock, "gnomad", 32)

    clock.advance(10_000.0)
    (ncbi,) = led.charge("author", {"ncbi": 1})

    assert ncbi.tier == 0
    assert ncbi.wait_seconds == 0.0
    assert ncbi.budget == 8 != led.budget_for("gnomad")


def test_a_new_day_resets_the_spend_and_halves_the_allowance_after_an_over_day(
    clock: FakeTime,
) -> None:
    """The cooldown is on the allowance, not the tier — and a clean day restores it in full."""
    led = ledger(clock, min_daily_units=1)
    ended = spend(led, clock, "gnomad", 32)[-1]
    assert ended.tier == 3, "32 units against an allowance of 4 is three doublings"

    clock.next_day()
    (fresh,) = led.charge("author", {"gnomad": 0})
    assert fresh.spent == 0, "the day's spend resets"
    assert fresh.budget == 2, "yesterday was over, so today's allowance is halved"

    clock.next_day()  # a clean day just ended (nothing was spent), so the streak resets
    assert led.charge("author", {"gnomad": 0})[0].budget == 4


def test_a_caller_spreading_the_overspend_across_days_is_ratcheted_not_forgiven(
    clock: FakeTime,
) -> None:
    """The hole this schedule exists to close, driven rather than asserted about the formula.

    A caller who wants ten allowances takes them on ten separate days. Under a plain nightly reset
    that costs nothing; under a tier carried down one step it still costs nothing, because ending
    each day at tier 1 carries 0. Halving the allowance is what makes the second day dearer than the
    first.
    """
    led = ledger(clock, min_daily_units=1)
    steady = led.budget_for("gnomad") * 2

    allowances, tiers = [], []
    for _ in range(5):
        spend(led, clock, "gnomad", steady)
        verdict = led.charge("author", {"gnomad": 0})[0]
        allowances.append(verdict.budget)
        tiers.append(verdict.tier)
        clock.next_day()

    assert allowances == sorted(allowances, reverse=True), f"the allowance did not ratchet: {allowances}"
    assert allowances[0] > allowances[-1]
    assert tiers == sorted(tiers), f"the same daily spend got cheaper over time: {tiers}"
    assert min(tiers) >= 1, "a repeat overspender was never paced at all"


def test_the_tier_is_capped_so_the_ledger_is_a_brake_not_a_ban(clock: FakeTime) -> None:
    led = ledger(clock, max_tier=2)
    verdicts = spend(led, clock, "gnomad", 64)

    assert max(v.tier for v in verdicts) == 2


def test_the_interval_is_capped(clock: FakeTime) -> None:
    led = ledger(clock, max_interval=10.0)
    spend(led, clock, "gnomad", 64)

    clock.advance(10_000.0)
    led.charge("author", {"gnomad": 1})
    (verdict,) = led.charge("author", {"gnomad": 1})

    assert verdict.wait_seconds == pytest.approx(10.0)


def test_a_disabled_ledger_still_counts_but_never_waits(clock: FakeTime) -> None:
    """Counting with the brake off keeps the report honest for an operator diagnosing the setting."""
    led = ledger(clock, enabled=False)
    verdicts = spend(led, clock, "gnomad", 32)

    assert max(v.spent for v in verdicts) == 32
    assert max(v.tier for v in verdicts) > 0
    assert {v.wait_seconds for v in verdicts} == {0.0}


def test_identities_do_not_share_a_budget(clock: FakeTime) -> None:
    led = ledger(clock)
    spend(led, clock, "gnomad", 32)

    clock.advance(10_000.0)
    (other,) = led.charge("someone-else", {"gnomad": 1})

    assert other.spent == 1
    assert other.tier == 0
    assert other.wait_seconds == 0.0


def test_every_upstream_carries_a_remedy_and_none_of_them_sells_a_key_we_do_not_have() -> None:
    """The honest-hint rule, asserted structurally rather than trusted to review.

    gnomAD sells no key at any price, so a remedy telling a caller to obtain one is a lie they can
    check; NCBI's key paces the process that holds it, so ours would not help them and theirs must
    not be sent here. Both remedies have to say the general escape — provision the snapshot, or run
    the enricher yourself — because that is the one answer that is true for every upstream.
    """
    assert set(pacing.UPSTREAMS) == {"ncbi", "ensembl", "gnomad", "literature", "ontology"}

    for name, terms in pacing.UPSTREAMS.items():
        assert terms.name == name
        assert terms.base_interval > 0
        assert terms.free_daily_units > 0
        assert terms.remedy.strip()
        assert "just-dna-enricher" in terms.remedy or "offline=true" in terms.remedy

    assert "no API key at any price" in pacing.UPSTREAMS["gnomad"].remedy
    assert "paces the process that holds it" in pacing.UPSTREAMS["ncbi"].remedy
    assert "issues no key" in pacing.UPSTREAMS["ensembl"].remedy
    assert "issue no key" in pacing.UPSTREAMS["ontology"].remedy
    assert "rather than a key" in pacing.UPSTREAMS["literature"].remedy


def test_the_spacing_can_be_grounded_in_the_client_that_actually_paces(clock: FakeTime) -> None:
    """`base_interval` is a fallback, not the truth: the real number is on the client.

    `EutilsClient` picks 10/s with `NCBI_API_KEY` set and 3/s without, so a constant in `UPSTREAMS`
    describes the wrong deployment half the time. A server passes the observed intervals in, and the
    decay is then a multiple of what the caller is actually being paced at.
    """
    led = ledger(clock, intervals={"gnomad": 0.25})
    assert led.interval_for("gnomad") == 0.25
    assert led.interval_for("ncbi") == pacing.UPSTREAMS["ncbi"].base_interval

    spend(led, clock, "gnomad", 5)
    clock.advance(10_000.0)
    led.charge("author", {"gnomad": 1})
    (verdict,) = led.charge("author", {"gnomad": 1})

    assert verdict.tier == 1
    assert verdict.wait_seconds == pytest.approx(0.25 * 2)


def test_gnomad_is_budgeted_far_below_the_others_because_its_limit_cannot_be_bought() -> None:
    """The one budget relation that is a design decision rather than a tuning choice."""
    gnomad = pacing.UPSTREAMS["gnomad"]
    others = [t.free_daily_units for name, t in pacing.UPSTREAMS.items() if name != "gnomad"]
    assert gnomad.free_daily_units < min(others) // 10
    assert gnomad.base_interval == 6.0, "gnomAD publishes 10 requests per 60 seconds"
    assert gnomad.base_interval == max(t.base_interval for t in pacing.UPSTREAMS.values())
