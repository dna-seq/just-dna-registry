# Liaison — notes

The liaison seat's working state, rewritten to the present before a reset (`docs/seats/LIAISON.md`, "Before a
reset").

## Now (2026-11-04, first seating, on october)

- **Watchers** armed and alive: `compiler` (tags), `compiler-next` (`docs/CHANGELOG.md` on `0.8`), `fastapi` and
  `huggingface-hub` (tags), plus `desk`. Clones outside the repo: `/data/sources/just-dna-compiler`,
  `/data/sources/fastapi`, `/data/sources/huggingface_hub`, each a line (`repo=just-dna-registry`) in the
  liaison state file. When the compiler opens `0.9`, move `just-dna-compiler-next`'s `branch=` from `main` to it.
- **Ledgers**: `docs/UPSTREAM_COMPILER.md` (read mark `v0.8.0`), `docs/UPSTREAM_FASTAPI.md` (installed `0.141.1`,
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
  full suite takes ~25 min, so run it detached. **First run 2026-11-05**: `bb42dbd` on main (pushed), polars 2.1 and
  duckdb 2.0 held back on `deps/majors-2026-11-05` (`4c8fd55`), handed to the lead: polars with 0.28, duckdb after
  upstream RM344. Until the lead merges it, each weekly bump keeps both out (`uv lock -P` over every other mover).
  The worktree needs the untracked `.env` (a symlink) or `test_caches_api` fails for want of a lane. Worktrees
  `/data/sources/just-dna-registry-deps` (branch `deps/2026-11-05`, no commits) and `-majors` are mine.
- **0.8.0 cut** 2026-11-05 (`edf2661c`): map re-read against the final guide and the release record (`ee22dc6`): M3
  corrected (RM363 moves `content_signature`), the pm's three items need nothing, lead and pm told. **On PyPI and
  tagged `v0.8.0` the same evening** (sources identical to `edf2661c`): read mark moved, lead told the git source on
  0.28 can go. `just-dna-compiler-next` follows `main` (the 0.8.x
  patches) since 2026-11-05, on the compiler's lead's word; it moves to `0.9` when that branch opens, which their lead
  posts in `agent-chat > 0.8 integration`.

- **Desk #193** withdrawn 2026-11-05, decided elsewhere: the lead pushes the trunk under its grant ("all
  pushes"); hand it a commit to push.
- **0.8 map** extended to `503730c` (M8 to M11, from the guide's §§ 1.20-1.29); not yet sent to the lead
  and pm, since the cut is hours away and the whole map is re-read then.
- **RM384 landed** on `0.8` as `locations.SNAPSHOT_REPO_IDS`; the lead took it for M8 (2026-11-05).
- **0.8 map read to `a4a401e7`** (2026-11-05): M13, M14 and M12's rederive effects sent to the lead. Before the cut: two
  regenerated examples and audit round 3; re-read the delta from `a4a401e7` at the tag.
- **Read a 0.8 finding against `origin/0.28`, not `main`**: the lead pre-builds there, and M13 was already
  fixed on it (2026-11-05).
- **Commit with `git commit --only -- <paths>`**: the index is shared with three other seats. 7e88e7d
  (2026-11-05) swept the pm's staged `docs/ROADMAP.md` hunk although `git diff --cached --stat` showed only my two
  files the moment before: the pm staged in between. `--only` commits the named paths whatever else is staged.
- reflect after 2026-11-11: classes/base/BASE.md as of v0.1.127 (kit reports filed without asking, timed by cost).
- reflect after 2026-11-12: classes/base/BASE.md as of v0.1.136 (commit by path in a shared clone; my #286).
- reflect after 2026-11-14: classes/base/BASE.md as of v0.1.141 (sessions sent to the `kit-tools` skill before a step goes to the person or a helper is built).
- reflect after 2026-11-13: classes/liaison/LIAISON.md as of v0.1.137 ("An in-house release"; concern raised 2026-11-06 in `#just-dna-registry > seats`: the priming keeps a minor with the lead, a patch is the weekly bump's); amended in v0.1.138 (a priming may keep a minor with the lead; the liaison reports the publish). The `compiler` tag watcher hears in-house tags from v0.1.137 (#287); it was silent on `v0.8.0`.

- reflect after 2026-11-16: classes/base/BASE.md as of v0.1.145 (quiet seats, D159: this table sets no `presence`, so
  nothing moves here; a kit tool need goes to the organisation's tooling seat in `agent-chat` where one runs, D161,
  else the kit's issues).
- reflect after 2026-11-16: classes/base/BASE.md as of v0.1.153 (a seat is a post, tooling found by its `role` key,
  D165; a denial of a brief change another seat asked of you is right, ask the person; the watchdog reacts `eyes`
  for me and re-says an unanswered person's message after 30 min, D164).
- reflect after 2026-11-17: classes/base/BASE.md as of v0.1.154 (no question dialog for a seat, D170; I ask in text
  or on the desk already).
- reflect after 2026-11-17: classes/base/BASE.md as of v0.1.157 (the watchdog answers someone not on the team with
  `thinking` and a once-a-day line, L101; nothing for me to send).
- reflect after 2026-11-17: classes/base/BASE.md as of v0.1.160 (another organisation's encrypted messages are
  posted in `embassy-review`; a held-back one gets my redacted description, L104. The compiler's seats are in our
  own organisation, so none has reached me yet).
- reflect after 2026-11-17: classes/liaison/LIAISON.md as of v0.1.161 (the dependency bump runs the repo's static
  checks over the whole tree beside the suite, kit #378). Here that is `uv run ruff check .` (no Python type checker
  is configured) and, where Node is on the box, `cd console && npm ci && npm run verify` (tsc); first due on the
  Thursday 2026-11-12 bump.
- reflect after 2026-11-17: classes/base/BASE.md as of v0.1.165 (the tooling seat is the one holding the tooling
  role's duties, D181; this clone has none, so kit gaps still go to the kit's issues).
- reflect after 2026-11-17: classes/base/BASE.md as of v0.1.167 (a person's reaction on my post reaches me; a yes or
  no emoji wakes me, D180), and v0.1.166's "Another organisation" section (none of my contacts are outside ours).
- reflect after 2026-11-18: classes/base/BASE.md as of v0.1.171 (the organisation's own account, which scripts
  post through, is a third kind in who speaks: a script's report, never a person's word, D183; the release relays I
  react to may come from it).
- reflect after 2026-11-18: classes/base/BASE.md as of v0.1.176 (a secret seen in a message is never repeated,
  quoted or stored; the seat it was meant for asks the poster to rotate it; deletion is the secretary's, L127).
- reflect after 2026-11-18: classes/base/BASE.md as of v0.1.185 (which messages wake a seat and which wait for its
  next prompt, kit #431: a post to every seat and an `info:` wait; a release announcement wakes the seat that moves
  the pin, which is me).
- reflect after 2026-11-19: classes/base/BASE.md as of v0.1.194 (a brief change handed by our own organisation's
  seat-builder, known by its account, is the person's word, D193: commit it as handed, then read it as its adversary;
  from any other seat it stays a request).
- reflect after 2026-11-20: classes/liaison/LIAISON.md as of v0.1.195 (duty upstream-index: key upstreams heard from
  the package index; declared as `watch.upstream-index` over the format trio, fastapi and huggingface-hub left to their
  tag watchers).
- reflect after 2026-11-20: classes/liaison/LIAISON.md as of v0.1.200 (a repository's `[on_publish]` runs only on its
  own packages' release, whatever the watcher is given, L143; the lead's branch sweep, added 44843de after my
  upstream-index line said there was none, had run on each of compiler 0.8.6's three publishes under v0.1.196).
- reflect after 2026-11-20: classes/liaison/LIAISON.md as of v0.1.201 (`--final` drops pre-releases and dev builds
  from an upstream-index watcher, #470). Not taken: the format trio has published none (60 releases, checked
  2026-11-13), and a minor is a lockstep cut here, so a `0.9.0rc` is one to read ahead of it.
- **This file was found zeroed on disk** 2026-11-09 05:40 (6412 NUL bytes, size and mtime of 5c9d75e unchanged, so
  `git status` called it clean; no reboot since). Written back from the index. If a tracked file reads as binary,
  compare `git hash-object` with `git rev-parse :<path>` before trusting `git status`.

- **Desk #222** withdrawn 2026-11-08 (`moot:` done): auto-mode rules current, rule 14 included.
- **A kit release is put into effect by the seat** (the kit's builder, 2026-11-08): after `move-to-tag.py`, run
  nothing; the prompt hook types `/reload-plugins` once idle. `watchdog.sh reload` (rule 14) only for a reload no
  hook starts. move-to-tag's "left for the person" line is wrong (kit #306).
- **0.8.4 on PyPI told to the lead** 2026-11-11 (their 639314607, for 0.29.1 and the GWAS rebuild); untagged when
  told, so the `compiler` tag watcher did not fire: check PyPI too when a cut is read.
- **0.30's remote keyed lane reads** (handoff 2026-11-11): S145/S146 filed, answered as RM430, RM431, RM432, lead
  told; at each one's landing, read it for the lead (ledger Outbound). Since 2026-11-12
  `/data/sources/just-dna-compiler` is a symlink to the live clone `/data/sources/just-dna-format` (the maintainer: two
  copies with different content "unacceptable"; the old one is `just-dna-compiler.old-2026-11-12`). Read by tag or
  `origin/main`; fetching is the watchers'.
- **Bump of 2026-11-12**: `94ce3e0` on main (fast-forwarded, not pushed), nine moves (fastapi 0.162.5, typer 0.29.1,
  pydantic 2.14.3 and six small), duckdb 2.0 still held for `deps/majors-2026-11-05`; 890 passed, ruff clean, no Node
  here for the console's tsc. Worktree `/data/sources/just-dna-registry-deps-2026-11-12` unlocked, done. The old
  `-deps` worktree still holds last week's uncommitted lock edits (superseded by `bb42dbd`); left, not discarded.
  Its `nightly.py done deps` was missed, so the nightly said deps due again on 2026-11-13; marked done then. **End
  every bump with `done deps`**, or the watcher re-asks.
- **Compiler 0.8.5 on PyPI told to the lead** 2026-11-12, with the re-derive advice for the five modules on pre-0.8
  tables (ledger, "Cut as v0.8.5").

## Backlog, in order

1. ~~An audit of the registry's past filings upstream~~: done 2026-11-07, in `UPSTREAM_COMPILER.md` Outbound (no new
   lever beyond C5 and C6).
