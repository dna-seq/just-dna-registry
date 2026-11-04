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

## What it will not become

The maintainer, 2026-11-04, picking three lines as written and rewording the fourth.

- **Not an annotation service.** It never takes a person's VCF or genome and runs the join for them. That
  stays in just-dna-lite, on the person's own machine.
- **Not a judge of the science.** It attests bytes, the compile it ran and the checks it ran itself. It never
  grades a module's evidence or states a gene–disease claim as a registry verdict, and a publisher's claim
  stays labelled as a claim (the `VerificationInfo` block is the standing example).
- **Not an authoring tool.** It drafts nothing of its own and keeps no work in progress between calls. It may
  rent out the drafters, statelessly (`POST /drafts`); authoring lives in just-module-creator.
- **Not an annotation-time dependency, though it may be a run-time witness.** An installed module annotates
  with nothing fetched from the registry: the compiled parquets carry what the join needs. The registry *may*
  be asked at run time as a witness, for example to confirm that a local module's digest is the one that was
  published before it runs. The maintainer's words: "it may, as digest witness for example, to validate local
  module sha before run. It is not a runtime dependency annotation-time". The caching proxy (`/hint`,
  `/drafts`, `/caches`) stays an authoring and publish-time surface.

## Open

Questions still to settle with the maintainer, one at a time:

- When the run-time witness cannot be reached, or disagrees, what does the installer do: run and label the
  result unverified, or refuse? "Installers first" points both ways, so this is the maintainer's call. It
  matters once just-dna-lite builds the witness, not before.
