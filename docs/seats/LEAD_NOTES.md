# Lead — notes

The lead seat's working state, rewritten to the present before a reset (`docs/seats/LEAD.md`, "Before a reset").

## Now

Seated 2026-11-04 (first seating). The seat-builder's first work, as it stands:

1. **Retire the old triage waker**: done, 7ff1398, after triage reported its watcher fired.
2. **Id scripts stay** (`.claude/triage-state.py`, `.claude/triage-archive.py`); moving to the kit's
   `classes/triage/` is a later roadmap call, not filed yet.
3. **Seats pointer in CLAUDE.md**: done, ad1b570.
4. **Trust register** (`docs/TRUST.md`): **waits until 2027-02-04**, the person, 2026-11-04: "no trust registry
   here yet, ask me in 3 months". On that date ask once again whether to start one (the server holds
   publishers' API keys and an HF write token).
5. **Working tree**: `uv.lock` is no longer dirty (clean on 2026-11-04 at punch-in). `docs/DREAMS.md` was committed by
   the pm on the person's word (daeab95); closed.
6. **Kit pin**: this seat moves it; nothing waiting.

Avatar set (the admin's bowerbird).

## Plan, in order

The 0.27.x patches, all unattended, each in its own worktree, on a maintenance branch from `v0.27.0`
(main's [Unreleased] already holds minor material, `merge_accounts`), in this order:

1. C7: **done**, 1beb158 on `release-0.27.x` (from `v0.27.0`), merged into main 8a04cb1. How patches land:
   on `release-0.27.x` first, then that branch merged into main; changelog `## [0.27.1] — unreleased` under
   main's [Unreleased]. Tests in a worktree run with `--basetemp` under `/data/just-dna-cache/`, not `/tmp`
   (a 32 GB tmpfs that ran out of inodes on 2026-11-04, 780k of them in kept pytest runs).
   H2 (httpx2 and httpcore2 loggers quiet): done, 015d3d0 on `release-0.27.x`, merged 087ce89.
2. C4: **done**, a96e8ac on `release-0.27.x`, merged into main.
2b. C16: **done** on `release-0.27.x`, merged into main.
3. C9: **done** on `release-0.27.x`, merged into main.
4. C8's patch half: **done** on `release-0.27.x`, merged into main.
5. The four small corrections: **all done** (subtitle 240, C6, C11, C12). (`gather_pmids` over every citing table).
6. C1 and C2 **done** (C2 narrowed: the bundle stays filled).
7. C5 + C13 + C15, reading what upstream made public.

**0.27.1 is prepared** (2026-11-05): version + lock (release-0.27.x, merged into main 33bee26), changelog
dated, docs/UPGRADE.md 0.27.1 note, dists built in `/data/sources/just-dna-registry.wt/relprep/dist/`
(wheel carries the console). Full suite on the branch: 596 passed. **Waits on the person: publishing to
PyPI**, `blocked: desk #202` (`uv publish` from that worktree), then the lead tags `v0.27.1` on release-0.27.x's head and
deploys stay theirs. C5 + C13 + C15 move to 0.27.2.

The 0.28 minor (pm's scope, waits on format 0.8): the rename, C8's fields half, C10, the column-release
item (C3 folded in), the rest of the pm's list. C14 canceled (both proxies gzip, checked 2026-11-04).
After 0.28: the variant-level catalog with a gene facet; design first.

Kit pin at v0.1.129 (2026-11-05); this session runs 0.1.128 until `/reload-plugins`.

**Pushes are the lead's** (LEAD.md grant, "all pushes"): push main and `release-0.27.x` after each landed block,
peers' commits included. Holding them for desk #193 was wrong (the person, 2026-11-05: "why noone pushes?");
pushed c83164d. There is no trunk watcher; the lead pushes at the end of each block instead.

**Waiting on the person**: `longevity-loci/liaison` (and `longevity-loci/triage`, per the kit's rule) into
`[seat.triage] wake_from` in `.blueprints.toml`; the auto-mode classifier refused the edit (Self-Modification). `blocked: desk #201` (filed 2026-11-05, default: no change).

**0.28 pre-build** (the person via pm, 2026-11-05: "0.8 is delayed ... pre-build on top of that"): building
on branch `0.28` (worktree `/data/sources/just-dna-registry.wt/0.28`, pushed), three tiers from upstream's 0.8
at rev 5b1b73b8 by git source in pyproject (removed and floored `>=0.8.0` before merge; move the rev when the
compiler's lead says §2 changed). Not merged, not shipped before the floors are on PyPI.
Baseline on 0.8: 5 failed / 587 passed. Done: M2 (be1d6db), `clinvar_gkm_cache` + the C7 guard over every lane
(634038c). Next: M8 (Ensembl repo default), M9 (validate switches), M4+M10 (+ C8 minor, C10, C17 per the
roadmap), M11 check. M3/M12 wait for the cut (rederive online, after RM381, per upstream).
**Tests in a worktree need `JUST_DNA_PIPELINES_CACHE_DIR=/data/just-dna-cache`**: the `.env` lives only in the
main checkout, and without it `test_no_filesystem_path_reaches_the_wire` sees no provisioned lane.

Standing from memory: the registry tokens leaked 2026-10-08 still need rotating (the person's act).
