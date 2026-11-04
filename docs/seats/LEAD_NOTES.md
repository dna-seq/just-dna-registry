# Lead — notes

The lead seat's working state, rewritten to the present before a reset (`docs/seats/LEAD.md`, "Before a reset").

## Now

Seated 2026-11-04 (first seating). The seat-builder's first work, as it stands:

1. **Retire the old triage waker**: done, 7ff1398, after triage reported its watcher fired.
2. **Id scripts stay** (`.claude/triage-state.py`, `.claude/triage-archive.py`); moving to the kit's
   `classes/triage/` is a later roadmap call, not filed yet.
3. **Seats pointer in CLAUDE.md**: done, ad1b570.
4. **Trust register** (`docs/TRUST.md`): asked the person once, 2026-11-04; open.
5. **Working tree**: `uv.lock` is no longer dirty (clean on 2026-11-04 at punch-in). `docs/DREAMS.md` was committed by
   the pm on the person's word (daeab95); closed.
6. **Kit pin**: this seat moves it; nothing waiting.

Avatar set (the admin's bowerbird).

## Plan, in order

0. Account handle rename (roadmap, minor, unattended): self-service and site admin, the person's answer
   2026-11-04. Built on the next minor's branch (main's [Unreleased] already holds minor material,
   `merge_accounts`), in its own worktree.
1. C1, declared correction filtered by `requires` (roadmap, unattended, patch).
2. C2, let `LookupClients.ensure` fill the shared bundle (roadmap, unattended, after C1, patch).
3. C3, name the release of a refused column: a new capability, asked of the person 2026-11-04; open.
4. The next minor holds the format-0.8 adoption; the pm sizes it, the liaison maps it. Nothing to build yet.

Standing from memory: the registry tokens leaked 2026-10-08 still need rotating (the person's act).
