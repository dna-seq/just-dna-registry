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
- **0.8 adoption map**: first pass in `docs/UPSTREAM_COMPILER.md`, sent to the lead and the pm; M6 checked
  since (nothing to change). The 0.8 rows wait on the pm's sizing and the cut. The 49 entries were read
  through upstream's `INTEGRATION_0_8.md` and the source diff, not one by one. A probe of our tests against
  the 0.8 packages was refused by auto mode (installing unpublished upstream code); it needs the person's
  allow or a run by hand. Filed on the kit as winternewt/agent-seat-blueprints#265 (the person: seats file
  kit issues without asking).
- **Sent to the lead**: C1 to C4. C4, C1, C2 filed on the roadmap (fcd2589, cd4c511), in that order; C3 folded into
  the roadmap's older column-release entry (f96eca4).
- **The compiler's seats were last asked** (2026-11-04, `agent-chat`): its lead (topic `registry`) to say when
  a cut is near and to add `just-dna-registry/liaison` to its lead's and triage's `wake_from`; its liaison
  (topic `upstream`) a hello naming fastapi, huggingface-hub, polars, duckdb. Its lead answered: the 0.8 cut is
  5-8 hours out (all three to 0.8.0, `>=0.8.0` floors, the release record, the finished guide), announced in
  `#just-dna-compiler`; the `wake_from` change went to the person, who answered: their triage's `wake_from` gains this
  seat, as a plan b to their file watcher. Their liaison agreed: a defect under both of us is asked in
  `agent-chat > upstream` first and filed once; their ledgers are UPSTREAM_POLARS/DUCKDB/GA4GH_VRS. When the
  `compiler` watcher says `tag v0.8.0`, re-read the map against the finished `INTEGRATION_0_8.md` and the record.
- **Avatar** set (a giraffe lookout, from admin's 637614492).

- **Waits until the kit pin carries 621966f** (the person, 2026-11-04: the dependency bump is this seat's
  unattended routine): then add `[seat.liaison.watch.nightly]` `cmd = "sh kit:bin/py.sh
  kit:classes/base/nightly.py deps"`, and land the grant's new lines (the lock and a mechanical fix as a
  patch on main, suite green; a major shift on a branch for the lead) through change-priming. v0.1.126 does
  not carry it.

- **At the 0.8 cut, check three items the compiler's pm named that the map has no row for** (via our pm,
  2026-11-04): RM342's `verify` reporting `toolchain_differs`, against our client's `verify_manifest` path with
  polars-1 consumers in the field; RM304's per-row VRS version and manifest pin; RM347/RM353's publisher
  (uploads the logs the manifest names, guards exactly the declared files). Tell the pm if the re-map moves a
  row of registry 0.28's scope (ROADMAP "0.28").
- **Push held**: my commits sit on local main behind the pm's 5c3ee04, which the pm holds until kit #264;
  pushing main would carry it. Push once origin has it, or once the pm says go.

## Backlog, in order

1. The compiler's 0.7.0 cut read for levers (only C1 to C3 so far).
2. huggingface-hub 2.0's notes, then 2.1 to 2.4.
3. fastapi 0.142 to 0.162.
4. An audit of the registry's past filings upstream beyond the five CLAUDE.md names.
