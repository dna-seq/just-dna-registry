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
2. C4, derive `_ROW_MODELS` from upstream (breaks us quietly).
2b. C16, the withheld-indel hint and the pyproject 0.7.3 comment (twenty minutes).
3. C9, `enrich_verify_datasets`, default off (unmetered egress).
4. C8's patch half: no early return in the identifier check, `write=False`, `check_pgs=False`, skips into `warnings`.
5. The four small corrections: subtitle 240 (on **main**, not the patch branch: 240 is [Unreleased] material, 0.27.0 still says 120), `pacing.py` text (C6, no reconcile), C11 (module-level by code),
   C12 (`gather_pmids` over every citing table).
6. C1, then C2.
7. C5 + C13 + C15, reading what upstream made public.

The 0.28 minor (pm's scope, waits on format 0.8): the rename, C8's fields half, C10, the column-release
item (C3 folded in), the rest of the pm's list. C14 canceled (both proxies gzip, checked 2026-11-04).
After 0.28: the variant-level catalog with a gene facet; design first.

Kit pin at v0.1.128 (moved 2026-11-05); this session runs 0.1.127 until `/reload-plugins`.

Standing from memory: the registry tokens leaked 2026-10-08 still need rotating (the person's act).
