# Triage seat — notes

State the seat's last holder left. The inbox itself (`docs/CONSUMER_SUGGESTIONS.md`) is the state of the
reports; this file holds the seat's own decisions and the items it owns.

## First seating, 2026-11-04

### The repository's own triage machinery, against the kit's

| piece | decision | why |
|---|---|---|
| `.claude/arm-on-prompt.py` (UserPromptSubmit hook) | retire | wired nowhere: no `.claude/settings.json`, nothing in the user's global settings. The watchdog wakes the seat now |
| `.claude/wake-on-suggestions.sh` + `.claude/watch-suggestions.sh` | retire | `[seat.triage.watch.inbox]` and `[seat.triage.watch.inbox-commits]` cover the same event; neither old script was running at seating (checked by process list). Removing them is the lead's first work, step 1, once this seat reports the kit watcher fired |
| `.claude/triage-state.py`, `.claude/triage-archive.py` | retire, in favour of the kit's `classes/triage/` copies | both ledgers named the same next id (S28) at seating. The priming keeps the clone's copies until the lead retires them; until then this seat runs the kit's |
| `docs/CONSUMER_TRIAGE_LOOP.md` | keep | it carries what the kit's runbook cannot: this repository's release table and its four traps. Its gist-sync step stays until the lead retires it |
| `CLAUDE.md`, section *Consumer feedback is a conversation* | keep, to be updated | it lists the five `.claude/` scripts; when the lead retires them, that section moves with them (lead's or the person's file, not this seat's) |

### Items this seat owns

- The inbox: empty at seating, `--pending` reports nothing; next id S28.
- No tracked items of its own.

### Handout state

1. Kit watcher proof: done. `watch.inbox` fired on a one-line test edit of the inbox (reverted); the lead was
   told in `#just-dna-registry > seating` to retire the old waker. `watch.inbox-commits` reported armed at
   origin's main 068c7b0. `watchdog.py watchers` at seating: `triage/watch.inbox`, `watch.inbox-commits`,
   `watch.desk`, `watch.brief`, all `started`.
2. Ids agree: kit and clone `--next` both S28.
3. Route to the compiler: hello sent to `just-dna-compiler/triage` in `agent-chat > triage-routes`.
4. First pass: nothing pending.
5. Avatar asked of `agents-kit/admin` in `agent-chat > avatars`; not yet set.
