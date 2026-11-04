# Lead — notes

The lead seat's working state, rewritten to the present before a reset (`docs/seats/LEAD.md`, "Before a reset").

## Now

Seated 2026-11-04 (first seating). The seat-builder's first work, as it stands:

1. **Retire the old triage waker** — `after triage's first fire`: waiting for triage's message that its kit
   watcher fired. Then one commit: `git rm` `.claude/arm-on-prompt.py`, `.claude/wake-on-suggestions.sh`,
   `.claude/watch-suggestions.sh`; rewrite the arming paragraph in `CLAUDE.md` ("Consumer feedback is a
   conversation") and the arming/waker sections of `docs/CONSUMER_TRIAGE_LOOP.md`; a changelog line. No prompt
   hook is wired (checked 2026-11-04: `.claude/settings.local.json` and `~/.claude/settings*.json` name none).
2. **Id scripts stay** (`.claude/triage-state.py`, `.claude/triage-archive.py`); moving to the kit's
   `classes/triage/` is a later roadmap call, not filed yet.
3. **Seats pointer in CLAUDE.md**: done, ad1b570.
4. **Trust register** (`docs/TRUST.md`): asked the person once, 2026-11-04; open.
5. **Working tree**: `uv.lock` is no longer dirty (clean on 2026-11-04 at punch-in). `docs/DREAMS.md` (the
   2026-10-18 four-model dream, 474 lines) is untracked; asked the person whether to commit it as the pm's idea
   book; open.
6. **Kit pin**: this seat moves it; nothing waiting.

Avatar asked of `agents-kit/admin` in `#agent-chat>avatars`; set it with `watchdog.py avatar lead --from ID` once
the reply comes.

Standing from memory: the registry tokens leaked 2026-10-08 still need rotating (the person's act).
