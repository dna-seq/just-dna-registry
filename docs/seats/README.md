# Seats: standing roles a session can take in this repo

A **seat** is a fixed role a Claude Code session takes for its whole run. The seats here run on the seats kit
(`agent-seat-blueprints`): its plugin is pinned in the clone, and its base, loaded at every session start, holds
what every seat knows: messages, the desk, unattended runs, who speaks. Every seat also loads `CLAUDE.md`, so the
house rules are shared. What differs is the seat's own priming file.

Take a seat with `/seats:seat <seat>` in a session started in this checkout. A session that has taken none does
the task it was given and takes no seat's work.

| Seat | Priming | Notes | Reached by | What it does |
|---|---|---|---|---|
| **lead** | [LEAD.md](LEAD.md), on the kit's `lead` role | [LEAD_NOTES.md](LEAD_NOTES.md) | the person; a roadmap entry from triage; an adoption map from the liaison; a proposal from the pm | The person's own coding sessions: executes the plan, each item in a worktree, batches when a scope holds several; merges, reviews pull requests, prepares releases and tags them. Moves the kit's pin. |
| **pm** | [PM.md](PM.md), on the kit's `pm` role | [PM_NOTES.md](PM_NOTES.md) | the person; a direction call from a seat | The steer above the code: who the registry serves, licensing, the name, the research list; sizes each minor and major and writes its plan. Writes no code. |
| **triage** | [TRIAGE.md](TRIAGE.md), on the kit's `triage` role | none: its state is `docs/CONSUMER_SUGGESTIONS.md` | the inbox watchers; a relayed consumer report | Answers the consumers in their document, ships patch fixes on `main`, files the rest on the roadmap, restates an upstream fix into the compiler's inbox. |
| **liaison** | [LIAISON.md](LIAISON.md), on the kit's `liaison` role | [LIAISON_NOTES.md](LIAISON_NOTES.md) | a release of an upstream; a symptom from a seat; the compiler's seats | Owns what is known about what the registry stands on: the compiler's three packages first, release by release, talked through with the compiler's seats; then the server's libraries. |

No tooling seat: a fault in the kit's tools is filed on the kit's issues (the skill `report-to-kit`), and the
lead moves the kit's pin. `.blueprints.toml` declares the four seats and who may wake each one. The team file
is on the person's desk, since this repository is public.

A notes file holds a seat's working state, rewritten to the present before a reset and committed by path; a
lesson still true next week moves into the priming or `CLAUDE.md`. Triage has none: the inbox is its state.
