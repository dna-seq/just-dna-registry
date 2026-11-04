# Liaison — notes

The liaison seat's working state, rewritten to the present before a reset (`docs/seats/LIAISON.md`, "Before a
reset").

## Now (2026-11-04, first seating, on october)

- **Watchers** armed and alive: `compiler` (tags), `compiler-next` (`docs/CHANGELOG.md` on `0.8`), `fastapi` and
  `huggingface-hub` (tags), plus `desk`. Clones outside the repo: `/data/sources/just-dna-compiler`,
  `/data/sources/fastapi`, `/data/sources/huggingface_hub`, each a line (`repo=just-dna-registry`) in the
  liaison state file. When the compiler cuts 0.8 and opens 0.9, move `just-dna-compiler-next`'s `branch=`.
- **Ledgers**: `docs/UPSTREAM_COMPILER.md` (read mark `v0.7.3`), `docs/UPSTREAM_FASTAPI.md` (`0.141.1`, backlog
  to 0.162.0 unread), `docs/UPSTREAM_HUGGINGFACE_HUB.md` (`v2.0.0`, the 2.0 major unread although installed;
  floor still `>=0.34.0`).
- **0.8 adoption map**: first pass in `docs/UPSTREAM_COMPILER.md`, sent to the lead and the pm. Half read: M6
  (does anything read an escalated strict finding from `warnings`) is unchecked; the 49 entries were read
  through upstream's `INTEGRATION_0_8.md` and the source diff, not one by one. A probe of our tests against
  the 0.8 packages was refused by auto mode (installing unpublished upstream code); it needs the person's
  allow or a run by hand.
- **Sent to the lead**: C1 to C4. C1, C2 filed on the roadmap (cd4c511); C3 waits on the person; C4 sent with
  the map.
- **The compiler's seats were last asked** (2026-11-04, `agent-chat`): its lead (topic `registry`) to say when
  a cut is near and to add `just-dna-registry/liaison` to its lead's and triage's `wake_from`; its liaison
  (topic `upstream`) a hello naming fastapi, huggingface-hub, polars, duckdb. No answer yet.
- **Avatar** asked of `agents-kit/admin` (topic `avatars`); set it with `watchdog.py avatar liaison --from ID`
  on the reply.

## Backlog, in order

1. The compiler's 0.7.0 cut read for levers (only C1 to C3 so far).
2. huggingface-hub 2.0's notes, then 2.1 to 2.4.
3. fastapi 0.142 to 0.162.
4. An audit of the registry's past filings upstream beyond the five CLAUDE.md names.
