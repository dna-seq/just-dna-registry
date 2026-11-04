# Dreams: just-dna-registry, 2026-10-18

A one-time dream, run on 2026-10-18 by four model families at medium effort, on one brief: ignore
every constraint and say what this registry should become. The models read a `git archive` copy of
HEAD (7c48684, 2026-09-30) with every data file removed (the one deleted was
`assets/acmg_sf/acmg_sf.csv`); no genome data was read. **This is inspiration, not a plan.** Nothing
here was decided, and nothing in it outranks the repo's own CLAUDE.md, roadmap or rules.

| Model | Ideas | Exit | Time |
|---|---|---|---|
| claude-opus-5-5 (this session, Opus leaf) | 9 | n/a (in session) | 115 s, 1,176 words |
| gpt-5.6-sol-medium (Cursor CLI, `--mode ask`) | 8 | 0 | 55 s, 821 words |
| grok-4.7-medium (Cursor CLI, `--mode ask`) | 9 | 0 | 127 s, 1,241 words |
| gemini-4-argon-medium (Cursor CLI, `--mode ask`) | 8 | 0 | 92 s, 1,576 words (over the ~1,200 cap) |

## 1. Convergence

Eight themes. The cell is the idea's rank in that model's list; "p" marks a partial match.

| Theme | Opus | Sol | Grok | Argon |
|---|---|---|---|---|
| **A. Rows, not files: a claim / variant-level catalog** with cross-module conflicts | 1 | 1 | 1 | 1 |
| **B. Living modules: the registry watches sources and proposes the next PATCH** | 3 | 3 | 3 | 2 |
| **C. "What applies to my genome"**: relevance or annotation across the catalog | 2 | 4 | 2 | 5 |
| **D. Scientific trust, not byte trust**: row-level review, evidence grading | 5 | 2 | 5 | 6 |
| **E. Federation and a transparency log** | 7 | 8 | 7p (cache peers) | 7 |
| **F. Composition**: bundles of modules, resolved conflicts | 9 | 5 | (4, forks, adjacent) | 8p |
| **G. Agents as first-class publishers and reviewers** | 5p | 7 | 9 | 6p |
| **H. One store for the family** (modules, PGS scores, biomarkers) | | | 6 | 8 |

**All four met on A, B, C and D**, and A was every model's first idea. The shared picture: the
registry is excellent at proving which bytes arrived and has stopped there. Its unit is the module
file, while what a reader, an author and a consumer all care about is the row (a variant, an allele,
a claim, a source release). Once rows are indexed, three things follow that every model reached
independently: conflicts across modules become visible (A), a source release can be traced to the
rows it moves and turned into a proposed version (B), and a person's own variants can be matched
against the whole catalog (C). D is the trust layer that A makes possible: review and grading at
the row, because server-side recompile proves the spec compiled, not that it is true.

**Three, nearly four, on E**: Opus, Sol and Argon want a transparency log and mirrors for manifests;
Grok's version federates the *caches* (a peer ring for the snapshot lanes and the unbuyable upstream
budgets), not the catalog.

**Two or three on F and G.** Composition (Opus, Sol; Argon's composite phenotype evaluator is close).
Agents as the main publisher with a queue and feed of their own (Sol, Grok; Argon's adversarial
referee agent and Opus's review agents touch it). **Two on H**: Grok and Argon both want PGS scoring
files and biomarker panels in the same store, on the argument that a person should not learn which
repository owns which shelf.

## 2. Only one saw

- **Population calibration on public genomes** (Opus 4). At publish, run the module over 1000 Genomes
  or HGDP on the box and attach hit rates and score distributions per population, so a carrier module
  that flags 30% of one ancestry is visible before install. Public data, so no privacy line moves.
- **Forks that do not burn the hash** (Grok 4). `content_signature` makes the same rows under another
  name a permanent `409 duplicate_content`, which yank never frees. A fork that cites its parent's
  signature and publishes a delta would make remixing and subsetting possible. Specific to a real
  pain in this repo.
- **Row patches** (Grok 8). A new version ships only the rows that changed, keyed by `variant_key`,
  verified against the new Merkle root; a big ClinVar panel that moves twelve rows stops re-crossing
  the proxy.
- **Installs talk back** (Argon 3). Opt-in, differentially private aggregate hit counts per module
  version from lite installs, to catch modules that pass `/check` and still never match real VCFs.
  Note: this sends genome-derived aggregates off the machine; see Divergence.
- **End the 0.x lockstep by compiling to several format minors** (Argon 4). Store the authored spec and
  serve each client the artifact for the format minor it speaks. The one idea aimed squarely at the
  repo's most-documented pain (S18, S20, S21 in the history file).
- **Pangenome-native identity** (Sol 6). GA4GH / VRS identities and graph coordinates instead of
  GRCh38 offsets, with SVs, star alleles and mitochondrial heteroplasmy first-class.
- **Compress the prose into checks** (Opus 8). CLAUDE.md is 1,154 lines; most paragraphs are a rule
  and the incident behind it. Make each rule an executable check that names its incident.
- **A public evidence page per gene and variant** (Opus 6), built on A, for people who never install
  lite.

## 3. The bets

- **Opus**: the variant-level catalog (A): one rebuildable projection table that keeps every invariant
  and is the substrate for conflicts, personal relevance, public pages and reclassification notices.
- **Sol**: the Living Evidence Graph (A, with B built in): modules become compiled views over
  traceable claims.
- **Grok**: Ask With a Genome (C), built on the claim graph (A): "the thing the house is for".
- **Argon**: Autonomous Living Panels (B) on a durable async job engine, which would also fix the
  dropped large-publish connection (S26).

**Where they agree:** three of four bets rest on A, the row-level layer (Opus and Sol bet on it
directly, Grok as the substrate of its bet). Argon is the one outlier, betting on the update loop
instead, but B is also inside Sol's bet, so the two most-shared bets are A then B. Nobody bet on
federation, trust grading or composition, though all four listed trust.

## 4. Divergence

**Diagnosis: what each thinks the real problem is.**
- *Opus*: the repo spends its imagination on the artifact's correctness and almost none on what a
  person does with it; second, its correctness lives in prose one context window can hold.
- *Sol*: byte trust is not scientific validity. Integrity is solved; validity, relevance and currency
  are not.
- *Grok*: the repo refuses to stand on the genome-to-module join, which is the reason the family
  exists. "Everything else in the plan makes the house safer."
- *Argon*: four self-imposed walls (siloed modules, frozen versions, the format lockstep, installs that
  never talk back), and the pain that eats the engineering is version skew and staleness. The only
  one to name the lockstep as the core problem.

**On the genome line, the sharpest split.** Opus and Sol keep the genome strictly local: lite
downloads a signed index and intersects it on the machine. Grok sends only variant keys, opt-in, or
uses a local join against a feed. Argon proposes a `POST /annotate` that receives variant keys and
a telemetry endpoint for aggregates from real VCFs. The set of variant keys a person carries is
genome data, so Argon's two ideas (3, 5) cross the line this ecosystem treats as absolute, and Grok's
keys-only option grazes it.

**Style of thought.**
- *Sol* is the most abstract: no file, rule or issue cited; standards vocabulary (GA4GH, pangenome,
  nutrition label); institution-centred (universities, labs, national projects); the shortest answer
  and the boldest structurally (retire the module as the unit).
- *Grok* is grounded and terse: it quotes the exact repo rule each idea breaks, sees the
  `duplicate_content` tax and the shared polygon/production IP no other model saw, and is the most
  person-centred ("what applies to me").
- *Argon* is the most citation-heavy (S-ids, RM numbers, field names) and the most willing to put an
  LLM and user telemetry into the server; also the one that ran over the word cap and misplaced a
  few references.
- *Opus* is grounded in counts (releases, reference modules, inbox adopters) and the most cautious in
  its bet: it chose the idea that breaks the fewest invariants.

## 5. Facts that did not hold

Checked against the archived copy. Ideas were not judged, only the facts they rest on.

- **Grok: "the Ed25519 signing the spec has deferred since the beginning."** Wrong. Optional Ed25519
  signing is built: `config.signing_key` (config.py:380), `sign_digest` imported in
  services/publish.py:54, `GET /api/v1/pubkey` (api/app.py:203), verification in client.py:497, an
  `ed25519` badge in the console. It is off by default. The likely source of the error:
  docs/ROADMAP.md:248 still lists it under *Deferred*, a stale line.
- **Argon: "Finishing Ed25519 manifest signing (`pubkey` is already wired)."** Partly: the signing is
  finished, not just wired; whether production turns it on cannot be told from the copy. Opus's own
  opening ("Ed25519-signed manifests") is partly wrong for the same reason: signing is optional.
- **Grok: "the catalog's five expert modules."** Wrong for this repo. It comes from AGENTS.md:1142, and
  **AGENTS.md is not this repo's file**: it opens "the coding standards and practices for
  **just-dna-lite**" and differs from CLAUDE.md from its first line. The registry's own docs speak of
  16 reference modules (CLAUDE.md:121). Argon's `just-biomarkers` and `lipidmetabolism` come from the
  same file. (A side finding worth a look: the repo ships another project's AGENTS.md.)
- **Grok: "A review is a free-text comment."** Partly: a review is a 1-5 rating, an optional verdict
  and notes, which the namespace owner can highlight (api/routers/reviews.py, models/api.py:587).
- **Grok: "a 180 MiB ClinVar panel."** Partly: CLAUDE.md:243 uses a 180 MiB spec as an example of the
  raw-upload `413`; the measured large panel on the roadmap is `pathogenic`, 20 of 25 MiB packed.
- **Argon: "the roadmap already notes ... (S45)."** Partly: S45 is the format tree's series, cited in
  CLAUDE.md as upstream's 0.6.4 measurement, not a registry roadmap item.

Held, among those checked: production and the polygon share one IP (ROADMAP.md:584, Grok); the
verification block is deliberately never a facet (ROADMAP, Grok); "the API serves JSON, not artifact
bytes" (CLAUDE.md:294, Argon); S18, S20, S21 are lockstep and patch-column incidents (history file,
Argon); `titles_as_quotes` is RM118 (Argon); `compiled_by="marketplace-server"` is a kept literal
(CLAUDE.md:695, Argon); there is no job runner yet (the roadmap's job route is unbuilt, Sol);
`genome_build` defaults to GRCh38 (SPEC.md:55, Sol); `version_genes` is the only per-row projection
(db/schema.py, Opus); 51 releases from 0.1.0 (2026-07-06) to 0.27.0 (2026-09-27), and the inbox is
mostly from just-module-creator (Opus).

## 6. The four reports, verbatim

Each report is unedited; their heading levels vary and are kept as written.

---

### Report: Opus (claude-opus-5-5)

# Dream: just-dna-registry (Opus)

What it is today: a careful, single-instance catalog for compiled annotation modules (FastAPI, SQLite projection of immutable manifests, HF storage, server-side recompile, Ed25519-signed manifests, a polygon twin for rehearsals), plus since 0.25 a caching proxy that rents its enricher snapshots and drafters to thin clients. Its publishers are mostly agents (the S1-S27 inbox is almost all from just-module-creator), its catalog is small (the docs speak of 16 reference modules), and it moves fast: 51 releases between 0.1.0 (2026-07-06) and 0.27.0 (2026-09-27). Its guard rails are excellent; its imagination is all spent on correctness of the artifact, almost none on what a person does with it.

## 1. The variant-level catalog (invert the index)

Today the unit is the module; search goes by gene, category, license. Project every published version's variant rows into a `version_variants` table (variant_key, allele, direction, weight, clin_sig, evidence) so the registry can answer "which modules say anything about rs429358, and what do they say?" Then cross-module conflict detection falls out: two modules giving opposite directions for the same allele is a finding the catalog can show on both cards.
- Why: the consumer cares about variants and traits, not about who packaged them. Conflicts across authors are the most dangerous thing in a catalog of agent-written modules, and nothing sees them now.
- Takes: one projection table filled at ingest from the parquet already stored, a `/variants/{key}` route, a conflict facet; weeks.
- Breaks: "the registry indexes manifests, not rows".

## 2. Personal relevance without the genome leaving

Ship a compact catalog-wide variant index (a Bloom filter or sorted key list per build, signed, versioned) that just-dna-lite downloads and intersects locally with the user's VCF. Lite then says "of 300 modules, these 12 touch variants you actually carry" and ranks them. The registry never sees a genotype.
- Why: discovery by relevance is the 10x for a consumer; browsing cards by category is how app stores looked in 2008.
- Takes: idea 1's table, an export job, a signed artifact under `/index`, a lite feature; a month.
- Breaks: the registry serving anything consumed at install/annotate time (the caching-proxy section says that layer must not become a runtime dependency; this is a downloadable artifact, not a call, but it bends the line).

## 3. Living modules: the registry proposes the next PATCH

Subscribe to source releases (ClinVar monthly, PGS Catalog). When a release reclassifies rows a published module rests on, the server re-drafts against the new snapshot and files a *proposed* version, a pull request for data, which the author accepts, edits or declines. Consumers who installed the old version get a "reclassified since you installed" notice through lite.
- Why: the roadmap's S24 item only tells a reader a source is newer. A module that was right in July and is wrong in November is the real harm, and the author is often an agent session long gone.
- Takes: the job subsystem the roadmap already wants for async publish, a proposals table, a notification feed; two months.
- Breaks: "the server drafts nothing of its own" and the stateless-drafts rule.

## 4. Population calibration at publish

At publish (or on /check), run the compiled module over public reference genomes (1000 Genomes, HGDP) on the box and attach a calibration report: hit rate per population, score distribution, the share of people a module calls "high risk". A carrier module that flags 30% of Europeans, or a PRS whose distribution collapses in one ancestry, is visible before anyone installs it.
- Why: the compile gate proves a module is well-formed, never that it is sane. This is the cheapest truth set there is, and it is public data, so no privacy line moves.
- Takes: a public-genome lane in the caches, a batch annotate path (lite's engine, server side), a report block in the manifest's verification; a month or two, plus storage.
- Breaks: publish latency and cost; the registry running annotation at all.

## 5. Row-level review instead of star ratings

Replace the 1-5 rating plus free-text verdict with structured row attestations: a reviewer (human, or a second model family) marks rows checked, disputed or wrong, with a quote. "Curated" then means "N% of rows independently checked", computed, not highlighted by the owner.
- Why: for agent-authored modules the review that matters is at the row, and the owner highlighting reviews of their own module is not independence.
- Takes: a review-row table, a console view, an MCP surface for review agents; weeks.
- Breaks: reviews as light social data off the manifest.

## 6. A public evidence site per gene and variant

Render idea 1 as static, indexable pages: "APOE: 7 modules, 3 agree, 1 conflicts, sources ClinVar 2026-09". Not an app, a reference other people land on from a search engine.
- Why: it makes the catalog useful to people who will never install lite, and brings authors.
- Takes: a static generator over the projection; days once idea 1 exists.
- Breaks: the console being an operator tool.

## 7. Federation by content identity

`content_signature` and `artifact.digest` are already name-independent identities. Make them the address: an append-only, publicly verifiable transparency log of publishes, and mirrors (a lab, a university) that serve and countersign. Lite resolves by signature from any mirror.
- Why: one box, one key, one person is the single point of failure for anything medical-adjacent.
- Takes: a log (Rekor-like or a git repo of signed entries), a mirror protocol, client resolution; a quarter.
- Breaks: the single-instance design and the HF storage choice.

## 8. Compress the knowledge into checks

CLAUDE.md is 1,154 lines and 95 KB of hard-won reasoning; the changelog is 3,700 lines. Most paragraphs are a rule plus the incident that earned it. Turn each rule into an executable check (a test, a lint, a property) that names the incident, and shrink the prose to an index. A second human contributor, or a fresh agent, cannot absorb the present form.
- Why: the repo's real risk is that its correctness lives in prose only one context window can hold.
- Takes: an afternoon per section, done steadily.
- Breaks: the repo's documentation culture.

## 9. Modules that compose

Let a module declare dependencies on other modules (a cardio panel built from lipid, coronary and Lp(a)), with a resolver and a lockfile. The registry resolves the graph and refuses cycles and conflicting pins.
- Why: today every author re-curates shared variants; composition is how ecosystems scale.
- Takes: a manifest field upstream, a resolver here; weeks after the format agrees.
- Breaks: one module = one flat, self-contained artifact.

## The bet

Idea 1, the variant-level catalog. It is small (one projection table, fed from parquet the registry already stores and recompiles), it keeps every invariant that matters (the manifest stays the truth, the table is rebuildable), and it is the substrate for four of the others: conflicts, the personal relevance index, the public evidence pages, and reclassification notices. Every other idea either needs it or gets cheaper with it.

---

### Report: GPT-5.6 Sol (gpt-5.6-sol-medium)

The repository is evolving from a module catalog into shared infrastructure for authoring, validating, enriching, and governing genomic annotation knowledge. Its biggest blind spot is that strong artifact integrity still does not establish scientific validity, relevance, or currency.

1. **The Living Evidence Graph**
   
   Replace modules as the primary unit with an addressable graph of claims: variant, genotype, phenotype, population, effect, evidence, source release, and curator. Modules become reproducible views compiled from that graph; source changes automatically generate reviewable diffs and candidate releases.
   
   **Why:** Today an entire module must be redrafted and republished when the world changes. A claim graph makes provenance, conflicts, reuse, and incremental updates native.
   
   **Takes:** Stable claim IDs, temporal provenance, source watchers, graph storage, deterministic view compilation, migration of CSV rows.
   
   **Breaks:** Manifest-as-source-of-truth, immutable module-centric storage, publisher-driven releases.

2. **Scientific Trust, Not Just Byte Trust**
   
   Add a scientific assurance layer distinct from integrity: independent replication, population applicability, study design quality, sample size, effect uncertainty, retraction status, curator identity, and unresolved disagreement. Publish a machine-readable “nutrition label” rather than collapsing trust into stars, reviews, or compile success.
   
   **Why:** SHA-256 proves which bytes arrived, not whether a conclusion deserves belief. This is the missing layer between a technically valid module and responsible consumer-genomics use.
   
   **Takes:** Claim-level review, signed curator identities, evidence-quality ontology, retraction feeds, conflict-preserving aggregation.
   
   **Breaks:** The registry’s reluctance to judge scientific claims or make verification filterable.

3. **Continuous Evidence CI**
   
   Turn every published module into a continuously tested project. Scheduled workers watch ClinVar, GWAS Catalog, PharmGKB, publications, retractions, reference assemblies, and compiler releases; they run semantic diffs and open proposed upgrades with exact affected claims.
   
   **Why:** “Current when published” is insufficient for biomedical knowledge. The roadmap already identifies source currency, but periodic refresh should become the central product rather than an operator command.
   
   **Takes:** Durable jobs, source adapters, event history, notification subscriptions, automated patch proposals, publisher approval workflows.
   
   **Breaks:** No background orchestration, rebuildable projection-only DB, manual upgrade model.

4. **A Personal Relevance Planner**
   
   Let a client locally summarize which variant classes, genes, builds, and evidence domains are relevant, then ask the registry for the smallest useful module set and an execution plan. The genome stays local; the registry returns signed indexes, selective artifact ranges, and expected coverage.
   
   **Why:** Browsing modules is catalog thinking. Users want to know what improves analysis of this genome, condition, medication list, or question without uploading sensitive variants.
   
   **Takes:** Privacy-preserving capability queries, fine-grained artifact indexes, module coverage metadata, local planning SDK.
   
   **Breaks:** Whole-module download as the main consumption unit and purely human-directed discovery.

5. **The Module Composition Compiler**
   
   Build phenotype-oriented bundles from many modules while explicitly resolving duplicate claims, incompatible weight scales, conflicting clinical significance, licensing constraints, and overlapping evidence. Produce a signed composition manifest explaining every inclusion, exclusion, and precedence decision.
   
   **Why:** The registry can find modules but cannot safely answer “use these together.” That becomes critical as the catalog grows beyond a handful of expert modules.
   
   **Takes:** Semantic types for weights and claims, dependency/conflict declarations, license solver, reproducible bundle compiler.
   
   **Breaks:** Modules as isolated artifacts and the refusal to define cross-module precedence.

6. **Pangenome-Native Annotation Exchange**
   
   Make genomic identity independent of one linear assembly by representing loci through GA4GH identifiers and graph/pangenome coordinates, with GRCh37, GRCh38, CHM13, structural variants, mitochondrial heteroplasmy, haplotypes, and pharmacogenomic star alleles as first-class forms.
   
   **Why:** GRCh38-centered positional joins exclude important variant classes and populations. A future registry should exchange biological identities, not merely chromosome offsets.
   
   **Takes:** New identity contract, graph-reference services, liftover evidence, ambiguity-preserving mappings, compiler overhaul.
   
   **Breaks:** Current coordinate model, lockstep format contract, conventional three-parquet assumptions.

7. **Agent-Native Publishing Cooperative**
   
   Give specialized agent seats durable roles: source scout, evidence verifier, licensing auditor, compiler, adversarial reviewer, and release steward. Agents propose modules or updates, but humans approve scientific closure and disputed decisions through a structured review queue.
   
   **Why:** The existing ecosystem already distributes work across AI-assisted repositories. Making that workflow explicit could multiply coverage without pretending autonomous extraction equals curation.
   
   **Takes:** Durable task/event system, agent identities, evidence packets, policy gates, human sign-off, auditable prompts and tool traces.
   
   **Breaks:** Stateless drafting, one-request workflows, free-text authorship, and the console’s narrow operator role.

8. **Federated Registry and Transparency Log**
   
   Allow universities, patient groups, labs, and national projects to run registries that synchronize signed manifests and claim records. Anchor releases in an append-only transparency log so deletion, replacement, moderation, and signing-key rotation are independently auditable.
   
   **Why:** A single operator, database, signing key, and Hugging Face repository are a governance bottleneck. Federation makes the format an ecosystem standard rather than one service.
   
   **Takes:** Global identities, trust policies, key rotation, mirror protocol, conflict handling, transparency proofs.
   
   **Breaks:** Central namespaces, one authoritative catalog, one-server signatures, local moderation.

**The bet: The Living Evidence Graph.** It unlocks continuous updates, scientific review, safe composition, agent workflows, and federation. The existing registry has already mastered artifact discipline; turning immutable packages into compiled views over traceable claims is the step that could make it foundational rather than merely useful.

---

### Report: Grok 4.7 (grok-4.7-medium)

The registry is a trusted publisher for annotation modules: authors upload a spec, the server recompiles it, and installers download a verified parquet. Since 0.25 it also rents out the enricher's caches, drafters, and lookups. The roadmap after that is still the catalog: jobs for long publishes, read-time currency, a stats endpoint. The person with a VCF is still expected to download files and join them somewhere else.

## 1. The Claim Graph

Stop treating a module as a file and treat every published row as a versioned claim: this variant, this weight, this phenotype, this PMID, this licence, this content signature. `GET /claims?variant=` returns what the whole catalog says, with disagreements side by side. A card is a view over claims, not the unit of storage.

It matters because nobody can ask a cross-module question without downloading the corpus. Gene search is a side table; the scientific object is the row.

It would take a variant-key index (the compiler already mints `variant_key`), licence carried per row, and a query API beside the file API. It breaks "the manifest is the source of truth and the database is a rebuildable projection," and the rule that install-time annotation must never depend on this box.

## 2. Ask With a Genome

A lite install, or an agent, sends only the variant keys it carries (or a local join against a signed claim feed). The answer is the annotation those keys earn: weights, conflicts, PGx calls, what was unchecked. The VCF never leaves the laptop if the feed does.

It matters because the family of repos exists to join a genome to modules, and this repo refuses to be on that path. Browsing a store is a publisher's job; the other user wants "what applies to me."

It would take the claim graph, a delta feed, and a privacy story (keys only; no genotypes unless the caller opts in). It breaks "this layer must not become a runtime dependency for every install."

## 3. Intent, Not Snapshot

An author publishes a recipe: these genes, this phenotype, these inclusion rules, these overrides. The registry re-drafts when ClinVar, CPIC, or gnomAD moves, opens a proposed PATCH with a row diff, and publishes only when the author accepts. Currency is the product; the frozen spec is a build artifact.

It matters because a module is stale the week after publish, and the open roadmap item can only say "behind." Re-drafting in place is forbidden because it appends corrected rows beside the old ones. Holding the recipe is how a re-draft stays a fresh directory.

It would take durable authoring intent, a scheduled probe of `PROBE_SOURCES`, and a proposal queue a human or a seat accepts. It breaks "this service drafts nothing of its own" and "drafts are stateless."

## 4. Forks That Do Not Burn the Hash

`content_signature` is a global claim: the same rows under another name are `409` forever, and yank does not free them. Replace that with a derivation: a fork cites a parent signature and publishes a delta (added rows, `overrides.csv`). Unchanged bytes are free to cite; only an uncredited copy is a duplicate.

It matters because the immutability rule, which protects the catalog, also makes remixing, translating, and subsetting a permanent tax. One person plus agent seats will hit that wall long before strangers do.

It would take a parent pointer on the manifest and identity defined over the delta. It breaks the global `duplicate_content` claim and "a published identity is spent for the life of the database."

## 5. The Evidence Court

A review is a free-text comment. Make the contested unit the row. Anyone can file a counter-citation; a module can disagree with another module on the same variant; a signed verdict (upheld, narrowed, withdrawn) rides the download. Trust stops meaning "our compiler finished."

It matters because server-side recompile proves the bytes match the spec. It does not prove the spec is true. The catalog's five expert modules and every future one fail or stand on that gap.

It would take row-level review objects, the claim graph, and the Ed25519 signing the spec has deferred since the beginning. It breaks "the verification block is never a facet."

## 6. One Store for the Whole Family

Catalog annotation modules, PGS scoring files, biomarker panels, and reference-lane releases as one kind of installable, with one client and one update feed. `just-prs` scores and registry modules are both "something you join a VCF to," discovered today in different apps.

It matters because a person installing lite should not learn which repo owns which shelf. The Store sketch in this tree is still a module grid.

It would take a type field on the card and adapters that verify a score file the way `verify_manifest` verifies a module. It breaks "this repository catalogs annotation modules."

## 7. The Peer Ring

Any deployment can register as a cache peer. A miss walks a signed ladder: this box, a peer registry, then the remote source. Lane manifests and derived tables replicate; gnomAD egress stays on boxes that have already spent their allowance. Polygon and production stop sharing one IP's budget by accident.

It matters because the caches are tens of gigabytes and the unbuyable rate limits are per IP. The 0.25 proxy helps clients who can reach this one server. A second honest operator cannot extend it.

It would take peer discovery, signed lane indexes, and a shared pace ledger that is not the catalog database. It breaks "one container, one bucket, one SQLite file."

## 8. Row Patches

A new version ships the rows that changed, content-addressed, plus a signature from the parent. Lite applies the patch. Full tarballs remain for first install. A 180 MiB ClinVar panel that moves twelve rows does not cross the proxy again.

It matters because publish already dies when the connection outlives the proxy, and panels grow with every ClinVar release. The planned job queue makes the wait polite; it does not make the bytes smaller.

It would take a row-level diff keyed by `variant_key`, and a client that verifies the result against the new Merkle root. It breaks "download the artifact, then verify."

## 9. Seats as the Primary Publisher

Accept a claim packet: rows, the quote that locates each one, the tool transcript that produced it. Refuse a row whose quote does not resolve to a passage. Emit a feed agents can subscribe to: modules behind their source this week, namespaces with a lost key, proposals waiting. The console stays for the cases a person must see.

It matters because the authoring half of this ecosystem is already agent seats, and the API is still shaped as a browser store plus an operator CLI. The seats are the user who will publish a hundred modules. A person will not.

It would take the evidence court, intent-not-snapshot, and a webhook or feed beside the REST catalog. It breaks "the console is the publisher surface and agents are just another HTTP client."

## The bet

**Ask With a Genome**, built on the claim graph. The file catalog, the polygon, the integrity contract, and the cache proxy are already a careful publishing house. The next decade of this work is a person, or their install, asking what the published record says about the variants they carry, and whether that answer is still current. Everything else in the plan makes the house safer. This is the thing the house is for.

---

### Report: Gemini 4 Argon (gemini-4-argon-medium)

`just-dna-registry` started as a thin catalog and compile-gate over HuggingFace, and by `0.27` has quietly become the **epistemic and reference hub** of the ecosystem: it holds the multi-gigabyte reference caches (`CACHE_LANES`), rents out drafters and lookups (`/drafts`, `/hint/*`), arbitrates global content identity (`content_signature`), and mediates between human/agent authors (`just-module-creator`) and local installs (`just-dna-lite`).

Yet it is trapped by four self-imposed walls: **modules are siloed bags of files**, **versions are frozen snapshots in a moving biological world**, **the client/server format minor is a brittle lockstep**, and **installs never talk back**. Here are eight ideas for what this service becomes when those walls come down.

---

### 1. The Living Evidence Graph (Kill the Module Silo)
* **The idea:** Stop treating modules as isolated zip archives that each re-curate the same variants and papers from scratch. Make the registry a global, content-addressed graph of atomic `(Variant/Haplotype, Assertion, Study Quote, License)` nodes, where a "module" is merely a signed, versioned DuckDB/SQL query or view over the shared graph.
* **Why it matters:** Right now, if `rs429358` (`APOE`) or `CYP2C19*2` is curated in five modules, four of them are duplicating work or drifting apart, and `409 duplicate_content` only catches 100% whole-module clones. A shared assertion graph lets authors compose modules, inherit verified literature quotes, and audit contradictory conclusions across the entire catalog at a glance.
* **What it would take:** A graph table in the catalog indexing every row of `variants.csv`, `haplotypes.csv`, and `studies.csv` by canonical VRS ID and PMID; a query-manifest spec that compiles a view into the standard parquets on demand.
* **Constraint broken:** Breaks the rule that `manifest.json` per module directory is the atomic source of truth, and replaces whole-module `content_signature` dedup with row-level provenance.

### 2. Autonomous Living Panels (Self-Healing Modules)
* **The idea:** Turn the registry from a passive warehouse into an active, scheduled curator that watches ClinVar, CPIC, PharmVar, and PubMed, and automatically opens "candidate PATCH/MINOR branches" whenever upstream biology moves. Instead of waiting for an author to notice `dataset_currency` is behind and re-draft from a fresh directory, the server wakes an agent seat to draft the delta, run `/check`, verify new PMIDs, and hand the human owner a one-click diff to sign.
* **Why it matters:** Human genetics moves monthly; static modules rot. The roadmap already notes that in-place re-drafting appends superseded rows (S45) and that catalog readers cannot tell when a module is behind its upstream source (S24). Making the registry the continuous compiler of upstream truth makes every published panel stay current without manual babysitting.
* **What it would take:** A scheduled worker combining `warm-caches`, `check_dataset_currency`, a clean-room `draft_module` runner, a semantic diff engine over compiled parquets, and a staging state (`candidate` versions) before immutable publication.
* **Constraint broken:** Breaks *"Drafting is authoring-side and this service drafts nothing of its own"* (`CLAUDE.md`).

### 3. Zero-Egress Federated Reference Concordance (Installs Talk Back)
* **The idea:** Every `just-dna-lite` install annotates real VCFs locally; let installs optionally return anonymous, differentially private aggregate hit-counts per module version (`variant_key` call rates, missing-callable loci, empirical zygosity distributions, PRS score quantiles) back to the registry. The registry compares a module's declared gnomAD frequencies and `requires_callable` flags against what actually matches in real user VCFs across sequencing platforms.
* **Why it matters:** The registry is currently blind to what happens after `302 Redirect`. A module can pass `/check --strict` with flying colors and still silently fail to match 40% of real-world WGS/array VCFs because of indel normalization quirks, build liftover artifacts, or uncalled regions.
* **What it would take:** A `POST /api/v1/modules/{ns}/{name}/versions/{v}/telemetry` endpoint accepting k-anonymized summary sketches, plus a "Field Concordance" badge on the module card and `/check` warnings for variants that never match in the wild.
* **Constraint broken:** Breaks the strict one-way boundary between install-time annotation and the registry.

### 4. Multi-Target Artifact Virtualization (End the `0.x` Lockstep)
* **The idea:** Decouple what a publisher uploads from the single `just-dna-format` minor the server happens to have installed in its `.venv`. The registry stores the canonical authored spec + `derived/` sidecars and compiles artifacts into an **on-demand matrix of format minors** (`format=0.6`, `format=0.7`, `format=0.8`) using isolated worker environments or WASM compiler capsules, serving each client the exact contract minor it asks for in `X-Format-Version`.
* **Why it matters:** Half of `CLAUDE.md` and `ROADMAP.md` (S18, S20, S21) is battle scars from the lockstep rule: upgrading the server breaks `0.6` clients; publishing PyPI first breaks `0.7` clients; `extra="forbid"` turns a new patch column (`StudyRow.curator`) into a brick wall. Virtualizing the compile target makes version skew vanish overnight.
* **What it would take:** Keying artifact storage by `(canonical_id, format_minor)`, caching compiled parquets per format version, and running `just-dna-compiler` inside version-pinned uv environments or sandboxes.
* **Constraint broken:** Breaks *"The floor is a lockstep, not a minimum"* and `version.contract_compatible` refusing cross-minor clients.

### 5. Remote Zero-Download Annotation & DuckDB-over-HTTP
* **The idea:** Allow thin clients, clinicians, or browser sessions to annotate a list of variants—or a client-side pre-filtered locus bloom filter—directly against the registry's entire catalog without downloading and installing individual modules. Alternatively, serve the entire catalog's compiled parquets as a single unified Hive-partitioned dataset that `just-dna-lite` queries in-place via DuckDB `httpfs`.
* **Why it matters:** Downloading, hash-verifying, and registering modules one by one works for five modules, not five hundred. A user with a VCF wants to ask: *"Across every trusted module in the registry, what hits my genome?"* in two seconds.
* **What it would take:** A unified catalog parquet projection rebuilt on publish, range-request CDN serving, or a stateless `POST /api/v1/annotate` endpoint that joins uploaded variant keys against all non-yanked trusted modules in memory.
* **Constraint broken:** Breaks *"The API serves JSON, not artifact bytes"* and *"Annotation at install time stays self-contained"*.

### 6. Adversarial Agent Peer-Review Arena (Semantic Trust)
* **The idea:** Today `trusted` only means *"the server ran `compile_module()` and positions join to a VCF."* Add an automated adversarial referee tier: on publish, a separate reviewer agent fetches the full text of every cited PMID, attempts to *falsify* the author's `conclusion`, `effect_allele`, and `weight` (catching flipped risk alleles, p-values from the wrong cohort, or overclaimed GWAS hits), and writes a signed `referee_report.json` sidecar.
* **Why it matters:** `titles_as_quotes` (RM118) already proved that syntactic quote-matching can be gamed by quoting the paper's title. In consumer genomics, a flipped `effect_allele` passes every schema and Ensembl check while telling a person the exact opposite of their genetic risk.
* **What it would take:** An asynchronous referee queue on publish/check that pairs Europe PMC full-text retrieval with a structured LLM verification rubric, producing a semantic confidence score alongside syntactic `trusted`.
* **Constraint broken:** Breaks the purely deterministic, non-LLM server boundary and synchronous publish grading.

### 7. Cryptographic Transparency Log & Portable Reproducibility Capsules
* **The idea:** Replace `"compiled_by": "marketplace-server"` (a string anyone who forks the compiler can write locally) with an append-only, Merkle-tree transparency log (like Sigstore/Rekor for genomics) and bundle the exactEnsembl/ClinVar slice used during enrichment into the artifact's `derived/` directory. Any third party can then cryptographically prove when a module was published, verify no history was rewritten, and recompile it byte-for-byte ten years later when live Ensembl has moved on.
* **Why it matters:** Clinical and research provenance requires more than trusting one central box's string literal; if the registry database is compromised or an operator runs `remove-version`, there is currently no external audit trail.
* **What it would take:** Finishing Ed25519 manifest signing (`pubkey` is already wired), chaining manifest digests into a signed Merkle tree head served at `/api/v1/log`, and freezing minimal reference slices into the tarball.
* **Constraint broken:** Breaks the `compiled_by == "marketplace-server"` trust heuristic and ops-silent hard removals.

### 8. Unified Multi-Omic & PRS Registry
* **The idea:** Dissolve the wall between `just-dna-registry` (curated variant/haplotype parquets), `just-prs` (PGS Catalog polygenic risk scores), and `just-biomarkers` (blood/lab reference ranges). Make a module capable of bundling SNP weights, a polygenic background score, and lab biomarker modifiers into one composite phenotype evaluator.
* **Why it matters:** Biology doesn't split cleanly into "monogenic/oligogenic module" vs. "PRS" vs. "biomarker": coronary artery disease (`coronary`) or lipid metabolism (`lipidmetabolism`) is an interaction of `LDLR`/`APOB` variants, a polygenic tail, and LDL-C lab values.
* **What it would take:** Extending `just-dna-format` and the registry's facet index to index PGS scoring files and biomarker schemas alongside `weights.parquet`.
* **Constraint broken:** Breaks the repo scope limiting this registry strictly to VCF-joining annotation modules.

---

### The Bet: #2 (Autonomous Living Panels) + #4 (Job-Backed Target Virtualization)

If I had to bet on one path right now, I would bet on **turning the registry into an asynchronous, self-updating compilation engine (#2 + the async job substrate of #4)**.

Why? Look at where the real pain in your changelog and consumer suggestions actually lives:
1. Your best author is already an AI agent (`just-module-creator`), and your biggest modules are ClinVar/CPIC/STRchive panels whose upstream sources change every month.
2. Synchronous HTTP connections are already snapping under 25 MiB genome-wide panels (S26), and version-skew friction between `format`, `compiler`, `enricher`, and live instances (S18, S20, S24, S45) consumes half your engineering energy.

If you build the **durable async job engine** first (solving S26 and large online `/check` runs), and then use that engine so the registry **automatically detects upstream ClinVar/CPIC/PGS releases, re-drafts affected modules in a clean sandbox, runs the full online verification suite, and stages the new version for the author or agent seat to approve**, the registry stops being a passive file host. It becomes a self-maintaining genomic knowledge factory.

