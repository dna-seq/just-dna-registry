# Triage seat — notes

State the seat's last holder left. The inbox itself (`docs/CONSUMER_SUGGESTIONS.md`) is the state of the
reports; this file holds the seat's own decisions and the items it owns.

## First seating, 2026-11-04

### The repository's own triage machinery, against the kit's

| piece | decision | why |
|---|---|---|
| `.claude/arm-on-prompt.py` (UserPromptSubmit hook) | retire | wired nowhere: no `.claude/settings.json`, nothing in the user's global settings. The watchdog wakes the seat now |
| `.claude/wake-on-suggestions.sh` + `.claude/watch-suggestions.sh` | retired (lead, 7ff1398, with `arm-on-prompt.py`) | `[seat.triage.watch.inbox]` and `[seat.triage.watch.inbox-commits]` cover the same event; neither old script was running at seating (checked by process list). Removing them is the lead's first work, step 1, once this seat reports the kit watcher fired |
| `.claude/triage-state.py`, `.claude/triage-archive.py` | keep for now | the builder's word (2026-11-04): they stay per the lead's first work step 2, and moving to the kit's copies is the lead's later call. Both ledgers named the same next id (S28) at seating; this seat runs the kit's, which read the same documents |
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
3. Route to the compiler: agreed with `just-dna-compiler/triage` (its notes, d9a10f3a). The protocol: take the
   id from *their* ledger's `--next` at the moment of writing (S129 on 2026-11-04), append the section to their
   `docs/CONSUMER_SUGGESTIONS.md` and leave it uncommitted (they commit it as it arrived, then reply), message
   them naming the id. They message this seat when they move an item back. Their `main` is patch scope only: a fix
   needing a new field or warning code lands on their 0.8 branch, and they say which release carries it.
   Their triage's `wake_from` now names `just-dna-registry/triage` (their lead, 2026-11-04, on the person's word),
   so a message from this seat wakes it.
4. First pass: nothing pending.
5. Avatar: set (a red squirrel clerk, from `agents-kit/admin`).

## Items this seat owns (2026-11-10)

- **S28 follow-up reply** — done 2026-11-11: the second Status paragraph is in the history file, and the consumer was told. Was: waits until 0.29.0 is cut. Answered 185a8c7 as "declined by design"; the person
  reversed that in the lead's session (lead's message 639283920): 0.29.0, built by the lead on branch `0.29`,
  renames a namespace and keeps the old name as an alias that reads and publishes follow. The lead reverses
  185a8c7's docs on that branch. Once 0.29.0 is cut: append a second `**Status —**` paragraph to S28 in
  `docs/CONSUMER_SUGGESTIONS_HISTORY.md` (accepted, shipped 0.29.0, the call to make), update its contents line,
  and say so to the consumer. Until then the delete-and-republish advice stands on the polygon.
- **Desk #313, the exposed registry keys** — superseded by the lead's key rotation, 2026-11-19. The person answered
  in the lead's chat (2026-11-18): "Don't bug me with rotating keys. Implement rotation." The lead relayed it to the
  desk and built `registry-client rotate-key` (0.34.1, published); the lead rotates the three keys once 0.34.1 runs on
  both servers. Nothing left for this seat.
- **S34 follow-up reply** — done 2026-11-19: 0.33.0 on PyPI 2026-11-18; second `**Status —**` and contents line in the
  history file, just-dna-compiler's liaison told. Neither server ran it then (both 0.32.1).
- **S35 follow-up reply** — done 2026-11-19: as S34's, just-module-creator's liaison told.
- **S36 follow-up reply: once the registry release that floors upstream 0.9 is on PyPI.** The pm decided S36
  (1469f92): the lane lookup reads upstream's `KEY_COMPARES` (just-dna-enricher's, on their 0.9 branch) at that
  floor, and the reply names the compare per key column; no per-request field. The pm told the reporter directly
  (2026-11-18). Then: a second `**Status —**` on S36 in the history file from that release's changelog, its
  contents line, and just-dna-compiler's liaison told.
- **S29–S33 follow-up replies** — done 2026-11-16: 0.32.0 reached PyPI; a second `**Status —**` on each and on
  the S33 corroboration, contents lines updated, the consumer told. Neither box served 0.32.0 then (polygon 0.30.0,
  production 0.31.0); S30's re-run on the polygon waits for its upgrade, the consumer's to do.
