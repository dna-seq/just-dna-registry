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
- **Pushed**: kit #264 closed in v0.1.127 (rule 11 now covers any seat granted a push); the rules here are
  current (`automode.py --check` clean, 2026-11-04 ~21:20 UTC) and `main` matches `origin/main`.
- **Waiting**: format 0.8 not cut yet (just-dna-format tags end at v0.7.3, PyPI 0.7.1, checked 21:20 UTC).
  When it is, read the liaison's re-map against the 0.28 scope and take only what moves to the person.
- **M8–M11 folded into 0.28** (the liaison's 23e340f, map at upstream `503730c`): all four are part of the
  0.8 adoption the maintainer already bundled, so no new question. M8 (Ensembl repo move, 14.5 GB pull on
  both boxes before the deploy) sits with M1; M9–M11 with M4. **Not pushed**: `main` carries the
  liaison's 23e340f, whose push waits on desk #193; pushing ours would push it too. Push after #193.

## Tools

Nothing the repo ran before the kit belongs to this seat: the triage scripts and wakers are triage's. Kept
none, retired none, moved none.
