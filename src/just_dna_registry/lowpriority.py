"""
Run a publish on a dedicated, niced thread instead of a shared threadpool worker.

Publish is the registry's one genuinely unattended path: nothing is watching it, it may spend
minutes in the enricher's pacing and seconds more compiling parquet, and it must not make an
interactive `/check` slower while it does. Two things make it yield, and the second is the reason
this module exists rather than a one-line `os.nice` inside the existing worker.

**It concedes CPU.** `os.setpriority` on a native thread id is per-thread on Linux, so the compile —
which is real work: parquet writes, SHA-256 over every artifact — runs at a nice value the scheduler
uses to prefer everything else. That matters for the compile, not the enrichment; a paced HTTP call
spends its time asleep and gains nothing from priority either way.

**It concedes a worker, which matters more.** Starlette's threadpool is small and fixed, and it is
what `/check` and every other blocking handler need in order to run at all. A long publish holding
one is a resource an interactive request cannot have. So a publish gets its own thread, created for
it and discarded after, and the anyio pool is left alone.

## Why the thread has to be disposable

This is the constraint the design turns on. **Raising a thread's nice value is unprivileged;
lowering it back is not** — `setpriority` returns `EPERM` without `CAP_SYS_NICE`, so
`finally: restore()` does not work and cannot be made to work. anyio *reuses* its workers, so
nice-ing one would leave it permanently degraded and hand the penalty to whichever request it served
next — quite possibly the `/check` this was all meant to protect. A thread we own and throw away
carries its nice value to the grave with it, which is exactly the lifetime the setting wants.

The cost is one thread per publish. At publish volumes that is nothing, and it buys a hard guarantee
rather than a scheduling hint.
"""

import asyncio
import contextvars
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger("registry.lowpriority")

T = TypeVar("T")

#: Set once, the first time renicing is refused, so a container without the privilege says so once
#: rather than on every publish.
_warned = threading.Event()


def _renice(increment: int) -> None:
    """Lower the calling thread's scheduling priority. Best-effort and one-way.

    Addressed by native thread id rather than the `0` shorthand: POSIX defines `PRIO_PROCESS` over a
    *process*, Linux implements nice per-thread, and passing the tid is what makes the target
    unambiguous instead of dependent on the libc's reading.

    A failure is not an error. Renicing is an optimisation, a container may forbid it, and refusing
    to publish because the scheduler hint could not be applied would trade a real capability for a
    cosmetic one.
    """
    if increment <= 0:
        return
    tid = threading.get_native_id()
    try:
        os.setpriority(os.PRIO_PROCESS, tid, increment)
    except (OSError, AttributeError) as exc:
        # AttributeError covers a platform with no `setpriority` at all (Windows).
        if not _warned.is_set():
            _warned.set()
            logger.info(
                "could not lower publish thread priority (%s) — publishes will run at normal "
                "priority. Harmless; they still run off the shared threadpool.", exc
            )


async def run_at_low_priority(fn: Callable[..., T], nice: int = 10, /, **kwargs: Any) -> T:
    """Await `fn(**kwargs)` on a fresh, niced thread. The thread is discarded when it returns.

    `fn` and `nice` are **positional-only**, and that is not style. Every remaining keyword belongs
    to the target, and `publish_version` takes a `name=`; a keyword parameter of our own would shadow
    it and fail with a missing-argument error a caller has no way to anticipate. Positional-only
    makes the collision impossible for any target rather than for the ones we thought of.

    Contextvars are copied in explicitly. `run_in_threadpool`, which this replaces on the publish
    path, does that for the caller; a bare executor does not, and losing the context would silently
    detach the work from anything request-scoped that reads it.

    The executor is shut down with `wait=False` rather than by a `with` block: on cancellation —
    a client hanging up mid-publish — `__exit__` would join the thread, which means blocking the
    event loop for however long the publish still has to run. The thread finishes and exits on its
    own either way.
    """
    context = contextvars.copy_context()

    def target() -> T:
        _renice(nice)
        return context.run(lambda: fn(**kwargs))

    pool = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix=f"registry-{getattr(fn, '__name__', 'task')}"
    )
    try:
        return await asyncio.wrap_future(pool.submit(target))
    finally:
        pool.shutdown(wait=False)
