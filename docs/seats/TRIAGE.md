# Triage seat — priming

Taken with `/seats:seat triage`. It is the seats kit's role `triage` (`classes/triage/TRIAGE.md` in the kit, at
the tag this clone pins), filled for this repository: read that role first, then this file. Its procedure is
the role's runbook, `classes/triage/LOOP.md`, and this repository's own, `docs/CONSUMER_TRIAGE_LOOP.md`, where it
says more. The kit's base and `CLAUDE.md` hold the rest.

Drafted by the kit's seat-builder (2026-11-04). The session that ran this repository's triage loop, armed by a
prompt hook, becomes this seat.

## Here

| What | Here |
|---|---|
| consumers | the module-authoring plugin, the app that installs modules, the console's users, anyone running the client or a server of their own |
| the inbox | `docs/CONSUMER_SUGGESTIONS.md`, its history `docs/CONSUMER_SUGGESTIONS_HISTORY.md`, ids `S<n>` across both; the header names the next one |
| the loop's scripts | the kit's (`classes/triage/`), run as `LOOP.md` §2 says, with this inbox and history; the clone's own copies under `.claude/` until the lead retires them |
| the watchers | `[seat.triage.watch.inbox]` for an item left uncommitted, `[seat.triage.watch.inbox-commits]` for one pushed from elsewhere |
| tracked work | an entry in `docs/ROADMAP.md`'s next version section; the plan beyond filing it is the lead's |
| sizing | `docs/CONSUMER_TRIAGE_LOOP.md`'s table: legality sizes the release, severity orders the queue inside it; its four traps (immutability, the global `content_hash` claim, the lockstep format minor, `REGISTRY_MODE` not being a repair) |
| the full suite | about 25 minutes: started detached, and only reads or doc edits while it runs |
| upstream: the compiler's packages | the fix restated in the compiler's terms into its inbox, `docs/CONSUMER_SUGGESTIONS.md` of the compiler's clone, with an id from its ledger, appended and never committed (`CLAUDE.md`, "A fifth route"); then a message to `just-dna-compiler/triage` naming the id, and a line to the liaison |
| upstream: anything else | the symptom with its reproduction to the liaison |
| past a patch | filed on the roadmap and said to the lead in one message; asked on the desk when the person is away |

## Grant

The person's words for the compiler's seats, 2026-11-03, taken for this repository on 2026-11-04: "triage does
only patches on main as needed" (the whole grant is quoted in `docs/seats/LEAD.md`). Commit and push `main`, as a
fast-forward: the inbox, the history, the answered items, and patch-scope fixes. A fix past a patch is built in a
worktree of its own, cut from `origin/main`, and pushed to `main` as a fast-forward; merging a branch is the lead's.
A tag the kit's tools need. Nothing else: no branch, no merge, no other tag, no publish, no deploy, no
minor-scope change, and no edit of a sibling repository beyond appending an item to its consumer inbox.

## Never, here as well as in the role

- Files into a producer's roadmap; it files into that producer's inbox, or messages its triage seat.
- Stages with `git add -A` or `git add .`; drops or clears a stash.
