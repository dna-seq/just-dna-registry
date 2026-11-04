# Pm — notes

The pm seat's working state, rewritten to the present before a reset (`docs/seats/PM.md`, "Before a reset").

## Now (2026-11-04)

First seating done on this machine. SPEC, ROADMAP (from "Next registry version") and UPGRADE read whole.

- **0.28 sized** (`docs/ROADMAP.md`, "0.28 — format 0.8 adoption…", 8d2610e + db0a85e): the maintainer bundled
  it with the 0.8 adoption (rejected: ship the rest now). All of M1–M7 in, plus the rename, publish recovery,
  the server `.env` fix, the refused-column release and `/stats`. The compiler's lead puts the 0.8 cut 5–8 h
  after 2026-11-04 ~20:00 UTC; the liaison re-maps then, and the scope is re-read against that map.
  `just-dna-compiler/pm` never answered; the lead's estimate replaced the question, nothing to re-ask.
- **Strategy** (`docs/STRATEGY.md`): who it serves first (installers) and what it will not become are settled;
  nothing open. The run-time digest witness is an idea for downstream to decide, not a registry
  question.
- **Dream triaged** (2026-10-18 dream, `docs/DREAMS.md` §7, 89092ff): the row catalog plus a gene-level facet to
  the lead (637623436, after 0.28); nine ideas on the new `docs/TO_RESEARCH.md`, PGS module-level vs
  catalog-level weighed there (leaning module-level plus a `pgs_id` facet); the rest let go with reasons.
  Two stale facts (ROADMAP:248 signing, a foreign `AGENTS.md`) sent to the lead as defects.
- **Avatar** set (an ibex, from admin's 637612986).
- **Account handle rename** filed by the lead (cd67d91, 1659ef8). The maintainer then ruled that `owner` is
  amendable registry metadata: a rename rewrites it on old manifests. Sent to the lead to fix the entry
  (637616735); check the entry says so.
- **Not pushed**: the auto-mode check denies this seat's push of `main` (kit rule 11 lists no pm), filed as
  kit #264. Local commits wait for the person or for the rule's fix.

## Tools

Nothing the repo ran before the kit belongs to this seat: the triage scripts and wakers are triage's. Kept
none, retired none, moved none.
