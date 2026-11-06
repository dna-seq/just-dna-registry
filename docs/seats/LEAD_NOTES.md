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

Kit pin at v0.1.137 (2026-11-06). The kit's liaison role now takes an in-house release's mechanical half; here the
priming keeps a format **minor** the lead's (a coordinated cut), so that covers patches only (the liaison's concern,
2026-11-06; which way the priming says it is the person's). On main (shared clone) commit by path: `git commit --only -- <paths>` (kit #286).

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
(634038c), M8 (59ddcd9, 2d06f57), M9 (c1706e3), M4 (158e239), M10 (84d4a6c); main merged in (71bf1a7).
Rev moved to a4a401e7 (46603de); RM384 tie-back (7a275a4); M13 test (bd7fe67); C10/M14 (9f4e114); C17
(276df93); C8 minor half (af18b2e). **PGS leg on** (ffe263d, the liaison's design; no UPSTREAMS row, since the ledger charges /hint only).
At upstream's release candidate c90e6d98 (049e036), main merged in (c949f91), polars 2.1.0 (0c23598): full
suite 621 passed. duckdb 2 waits for upstream's RM344 (roadmap 3d4d850).
**Upstream cut 0.8.0** (edf2661c, 2026-11-05; PyPI and tags are their maintainer's): 0.28 is on it with floors
`>=0.8.0` (4579fea), full suite 621 passed. **0.8.0 on PyPI** (all three, 2026-11-05): git source out, relocked from
PyPI (c809c09), full suite on the published wheels 621 passed, 10 skipped. 0.28 depends on nothing unpublished now.
**M12 done** (cfba29b, 68aed3d; full suite 639 passed). **Next: the handle rename**, planned and reviewed (roadmap 7e27f92).
**Full 0.28, no lean cut** (the person, 2026-11-06: "Keep full 0.28"; roadmap): the release waits for the whole list.
**M12 is unblocked** (RM381 shipped in the cut): the upgrade sweep re-enriches with `rederive`, online for
indels, so it needs an online setting and an egress budget for the run; then UPGRADE.md's 0.28 procedure
(Ensembl pull, deploy, `upgrade --dry-run`, `--apply`; a chr-prefixed module's content_signature moves, RM363)
and CLAUDE.md's floor reasons.
**Next on 0.28: the handle rename** (roadmap, decided 2026-11-04). It amends `owner` on every stored manifest the
account published and reserves the old handle as an alias: one-way on production data, so it starts with a
written plan and a "what did I miss" review pass (memory: dogfood plans before immutable decisions), then the
build: route + client method + parity row, admin route beside merge-accounts, CLI, tests. Then publish
recovery, the `.env` item, M5, M7, C3, /stats. M3/M12 at the cut. Next: M11 check,
then the rest of the 0.28 list. M3/M12 wait for the cut (rederive online, after RM381, per upstream).
**Tests in a worktree need `JUST_DNA_PIPELINES_CACHE_DIR=/data/just-dna-cache`**: the `.env` lives only in the
main checkout, and without it `test_no_filesystem_path_reaches_the_wire` sees no provisioned lane.

**Plan watcher** (the kit builder's note, 2026-11-05): `[seat.lead.watch.plan]` needs `## <ID> — <title>` items
with a `**State:**` line; our ROADMAP is bullets under version headings, so `plan-watch.py --once` reads no item.
`waits until 2026-11-12`: decide then whether to convert the roadmap (a pm-scope restructure) or keep the
notes' plan list. Adding the watcher also edits `.blueprints.toml`, which auto mode refused once (desk #201).

Standing from memory: the registry tokens leaked 2026-10-08 still need rotating (the person's act).
