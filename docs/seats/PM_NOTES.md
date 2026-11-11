# Pm — notes

The pm seat's working state, rewritten to the present before a reset (`docs/seats/PM.md`, "Before a reset").

## Now (2026-11-11)

First seating done on this machine. SPEC, ROADMAP (from "Next registry version") and UPGRADE read whole.

- **0.28 published** (2026-11-06, desk #215; tagged `v0.28.0`): the whole bundle as sized, format 0.8 adopted.
  The maintainer kept it whole when the lead proposed a lean cut (2026-11-06, "Keep full 0.28"). Heading
  marked ✅. The C8/C17 "you may move them" reminder is moot: they shipped in it. 0.28.1 and 0.28.2 (maintenance
  runs, replay, pruning, parallel re-publish) are the lead's patches, not scope. Deploying is the person's,
  `docs/UPGRADE.md` 0.28; the sweep's operator question is the lead's desk #218.
- **0.29 published** (2026-11-11, `v0.29.0`; heading marked ✅, c17af6e): the namespace rename, sized by the
  person in the lead's session ("1a 2a 3a", reversing S28). 0.29.1 (rebuild once the enricher carrying RM428, the
  GWAS page-size fix, is on PyPI) is the lead's patch, not scope.
- **0.30 is the caching proxy by lane and by pass** (the person, 2026-11-11, forwarded by the lead; requirements
  filed in the roadmap's 0.30 section). The lead builds it. Three questions are put to the person in chat
  answered for licences ("don't serve forbidden, serve what allows redistribution": pharmvar, pubmind, mane, acmg
  not served, pubmind leaves /hint too); alphagenome_avi remote-vs-live still open under its default. Relay their
  answers into the section. The row catalog plus gene facet moves behind it, to 0.31.
- **Upstream parked RM378** (coded strict errors): the strict-phrase match in *Next registry version* may be
  permanent (da9d8b8).
- **Strategy** (`docs/STRATEGY.md`): who it serves first (installers) and what it will not become are settled;
  nothing open.
- **Dream triaged** (2026-10-18 dream, `docs/DREAMS.md` §7, 89092ff): the row catalog plus a gene-level facet to
  the lead (637623436, after 0.28, so now due for 0.29's sizing); nine ideas on `docs/TO_RESEARCH.md`.
- **Push works**; commits go by path, `git commit --only -- <paths>` (base, kit #286), after a race on
  2026-11-05 put a pm roadmap paragraph inside the liaison's 7e88e7d.
- **Auto-mode rules** still stale for the person to apply (rule 14 older), `automode.py --apply`, told 2026-11-10.

## Tools

Nothing the repo ran before the kit belongs to this seat: the triage scripts and wakers are triage's. Kept
none, retired none, moved none.
