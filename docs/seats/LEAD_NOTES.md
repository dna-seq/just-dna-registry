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
(wheel carries the console). Full suite on the branch: 596 passed. **Published** by the person 2026-11-06 (desk #202 answered);
PyPI files match the local build; the lead tagged `v0.27.1` (0d001b8) and pushed it. Deploys stay theirs. C5 + C13 + C15 move to 0.27.2.

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
**M12 done** (cfba29b, 68aed3d; full suite 639 passed). **0.28.0 is cut** (2026-11-06): the whole list built, the ClinVar-tier facet last (fef4ba1); version + lock c5a7840;
release-head suite 687 passed; main fast-forwarded to it and pushed. Dists in `/data/sources/just-dna-registry.wt/0.28/dist/`.
**Published** by the person 2026-11-06 (desk #215 answered); PyPI files match the local build; `v0.28.0` tagged (c5a7840) and pushed.
**Waits on the person: deploying both boxes**, per docs/UPGRADE.md 0.28 (Ensembl pull first); the boxes serve 0.27 until then.
The `?gene=`/`?category=` scoping fix is on main (c551799), 0.28.1 material.
**0.28.1 published and tagged** (efa6055). Replay on the polygon reproduced the sweep exactly (34 same, 12 refused); the 12 are on desk #218 (publish 8 = moved insertions dbSNP confirms + respellings; hold 4 lost_allele for upstream RM400). Upstream: S132 answered (819553ea), S133 filed (timeouts/batching). Real-HF revert: desk #216 (default skip).
**0.28.2 published and tagged** (2026-11-07, v0.28.2 on b5b0043; desk #219 answered "published"): gzipped run backups, terse sweep, `prune-runs` + auto-prune (REGISTRY_RUN_KEEP=2), `--jobs`. Open: the sweep runs with upstream retry defaults (Ensembl 3) while the server exports http_retry_attempts=5; left as is.

**0.28.3 published and tagged** (v0.28.3 on 43bd40b). **0.28.4 cutting** (2026-11-07, the person: "yes, add REGISTRY_LOG_FILE"): the server writes a rotating log file of its own; the polygon answered 502 with no log to read. Folded in on the person's word ("make this thing track proxy drafts ... --proxy ... exclude flag"): `lane_readers` tags, `warm-caches --proxy` / `--exclude`. **OpenTargets waits on upstream** (the person: "wait for upstream to tidy up opentargets part"): their RM408 gives the lane a pull route (published, uncut); nothing here reads it, and drop-caches asks --force only because it is build-only today. Revisit when RM408 is on PyPI. The polygon's 502 was a full disk. Then: deploy, set REGISTRY_LOG_FILE there, `replay-upgrade --online` (desk #218).

**0.28.4 built, not published** (2026-11-07 22:00; suite 847 passed, dists from bda2bbf; tag v0.28.4 on bda2bbf once it is on PyPI). **0.28.5 under way on main, unattended, desk #232's default** (publish 0.28.4 as built, fix in 0.28.5): 76aac02 makes `GET /caches` carry `readers` and `read_here = bool(readers)`; `[Unreleased]` in the changelog, version not stamped (stamp at the cut, with the full suite). If #232 comes back "hold", fold it into 0.28.4 by restamping that cut instead. **RM404 stays in upstream 0.9** (their pm, 2026-11-07: no new public parameter on their main, additive or not), so `_UNSHARED_EGRESS` keeps online modules serial under `--jobs` until we adopt 0.9.

**0.28.4 published and tagged** (v0.28.4 on bda2bbf, 2026-11-09; desk #232 withdrawn as moot). **0.28.5 stamped** (19ac3b9), full suite running; then build, push, report. Two upstream items wait on an enricher floor, neither on a date: **RM420** (re-pull a present pulled lane when the hub has a newer release) reaches us only if `warm-caches` hands present pullable lanes to `prepare_caches` (today: absent + `lanes_to_repull`), so that change goes in the release whose floor carries RM420 (ledger 0c33e83). **RM418** (one NCBI gate per process) retires the `verify_rsids` half of `_UNSHARED_EGRESS` once the floor carries it (ledger fbadc0e, with its probe).
**0.28.5 published and tagged** (v0.28.5 on 19ac3b9, 2026-11-10; PyPI files match; desk #244 withdrawn as moot).
**0.28.6 under way** (2026-11-10, the person: ".8.3 in pypi"; "dm me in zulip on 28.6"): floors `>=0.8.3`, RM418
(the `verify_rsids` half of `_UNSHARED_EGRESS` gone), RM420 (`warm-caches --apply` hands selected present pulled
lanes to `prepare_caches`), OpenTargets' drop sentence (RM408). Then full suite, stamp, build, and **DM the person
on Zulip** when the dists are in `dist/` and ready for `uv publish`. The OpenTargets wait is closed: RM408 is on PyPI.
**0.28.6 built** (2026-11-10 23:11, release head e73fe8a, pushed; full suite 851 passed + the one RM423 test
fixed in c996abf, its files rerun 119 passed). Also in it, on the person's word ("I ned partial/build artifacts
cleanup in ..6 now"): `drop-caches` lists partial lanes and `--leftovers` removes build staging (961671b).
**Published and tagged** (v0.28.6 on e73fe8a, 2026-11-11; PyPI files match the local build). Found while fixing the RM423 test: a forged closure with the
correct binding publishes (the docs overclaimed; corrected); an upstream ask for a signed closure is the
liaison's call. **0.29.0 built** (2026-11-11 00:59, release head 58d6a05 on main, pushed; full suite on the branch 862 passed + the overlay fix 4b0c083, its tests and the rename's rerun at the head, 81 passed). Tag `v0.29.0` on 58d6a05 once it is on PyPI; then tell triage (S28's follow-up), unlock the worktree, `git branch -d 0.29`. Was: **0.29 under way** on branch `0.29` (worktree `/data/sources/just-dna-registry.wt/0.29`, locked):
the namespace rename, the person's "1a 2a 3a"; plan e68d89a; built and reviewed (an Opus "what did I miss"
pass found 11 gaps, all addressed); uncommitted on the branch at 23:15. Left: commit, the full suite, the
plan's Facts corrected, and the console banner (needs Node). Worktree tests need
`JUST_DNA_PIPELINES_CACHE_DIR=/data/just-dna-cache`.
**Next**: after 0.28, the variant-level catalog with a gene facet, design first (roadmap).
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
