# To research: just-dna-registry

Questions not yet worth building. Kept by the pm seat (`docs/seats/PM.md`). Each entry says what was found,
dated, and what would settle it or reopen it. Outside facts are tagged **checked** (read at the source, dated),
**reported** (secondhand, linked) or **unchecked**. An entry leaves this file when it is decided: to the lead
as a proposal, to `docs/STRATEGY.md`, or let go with the reason.

Started 2026-11-04 from the triage of the 2026-10-18 dream (`docs/DREAMS.md` §7).

## PGS scores: inside modules, or in the catalog? (dream theme H)

The maintainer, 2026-11-04: "May become, but we considered pgs ids inside modules. Weigh pro and contra for
module-level vs catalog-level". So the registry *may* become a store for more than annotation modules; this
entry weighs the two places a PGS score can live.

**What exists** (checked, just-dna-format `main`, 2026-11-04): a module can already carry PGS references.
`pgs.csv` is a table kind whose `PgsRow` is keyed `(pgs_id, trait_efo_id)`; the enricher checks each
`pgs_id` against the PGS Catalog (RM163, format 0.7), and the licensing pass writes one licensing row per
score with that score's own licence text. The scoring file itself (the weights) is not in the module; a
consumer such as just-prs fetches it from the PGS Catalog.

**Module-level** (a module references scores by `pgs_id`, as today):

- For: already built, checked and licensed per score, with no new artifact kind. The curator's context
  travels with the reference (trait, tier, research status). The integrity contract and every registry
  rule stay as they are.
- Against: the registry attests the reference, never the weights, so an installer's scoring file is
  outside the digest and outside our verification. A score used by many modules appears once per module,
  and nothing in the catalog answers "which modules use PGS000013" (a gap the row catalog, now going to
  the lead, would close as a `pgs_id` facet).

**Catalog-level** (the registry lists scoring files as installables of their own):

- For: one store and one verify for the person installing; the registry could hash and attest the weights
  an installer actually runs, which is the installers-first argument.
- Against:
  - **Licensing is per score and some forbid redistribution.** Most PGS Catalog scores carry a generic
    "used in accordance with any licensing restrictions set by the authors" sentence, some are
    academic-use-only, a couple are CC0 (checked, upstream's `AGENT_NOTES.md`, measured over the first 250
    scores; 6 of those 250 are academic-use-only). Hosting the bytes makes the registry the redistributor,
    and for the generic sentence nobody can say what was granted. That is a point for a lawyer, not one
    this record settles.
  - A second artifact kind needs a manifest shape, a verifier and a card type from the format, since
    artifact shapes are upstream's.
  - It mirrors a catalog that already serves the files, and large scoring files meet the upload cap the
    roadmap already fights for ClinVar panels.

**Leaning**: keep scores module-level and make them findable catalog-wide (a `pgs_id` facet on the row
catalog), which gets the discovery half of "one store" without redistributing anyone's weights. The
attestation half stays open.

**What would reopen catalog-level**: just-prs asking for verified scoring-file distribution; a licence probe
showing the scores a module set actually uses are redistributable; or the format proposing a second artifact
kind. Biomarker panels are not weighed here: nothing in this ecosystem defines them yet (unchecked beyond
the dream's mention of a `just-biomarkers` project).

## A local "what applies to my genome" index (dream C, Opus 2)

A signed catalog-wide variant index that just-dna-lite fetches and intersects with a VCF on the person's
machine, so the registry never sees a genotype. Fits the strategy only as a downloadable artifact, never as
a call. **Settles it**: the row catalog existing (it is the index's source), and just-dna-lite wanting it.
It is their feature; ours would be the export.

## A public evidence page per gene and variant (dream, Opus 6)

Static pages over the row catalog ("APOE: 7 modules, 3 agree, 1 conflicts"). **Settles it**: the row
catalog built, then whether the page belongs in the console here or in just-dna-lite. It reports what
modules say, so it stays clear of judging the science only if it never ranks one claim above another.

## Transparency log and mirrors (dream E)

An append-only, publicly verifiable log of publishes, and mirrors that serve and countersign. Serves
installers: an audit trail that survives one compromised box. **Reopens when**: a second operator exists, or
an installer asks to verify a module's publish history independently of this box. Optional Ed25519 signing
of `artifact.digest` already ships (0.5.0); whether production turns it on is unchecked.

## A peer ring for the snapshot caches (dream E, Grok 7)

Registries as cache peers, so a miss walks to another box before the remote source. Real: both instances
share one IP's upstream budget (reported in the dream, from `docs/ROADMAP.md`). **Reopens when**: a second
operator runs a box, or the shared budget throttles one of the two instances.

## Modules that compose (dream F)

Module dependencies with a resolver, or bundles with resolved conflicts. **Settles it**: the format deciding
whether a manifest may name other modules; nothing here can start before that.

## Population calibration on public genomes (dream, Opus 4)

At publish or `/check`, run the module over 1000 Genomes or HGDP on the box and attach hit rates and score
distributions per population. A check the server runs itself on public data, so it fits "attests the checks
it ran itself". **Settles it**: the cost of running lite's join server-side per publish (time, storage of
the reference genomes), measured once on the largest module; and whether the result is a fact sidecar the
format attests.

## Forks that do not burn the hash (dream, Grok 4)

`content_signature` claims data globally and `yank` never frees it, so a fork or subset of published rows is a
permanent `409 duplicate_content`. A fork citing its parent's signature would allow remixing. **Settles it**:
a publisher actually blocked by it (none reported as of 2026-11-04), then upstream, since `content_signature`
and its identity rules are the format's.

## Compile to several format minors (dream, Argon 4)

Keep the authored spec and compile per format minor, serving each client the one it speaks, which would end
the lockstep. **Settles it**: the cost of keeping two compiler environments live on a box, measured at the
next coordinated cut (0.28 / format 0.8 is the first chance to try it on paper).
