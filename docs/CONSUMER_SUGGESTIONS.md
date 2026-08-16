# Consumer suggestions

> **Status:** consumer feedback / design input — not a shipped contract.
> **Audience:** maintainers of `just-dna-registry` (this project) and the
> `just-dna-pipelines` commands that call it.
> **Purpose:** intake for field notes from clients adopting the registry.

Field notes from consumers of the registry service and its client, in sections by
adopter. Numbering (`S<n>`) is local to this file — the format tree keeps its own
series in `../just-dna-format/docs/CONSUMER_SUGGESTIONS.md`, and a note belongs
wherever the *fix* would land.

(Filed from `just-module-creator`, which reaches this repo by its on-disk path
`../just-dna-marketplace`. We understand that to be a legacy directory name rather
than a current one, and refer to the project as `just-dna-registry` throughout.)

S1–S4 were answered in 0.13.0, S5–S7 in 0.14.0, S8–S9 in 0.15.0 and S10–S12 in 0.16.0, all moved to
[CONSUMER_SUGGESTIONS_HISTORY.md](CONSUMER_SUGGESTIONS_HISTORY.md).

---

## How this file is maintained

**This file is the inbox, so an empty one means nothing is owed.** An item answered with a `**Status —**`
reply moves to [CONSUMER_SUGGESTIONS_HISTORY.md](CONSUMER_SUGGESTIONS_HISTORY.md), whose contents list is
the one-line summary of every one; the runbook for answering them is
[CONSUMER_TRIAGE_LOOP.md](CONSUMER_TRIAGE_LOOP.md).

### The next item is S13

**Claim ids from the ledger, never from what this file shows** — once answered items move out, an empty
inbox says nothing about how many ids are taken, and the next report would be a second S1:

```
.claude/triage-state.sh --next        # scans this file AND the history file
```

Ids are never reused, including for an item answered as a non-issue: the reply is part of the record and a
recycled id would collide with it.

### Adding one

Append a `## Sn — <what happened>` section under a `# Field notes from <adopter>` heading with a dateline.
Write the report, not a request: what you ran, what you expected, what happened, and what you did about it
meanwhile. A candidate fix is welcome and so is a reason a candidate is wrong.

Your prose is left byte-for-byte when it is answered and when it is moved, so it stays the record of what
was observed rather than of what was decided. Replies are appended, never written over it.

---

*The inbox is empty. Nothing is owed.*
