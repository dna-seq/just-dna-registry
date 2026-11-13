# Pm — notes

The pm seat's working state, rewritten to the present before a reset (`docs/seats/PM.md`, "Before a reset").

## Now (2026-11-13)

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
- **Auto-mode rules**: current (checked 2026-11-12, `automode.py --check`); the pm runs `--apply` itself when stale.

## Tools

Nothing the repo ran before the kit belongs to this seat: the triage scripts and wakers are triage's. Kept
none, retired none, moved none.
