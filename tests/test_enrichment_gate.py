"""
The two-lane enrichment gate: `/check` takes or fails, publish queues and yields.

The asymmetry is the whole design, so these tests are about the *difference* between the lanes
rather than about mutual exclusion, which any semaphore would give.
"""

import asyncio
import time
from unittest import mock

import pytest

from just_dna_registry.lowpriority import run_at_low_priority
from just_dna_registry.services.enrich import EnrichmentGate


def _gate(**kw) -> EnrichmentGate:
    # Quiet/poll wound right down: these assert ordering and deference, not wall-clock policy.
    kw.setdefault("quiet_seconds", 0.0)
    kw.setdefault("poll_seconds", 0.01)
    return EnrichmentGate(kw.pop("limit", 1), **kw)


def test_check_fails_fast_and_publish_waits(anyio_backend=None) -> None:
    """The same full gate is a `503` for one lane and a queue for the other.

    A dry run has someone watching, so queueing behind a multi-minute paced run would turn a quick
    rejection into a slow timeout. A publish has nobody watching and an upload already spent, so a
    rejection would cost a whole re-upload for a reason that evaporates in seconds.
    """

    async def scenario() -> None:
        gate = _gate()
        assert gate.try_acquire() is True

        assert gate.try_acquire() is False, "interactive must never queue"

        waiter = asyncio.create_task(gate.acquire_idle())
        await asyncio.sleep(0.05)
        assert not waiter.done(), "idle must queue rather than fail"
        assert gate.waiting == 1

        gate.release()
        await asyncio.wait_for(waiter, timeout=2)
        assert gate.active == 1 and gate.waiting == 0

    asyncio.run(scenario())


def test_a_queued_publish_defers_to_interactive_demand() -> None:
    """Deference is measured against *demand*, not against grants.

    A `/check` that was refused still moves the quiet marker. That is the case worth pinning: a
    server busy enough to be rejecting dry runs is exactly the server a publish should stay out of
    the way on, and keying deference on successful acquisitions would read that as an idle system.
    """

    async def scenario() -> None:
        gate = _gate(quiet_seconds=0.3)
        gate._last_interactive = float("-inf")

        # A rejected interactive attempt: the gate is free, so this one is granted, then released.
        assert gate.try_acquire() is True
        gate.release()

        waiter = asyncio.create_task(gate.acquire_idle())
        await asyncio.sleep(0.1)
        assert not waiter.done(), "still inside the quiet window"

        await asyncio.wait_for(waiter, timeout=2)

    asyncio.run(scenario())


def test_queued_publishes_are_served_in_arrival_order() -> None:
    """Without a ticket, waiters poll on their own timers and whichever wakes first wins, so an
    early publish can be overtaken indefinitely by later arrivals."""

    async def scenario() -> None:
        gate = _gate()
        assert gate.try_acquire() is True
        order: list[int] = []

        async def publisher(n: int) -> None:
            await gate.acquire_idle(label=f"publish-{n}")
            order.append(n)

        tasks = []
        for n in range(3):
            tasks.append(asyncio.create_task(publisher(n)))
            await asyncio.sleep(0.02)  # stagger arrival, which is what "order" means here

        for _ in range(3):
            gate.release()
            await asyncio.sleep(0.05)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

        assert order == [0, 1, 2]

    asyncio.run(scenario())


def test_a_cancelled_publish_drops_its_place_in_the_queue() -> None:
    """A client that hung up must not keep a ticket — the next waiter would block on a caller
    nobody is waiting for."""

    async def scenario() -> None:
        gate = _gate()
        assert gate.try_acquire() is True

        first = asyncio.create_task(gate.acquire_idle(label="abandoned"))
        await asyncio.sleep(0.02)
        second = asyncio.create_task(gate.acquire_idle(label="live"))
        await asyncio.sleep(0.02)
        assert gate.waiting == 2

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        gate.release()

        await asyncio.wait_for(second, timeout=2)
        assert gate.waiting == 0

    asyncio.run(scenario())


def _our_threads() -> list[str]:
    """Threads this module's machinery created. Counted by name rather than with
    `threading.active_count()`, which is process-global — an unrelated pool winding down in another
    test would otherwise break the assertion and read as a real regression."""
    import threading

    return [t.name for t in threading.enumerate() if t.name.startswith("registry-")]


def test_waiting_costs_no_thread() -> None:
    """The load-bearing concession, and the one a semaphore in a worker would get wrong.

    Starlette's threadpool is small and fixed, and it is what an interactive request needs in order
    to run at all. A publish queued in a worker would starve the very calls it is meant to yield to,
    so the wait happens in the coroutine — asserted by queueing twenty and finding no thread behind
    any of them.
    """

    async def scenario() -> None:
        gate = _gate()
        assert gate.try_acquire() is True

        waiters = [asyncio.create_task(gate.acquire_idle(label=f"p{n}")) for n in range(20)]
        await asyncio.sleep(0.1)
        assert gate.waiting == 20
        assert _our_threads() == [], "queued publishes must not each hold a thread"

        for task in waiters:
            task.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)

    asyncio.run(scenario())


# ── the disposable low-priority worker ────────────────────────────────────────


def test_the_publish_thread_is_niced_and_not_reused() -> None:
    """Raising a nice value is unprivileged; lowering it back is not.

    So the thread has to be disposable — a pooled worker niced once could never be restored, and
    would hand the penalty to whichever request it served next. This asserts both halves: the work
    really does run niced, and it runs on a thread that does not survive to serve anything else.
    """
    import os
    import threading

    def sample() -> tuple[int, int]:
        tid = threading.get_native_id()
        return tid, os.getpriority(os.PRIO_PROCESS, tid)

    async def scenario() -> tuple[tuple[int, int], tuple[int, int]]:
        return (
            await run_at_low_priority(sample, 7),
            await run_at_low_priority(sample, 7),
        )

    main_before = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())
    (tid_a, nice_a), (tid_b, nice_b) = asyncio.run(scenario())

    assert nice_a == nice_b == 7
    assert tid_a != tid_b, "a niced thread must not be reused — its nice value cannot be undone"
    # Per-thread on Linux: the caller is untouched, which is what makes this safe to do at all.
    assert os.getpriority(os.PRIO_PROCESS, threading.get_native_id()) == main_before


def test_a_worker_that_never_starts_does_not_strand_the_permit() -> None:
    """The permit is released by the worker's own `finally`, so a worker that never runs leaves
    nobody to release it.

    Cheap to overlook and expensive now that publishes queue without a deadline: with a limit of 1,
    a stranded permit does not merely slow throughput, it hangs every subsequent publish for the
    life of the process. `_run_queued`'s `RuntimeError` arm is the guard.
    """
    from just_dna_registry.api.routers.publish import _run_queued
    from just_dna_registry.config import Settings

    settings = Settings(publish_nice=0)
    gate = _gate()

    async def scenario() -> None:
        assert await gate.acquire_idle() is None
        assert gate.active == 1

        def never_runs(*, gate) -> None:  # noqa: ARG001 — the signature the real targets have
            raise AssertionError("must not be reached")

        with mock.patch(
            "just_dna_registry.lowpriority.ThreadPoolExecutor.submit",
            side_effect=RuntimeError("can't start new thread"),
        ), pytest.raises(RuntimeError):
            await _run_queued(never_runs, gate, settings)

        assert gate.active == 0, "the permit must not outlive a worker that never started"
        # And the gate is genuinely usable again, which is the thing that actually broke.
        await asyncio.wait_for(gate.acquire_idle(), timeout=2)

    asyncio.run(scenario())


def test_target_keyword_arguments_are_not_shadowed() -> None:
    """`publish_version` takes `name=`, so a keyword parameter of the wrapper's own would shadow it
    and fail with a missing-argument error the caller cannot anticipate. Positional-only prevents it
    for every target, not just the ones we thought of."""

    def target(*, name: str, nice: str) -> str:
        return f"{name}/{nice}"

    assert asyncio.run(run_at_low_priority(target, 0, name="mod", nice="not-a-priority")) == (
        "mod/not-a-priority"
    )


def test_the_worker_does_not_outlive_its_call() -> None:
    """The disposal half of the disposable thread.

    `shutdown(wait=False)` frees the event loop immediately rather than joining — which is what
    keeps a cancelled publish from blocking the loop for the rest of its run — so the thread has to
    exit on its own once the target returns. If it did not, one leaked niced thread per publish
    would accumulate for the life of the process.
    """
    asyncio.run(run_at_low_priority(lambda: time.sleep(0.01), 0))
    deadline = time.monotonic() + 2
    while _our_threads() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _our_threads() == []
