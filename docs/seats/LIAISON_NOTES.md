# Liaison — notes

The liaison seat's working state, rewritten to the present before a reset (`docs/seats/LIAISON.md`, "Before a
reset").

## Now (2026-11-04, first seating, on october)

- **Watchers** armed and alive: `compiler` (tags), `compiler-next` (`docs/CHANGELOG.md` on `0.8`), `fastapi` and
  `huggingface-hub` (tags), plus `desk`. Clones outside the repo: `/data/sources/just-dna-compiler`,
  `/data/sources/fastapi`, `/data/sources/huggingface_hub`, each a line (`repo=just-dna-registry`) in the
  liaison state file. When the compiler cuts 0.8 and opens 0.9, move `just-dna-compiler-next`'s `branch=`.
- **Ledgers**: `docs/UPSTREAM_COMPILER.md` (read mark `v0.7.3`), `docs/UPSTREAM_FASTAPI.md` (installed `0.141.1`,
  read through 0.162.0 on 2026-11-05: F1, for the first bump), `docs/UPSTREAM_HUGGINGFACE_HUB.md` (installed `v2.0.0`,
  read through v2.4.0 on 2026-11-05: H2 to H4).
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

- **Dependency bump** set up 2026-11-04 on kit v0.1.127: `[seat.liaison.watch.nightly]` (nightly `deps`, weekly on
  this seat's day, while the person is away) and the grant in `LIAISON.md`. Run it as the kit's role says; the
  full suite takes ~25 min, so run it detached. Not yet run.
- **At the 0.8 cut, check three items the compiler's pm named that the map has no row for** (via our pm,
  2026-11-04): RM342's `verify` reporting `toolchain_differs`, against our client's `verify_manifest` path with
  polars-1 consumers in the field; RM304's per-row VRS version and manifest pin; RM347/RM353's publisher
  (uploads the logs the manifest names, guards exactly the declared files). Tell the pm if the re-map moves a
  row of registry 0.28's scope (ROADMAP "0.28").

- **Desk #193** withdrawn 2026-11-05, decided elsewhere: the lead pushes the trunk under its grant ("all
  pushes"); hand it a commit to push.
- **0.8 map** extended to `503730c` (M8 to M11, from the guide's §§ 1.20-1.29); not yet sent to the lead
  and pm, since the cut is hours away and the whole map is re-read then.
- **RM384 landed** on `0.8` as `locations.SNAPSHOT_REPO_IDS`; the lead took it for M8 (2026-11-05).
- **0.8 map read to `a4a401e7`** (2026-11-05): M13, M14 and M12's rederive effects sent to the lead. Before the cut: two
  regenerated examples and audit round 3; re-read the delta from `a4a401e7` at the tag.
- **Read a 0.8 finding against `origin/0.28`, not `main`**: the lead pre-builds there, and M13 was already
  fixed on it (2026-11-05).
- reflect after 2026-11-11: classes/base/BASE.md as of v0.1.127 (kit reports filed without asking, timed by cost).

## Backlog, in order

1. An audit of the registry's past filings upstream beyond the five CLAUDE.md names.
