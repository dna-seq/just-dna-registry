# Pm — notes

The pm seat's working state, rewritten to the present before a reset (`docs/seats/PM.md`, "Before a reset").

## Now (2026-11-07)

First seating done on this machine. SPEC, ROADMAP (from "Next registry version") and UPGRADE read whole.

- **0.28 published** (2026-11-06, desk #215; tagged `v0.28.0`): the whole bundle as sized, format 0.8 adopted.
  The maintainer kept it whole when the lead proposed a lean cut (2026-11-06, "Keep full 0.28"). Heading
  marked ✅. The C8/C17 "you may move them" reminder is moot: they shipped in it. 0.28.1 and 0.28.2 (maintenance
  runs, replay, pruning, parallel re-publish) are the lead's patches, not scope. Deploying is the person's,
  `docs/UPGRADE.md` 0.28; the sweep's operator question is the lead's desk #218.
- **Next: 0.29 is not sized.** Its candidates are the open entries under *Next registry version* plus whatever the
  liaison maps from upstream's next patch (RM400/401/403, a patch, so likely 0.28.x). Size it with the person
  when they ask, or when the lead runs out of decided work; not before.
- **Upstream parked RM378** (coded strict errors): the strict-phrase match in *Next registry version* may be
  permanent (da9d8b8).
- **Strategy** (`docs/STRATEGY.md`): who it serves first (installers) and what it will not become are settled;
  nothing open.
- **Dream triaged** (2026-10-18 dream, `docs/DREAMS.md` §7, 89092ff): the row catalog plus a gene-level facet to
  the lead (637623436, after 0.28, so now due for 0.29's sizing); nine ideas on `docs/TO_RESEARCH.md`.
- **Push works**; commits go by path, `git commit --only -- <paths>` (base, kit #286), after a race on
  2026-11-05 put a pm roadmap paragraph inside the liaison's 7e88e7d.
- **Auto-mode rules** still stale for the person to paste (1, 2, 3, 5 older, 13 missing), told 2026-11-05.

## Tools

Nothing the repo ran before the kit belongs to this seat: the triage scripts and wakers are triage's. Kept
none, retired none, moved none.
