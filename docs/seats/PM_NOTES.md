# Pm — notes

The pm seat's working state, rewritten to the present before a reset (`docs/seats/PM.md`, "Before a reset").

## Now (2026-11-27)

First seating done on this machine. SPEC, ROADMAP (from "Next registry version") and UPGRADE read whole.

- **0.28 published** (2026-11-06, desk #215; tagged `v0.28.0`): the whole bundle as sized, format 0.8 adopted.
  The maintainer kept it whole when the lead proposed a lean cut (2026-11-06, "Keep full 0.28"). Heading
  marked ✅. The C8/C17 "you may move them" reminder is moot: they shipped in it. 0.28.1 and 0.28.2 (maintenance
  runs, replay, pruning, parallel re-publish) are the lead's patches, not scope. Deploying is the person's,
  `docs/UPGRADE.md` 0.28; the sweep's operator question is the lead's desk #218.
- **0.29 published** (2026-11-11, `v0.29.0`; heading marked ✅, c17af6e): the namespace rename, sized by the
  person in the lead's session ("1a 2a 3a", reversing S28). 0.29.1 (rebuild once the enricher carrying RM428, the
  GWAS page-size fix, is on PyPI) is the lead's patch, not scope.
- **0.30 published** (2026-11-11, `v0.30.0`, heading marked ✅; both servers run it, measured 2026-11-12). Its
  requirements and the person's licence rulings are in its section. Remote lane reads wait on upstream RM430.
- **0.30.1 published** (2026-11-13, `v0.30.1`, heading marked ✅): upstream 0.8.5 and the re-derivation
  discriminator. The five pre-0.8 modules re-derive in the maintainer's production run after a deploy.
- **0.31.0 published** (2026-11-13, `v0.31.0` on 0f2d3ab, floors upstream 0.8.6), the variant-level catalog; its
  item under *Next registry version* marked ✅ (it has no heading of its own). S29/S30 (lane terms, closed live
  legs) were not in it: moved to 0.32.
- **0.31.1 published** (2026-11-14, `v0.31.1`): the lead's patch (re-derivation publishes and reports drift,
  `--withhold-rederive`/`--accept-drift`), no roadmap heading.
- **0.32.0 published** (2026-11-16, `v0.32.0` on e2e172b): S29, S30, S31, S32 (all four pieces), S33 and its
  corroboration (`curated` counts only an outside reviewer's `verified` highlight, decided 2bb903e), the person's
  `GET /upgrade/status`, C13/C15, enricher 0.8.7. Six items under *Next registry version* marked ✅.
- **0.33.0 and 0.33.1 published** (2026-11-18, `v0.33.0` on da53225, `v0.33.1` on c965700): S34 (lane replies name
  their release and remote commit), S35 (a verdict change clears the owner's pin), and the kept spec after a compile
  refusal (0.33.1). Three items marked ✅. Both servers still on 0.32.1 at 22:35 CET; deploy is the person's.
- **0.34.0 and 0.34.1 published** (2026-11-18/19, `v0.34.0` on 8c53d21, `v0.34.1` on b11f991): the lead's minors
  (deploy over the API; key rotation, folder lock, upstream 0.8.9 floor), no roadmap items to mark. 0.34.2 (supervise
  via uvx) and 0.34.3 (0.8.10 floor) are the lead's. Servers on 0.32.1 at 08:00 CET.
- **0.34.2 published** (2026-11-22 on PyPI, `v0.34.2` on aca25f4): supervise from PyPI via `uvx`, the lead's patch, no
  roadmap item. Milestone 642621117. Servers on 0.32.1 at 07:12 CET 2026-11-22. 0.34.3 (0.8.10 floor) is next.
- **0.34.3 published** (2026-11-26 19:31Z, `v0.34.3` on 41b1b3d): upstream 0.8.10 floor, no roadmap item. 0.34.4 (`compat`
  extra) is not on PyPI (lead's desk #471: publish it or fold into 0.35). **Both servers deployed 2026-11-26** on a new
  host under `supervise`, serving 0.34.4 from the tag; caches warmed (17/17), backups daily, leaked keys rotated.
  Public posts name no host.
- **0.35.0 in build** (lead, `.worktrees/0.35`): upstream 0.9 floor, S36 (`KEY_COMPARES`, reply names `compares`),
  RemoteSnapshots Hub-only. Mark S36 ✅ when 0.35 is on PyPI. Then the one sweep per box (prod ClinVar trio ~37 h).
- **S36 decided** (1469f92, 8dd726a): lane gene keys compared by upstream's `KEY_COMPARES`, read at the 0.9 floor
  (enricher included); the reply names its compare in that release.
- **Upstream RM441** (declared corrections, with RM399 and our S156) now proposed for its 0.10; the RM438 probe
  stays the path until then. Remote lane reads still wait on RM430 (upstream 0.9 zone).
- **Duty: milestones** (kit v0.1.187, `PM.md` of the kit): the `state` post in `#just-dna-registry>state` is kept
  from `docs/seats/PM_STATE.md` with `watchdog.py keep pm state '#just-dna-registry>state' docs/seats/PM_STATE.md`;
  rewrite it when the standing, a headline result or the next actions change. One post per landed result in
  `#just-dna-registry>milestones`. The repo is public: no machine names or paths in either. Links go to
  `github.com/dna-seq/just-dna-registry` (tags; there are no GitHub releases).
- **Upstream parked RM378** (coded strict errors): the strict-phrase match in *Next registry version* may be
  permanent (da9d8b8).
- **Strategy** (`docs/STRATEGY.md`): who it serves first (installers) and what it will not become are settled;
  nothing open.
- **Dream triaged** (2026-10-18 dream, `docs/DREAMS.md` §7, 89092ff): the row catalog plus a gene-level facet to
  the lead (637623436, after 0.28, so now due for 0.29's sizing); nine ideas on `docs/TO_RESEARCH.md`.
- **Push works**; commits go by path, `git commit --only -- <paths>` (base, kit #286), after a race on
  2026-11-05 put a pm roadmap paragraph inside the liaison's 7e88e7d.
- **Kit pin and auto-mode rules are the lead's** since 183d3b1 (2026-11-22, `duties = "pin-mover automode-rules"`, the
  kit's seat-builder): the pm no longer moves the pin or runs `automode.py` on a kit release.

## Tools

Nothing the repo ran before the kit belongs to this seat: the triage scripts and wakers are triage's. Kept
none, retired none, moved none.
