# Strategy: just-dna-registry

Who the registry serves, what it will not become, and why. Kept by the pm seat (`docs/seats/PM.md`), written
from the maintainer's answers, each with the alternative it rejected. `docs/SPEC.md` says what the registry
is; this file says whom it is for when those two pull apart.

Started 2026-11-04. Each entry is decided for the registry as it stands now, not for a sale or a fork.

## Whom it serves first

**Installers come first**: just-dna-lite and the people who install modules through it. What they install
has to be trustworthy and verifiable, and when that conflicts with what a publisher or an operator wants,
the installer's side wins. (The maintainer, 2026-11-04, choosing "installers first".)

What this costs, said once: publishers carry the cost of strict gates. A compile-strict publish that refuses
a module with an unplaced variant, a `409 duplicate_content` that only a purge frees, an immutable version
that a typo spends: each is friction for an author, kept because it protects the reader of the catalog.

Rejected:

- **Publishers first** (module authors, human or agent): lowest friction to publish, with installers taking
  more on trust. The authoring surface (the caching proxy, `/hint`, `/drafts`) stays, but it is a service to
  authors inside the installer's guarantees, never a reason to loosen them.
- **Operators first** (whoever runs a box): cheap and safe to run, with both other parties bending to that.
  Operator cost still bounds what is built (the upstream budgets in `CLAUDE.md` are real), but it decides
  *how* a guarantee is delivered, not *whether*.

## Open

Questions still to settle with the maintainer, one at a time:

- What the registry will not become.
