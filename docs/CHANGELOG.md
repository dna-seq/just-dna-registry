# Changelog

All notable changes to **just-dna-registry**. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions are [SemVer](https://semver.org/).

Full API: [API-REFERENCE.md](API-REFERENCE.md) · client: [CLIENT.md](CLIENT.md) · plan:
[ROADMAP.md](ROADMAP.md).

## [0.13.0] — 2026-08-11

Answers **S1**, **S2** and **S3** from `just-module-creator`, and **S4** from the operator, and adopts
**compiler/enricher 0.5.4**. Nothing here changes a status code, an error `code`, or a field a client
already reads.

**Client surface: unchanged.** No `RegistryClient` method signature moved. Added: `expect_mode=` on
the constructor (optional), `ValidationReport.would_publish_module_level`, `VersionInfo.mode`,
`EnrichmentReport.unreachable_rsids`, `IdentifierCheck.gene_loci` and `.gene_loci_not_checked`.

### compiler + enricher 0.5.4: two answers that used to be one, and a phrase we no longer spell

The floor moves to `just-dna-compiler>=0.5.4` / `just-dna-enricher>=0.5.4` in the `server` extra and
`just-dna-compiler>=0.5.4` in `compiler`. A hard floor: three of the four items below are attributes this
tier now reads unguarded. `just-dna-format` deliberately stays at `>=0.5.0` — upstream bumped it to the
shared number for legibility ("a 0.5.4 compiler naming a 0.5.0 schema is a version pair nobody can
read"), not as a schema cut, so a 0.5.0 client still exchanges artifacts with a 0.5.4 server and
`version.contract_compatible` still says so.

- **An unreachable Ensembl is now `unreachable_rsids`, not silence (enricher S20).** `resolve_rsid`
  used to fuse "asked, no GRCh38 locus" and "the request never completed" into one empty answer, so a
  failed lookup was reported as a definite negative — and `loci: []` beside "Ensembl has no locus for
  it" is exactly the fingerprint of a fabricated rsID. The consumer who found it put two published
  variants (`rs6567160`, a long-standing *MC4R* BMI locus, and `rs13010010`) in the fabricated pile.
  `enrichment.unreachable_rsids` on `/check` names them, `notes` says it in prose, and the publish
  path's strict-refusal hint now says **re-publish** for this case instead of offering the three
  remedies that assume somebody's spec or cache is at fault. It does not soften `would_publish`: a
  strict publish against an Ensembl that will not answer really does refuse. What changes is that the
  refusal no longer reads as an authoring defect.
- **A gene that names another chromosome is its own finding (enricher S24).** `?identifiers=true` gains
  `gene_loci` and `gene_loci_not_checked`. Previously the pass asked whether HGNC approves the symbol,
  which is a different question — `FTO` is approved whatever variant sits beside it — so a row pairing a
  real symbol with an rsID on another chromosome passed everything, both halves being individually true
  and only the relationship false. Chromosome granularity only: a row may legitimately name a distal
  regulatory target, and a pseudoautosomal X/Y disagreement is a spelling. It moves `clean` and, like
  everything else in that pass, not `would_publish`.
- **`db/facets.py` imports the phrase it used to spell** (`compiler.UNJOINABLE_PHRASE`, upstream S13).
  The trust facet keys on a warning substring because the manifest carries no structured record of what
  resolution was applied to (still owed, still upstream's, tracked as RM44 for format 0.6). Upstream now
  freezes the fragment as a named constant whose docstring names this consumer, so a reword is a
  deliberate act with someone to tell rather than a silent re-granting of trust to modules that annotate
  nothing. The pinning test stays and its job narrows: an import proves the spellings agree, not that
  the warning still fires and still reaches `manifest.compilation.warnings`.
- **`PacingGate` is thread-safe upstream now (S15), and this server was the reported cause.** Sharing
  one `LookupClients` bundle across a threadpool is what the enricher's own docstring advises, and the
  gate read `last`, slept, then wrote it — so two threads could both skip the sleep and turn a 3/s
  budget into 6/s. That removes the *correctness* reason `enrich_max_concurrency` defaults to 1; the
  default stays 1 because the reason it protects — one shared, IP-scoped, unbuyable budget — has not
  changed, and a second concurrent run now interleaves on the same pace rather than going faster. The
  comments in `config.py`, `shared_lookup_clients` and `EnrichmentGate` that said the limit is what
  makes sharing correct were true and are now wrong, so they say what is left instead.

Two upstream changes arrive as new **validate/check warnings** with no code here: a `.csv` whose name is
one edit from a real table (`varaints.csv` — previously silent, so the rows were dropped and the compile
was green) and a binning table asserting thresholds with no `studies.csv` anywhere. Both are warnings in
both modes and neither gates a publish. One warning also *stops*: a hand-declared `literature`-layer
row in `sources.csv` is no longer reported as unused when the module carries `studies.csv`, which had
been telling authors to delete the exact row the licence gate exists to read.

### The ceiling withheld the check on exactly the modules that needed it (S1)

Three repairs to the pre-publish dry run.

### The ceiling bounds pacing, so it now bounds only the runs that egress

`enrich_max_variants` exists because the paced passes cost ~6s per twenty subjects against gnomAD's
IP-scoped budget — its own comment said so, and said publish is exempt "because publish never runs
the frequency pass, which is the expensive one this bound is really about". It was nonetheless
enforced unconditionally, including on `?offline=true`, which issues no request for it to bound.

- **`?offline=true` has no ceiling.** Measured on the suite's own spec with the socket tripwire
  armed: 40,000 enrichment subjects offline in **5.1s**, linear from 100 — the ceiling was refusing
  in zero time a run costing under 2% of `enrich_timeout_seconds`. Offline CPU stays bounded by that
  timeout and by `enrich_max_concurrency`, which are the bounds designed for it; a subject count is
  a proxy for pacing and nothing else. So a ClinVar-scale panel is now checkable against whatever
  snapshots a deployment holds, which is the configuration those panels were always going to use.
- **Online runs are unchanged** — resolution still egresses per subject there, so the bound still
  describes a real cost.
- Loosening a refusal, so no client breaks; sized minor rather than patch because it changes what a
  deployment does with a request it used to reject.

### A refusal that still answers what it had computed

`/check` runs `validation_report()` and *then* checks the ceiling, so the `422` was discarding a
module-level verdict the server already held. The inversion this produced is the sharpest statement
of S1: an **invalid** spec over the ceiling has always returned `200` with a full report
(`invalid_spec` short-circuits earlier), so the ceiling withheld the check precisely on the specs
that pass it.

- **`422 too_many_variants` now carries `subject_count`, `limit`, the full `validation` report and
  `would_publish_module_level`.** The `error` code and the status are untouched; the four fixed keys
  of the error body win any collision, so a client branching on them cannot be affected.
- The message names the two ways through — `offline=true`, or `/validate` — instead of only naming
  the knob an author cannot turn. `registry-client check` prints all of it rather than `HTTP 422`.

### `would_publish_module_level` on `/validate`

The publish gates that do not scale with the variant count — the spec validates under `strict`,
`module.name` matches the path, no version is already built from identical data — composed into one
branchable field on a route with no ceiling and no egress. Derived from the same expression
`_would_publish` builds on, so the two cannot drift; `registry-client validate` now exits on the
server's verdict instead of its own fourth copy of those three gates.

**It is deliberately not `would_publish`.** This is the trap the release turns on: a skip must never
produce a positive verdict. `invalid_spec` is safe because it yields `would_publish: false`, but a
`true` beside an unrun network tier is the empty-collection ambiguity `clin_sig_not_checked` was
introduced to end, one level up. So the weaker question got a name that says what it quantifies over
rather than a shared name and a caveat. `true` means nothing module-level blocks a publish, never
that one would succeed — the tier only `/check` runs can still refuse on a reference mismatch or a
withdrawn rsID.

Paging or sampling the *online* variant tier — S1's second option — needs the async job queue and is
tracked in [ROADMAP.md](ROADMAP.md#next-registry-version-post-011).

### The deployment mode is now observable, and assertable (S3)

`REGISTRY_MODE` governs every irreversible decision on the box, and nothing over the wire reported
it. A client could only infer it from a hostname or by testing whether the polygon's `DELETE` routes
happened to be mounted — inferring a deployment's identity from the shape of its route table.

- **`mode` on `GET /health` and `GET /api/v1/version`.** One additive field on each; old clients
  ignore it. Both, because they serve different callers: `/health` needs no token and is what an
  operator or a proxy check curls, `/api/v1/version` is what the SDK already fetches for its
  contract guard. A test asserts the advertised mode agrees with which routes are mounted — a field
  that could disagree with the route table would be worse than the probe it replaces.
- **`RegistryClient(..., expect_mode="test"|"prod")`** raises `ModeMismatchError` before the first
  call that could spend anything, on the same six methods the contract guard already covers (publish,
  import, download, validate, check, is_published). It checks what the *server* says, never the
  hostname. Independent of `check_version`: someone who silenced the contract check has not thereby
  agreed to publish on an unidentified instance. **A server that reports no mode fails the check** —
  asking for verification and getting silence is not a pass, and that direction's remedy is a server
  upgrade, while the other's is an irreversible publish.
- The receipt half of S3's option 3 (the publish response naming the instance that stamped it) is
  **not** in: the publish response *is* the manifest, so it needs either a format field or the
  response-envelope change already queued in [ROADMAP.md](ROADMAP.md). Left for that work.

### `/health` reports enough to run a deployment from (S4)

Filed by the operator on bringing the polygon up, and the timing is the argument: with both instances
live they answered **byte-identical** payloads — `{"status":"ok","version":"0.12.0","storage":"local"}`
from production and from the polygon alike. Three fields, none of them the one that decides whether a
publish can be undone.

- **`mode`, `uptime_seconds`, `enrichment` and `catalog`** alongside the existing fields.
  `enrichment` is the gate — `{active, queued, limit}` — so `503 enrichment_busy` is explicable from
  outside instead of mysterious. `catalog` is `{modules, versions, yanked, namespaces}`, four indexed
  `COUNT(*)`s. `uptime_seconds` is monotonic, so it survives an NTP step.
- **Only publicly enumerable facts.** `/health` takes no token, so account and API-key counts are
  deliberately absent and should stay absent — everything reported here is already reachable through
  the listing routes. `versions` includes yanked ones with `yanked` beside it rather than subtracted
  out, because "how many are hidden" is its own question.
- **A sick catalog degrades the response instead of failing it**: `status: "degraded"`, `catalog:
  null`, and `degraded_reason` naming the exception type. A liveness probe that 500s on a database
  hiccup tells a balancer to pull a process that is still serving every read it has, and withholds
  the diagnosis at the moment it is most wanted. Probe on the HTTP status; read `status` to decide
  whether to page someone.

### The client surface is legible without reading the release (S2)

A consumer calling eight methods against a 35-endpoint API could only answer "did this release touch
anything I call?" by reading the release or diffing the client — which for 0.9.1 → 0.12.0 cost them
a full read to conclude nothing had moved. Verified here: none of those eight signatures has changed
since the 0.9.0 rename.

- **A `Client surface:` line per release**, at the top of the entry — *unchanged*, or the methods
  whose signatures moved. A new method counts as unchanged: it breaks nobody. The convention is
  recorded in [CLAUDE.md](../CLAUDE.md) so it cannot quietly lapse.
- **Both reference docs are stamped** with the version range they are normative for. An unstamped
  schema is what made a consumer write defensive code (`pick("version", "latest_version")`, tolerating
  an `identity` key that does not exist) against a `ModuleCard` we had specified exactly.
- **`module-marketplace.just-dna.life` is purged from the docs** in favour of
  `module-registry.just-dna.life`, including from 0.12.0's own entry above, which named it as
  production and sent a consumer looking for a third deployment. The retired names are now listed in
  [CLAUDE.md](../CLAUDE.md) rather than merely deleted — a purge with no record is how a dead name
  comes back. `compiled_by="marketplace-server"` is untouched and stays: it is baked into every
  published manifest and clients verify against that literal.

### Fixed

- **`REGISTRY_MODE` leaked out of `tests/test_modes.py`** into every test module that ran after it,
  because a `finally` used `monkeypatch.delenv` to undo an env var `cli.serve` had set behind
  monkeypatch's back — so teardown *restored* it. Every later test therefore built its app on
  polygon defaults, silently arming the delete routes on the fixture that documents itself as a
  production instance. Found by asserting `/health` reports `prod` there.

## [0.12.0] — 2026-08-11

Two deployments of one image: **production** (`module-registry.just-dna.life`) and the **polygon**
(`module-polygon.just-dna.life`, `REGISTRY_MODE=test`). Plus the ops safety net that makes cleaning up
after a test survivable.

### Why a mode exists at all

A published `(namespace, name, version)` is immutable, and its authored data is claimed by a
name-independent `content_hash` that **`yank` does not release**. Measured, not assumed: publish to a
sandbox namespace → publish the same data for real → `409 duplicate_content`; yank the sandbox copy →
still `409`; hard-purge it → `201`. So on a single instance every rehearsal permanently burns both a
version number and the right to publish that data under any other name. That is the burner-test trap,
and it is why a test subtree in production is not a workable answer.

- **`REGISTRY_MODE`** = `prod` (default) | `test`. An unknown value **refuses to boot** — falling back
  either way is invisible from a running server, and one direction arms a delete endpoint on production.
- **`registry serve --mode prod|test`** as a convenience over the env var. It works by *exporting*
  `REGISTRY_MODE`, because uvicorn imports the app in the worker — under `--reload` a separate process —
  where it builds its own settings from the environment; handing a value to a `Settings` object in the
  CLI would configure the CLI and nothing that serves a request. Omitting the flag leaves an operator's
  existing `REGISTRY_MODE` untouched.
- **Default port follows the mode**: prod 8000, polygon 8100. A hundred apart so a misdirected client
  gets a connection refusal instead of the wrong catalog answering on a plausible port.
- **Production refuses test data** at both doors: publishing into a `test-`prefixed namespace, publishing
  a `test_`prefixed module name, and *claiming* such a namespace (`422 test_data_on_prod`). Blocking only
  the publish would leave the name claimed and the caller's quota spent on a dead namespace. `issue-key`
  refuses it too — the CLI is the other way into the same table.
- **Two spellings, one flag.** Namespaces and account handles allow hyphens; a module name is validated
  `lowercase alphanumeric with underscores`, so `test-panel` is a `422` at publish and can never exist.
  The prefix is normalised per identifier (`purge.module_name_prefix`) rather than configured twice.
- **The polygon scopes `duplicate_content` to the publisher.** A shared test box has several people
  rehearsing overlapping data, and blocking on someone else's rehearsal is noise. Within-account is kept
  so the gate is still exercised. This is one contract with two behaviours, so a polygon run cannot prove
  a *cross-account* duplicate would be refused in production — that stays covered by unit tests.
- **`DELETE` on a module/version, polygon only.** Authenticated and namespace-scoped (the box answers on
  public DNS, so "open" means available, not unauthenticated). Frees the version number *and* the content
  claim. Production refuses it at the router with `405` — the paths exist for GET/POST, so "method not
  allowed" is the accurate answer, and there is no handler to authorize.
- **SDK**: `RegistryClient.delete_version()` / `.delete_module()`, always present and mode-free — a
  client cannot know a host's mode before asking, so the limitation lives in the docstring instead.

### Rolling backups, and a purge that reports before it removes

- **`registry backup`** snapshots the catalog DB via SQLite's online-backup API (atomic against a live
  writer). Filenames are `registry-00001-<utc>-<reason>.db`: a **rolling index that only counts up and
  never overwrites**. Not a ring buffer — snapshot 3 is still snapshot 3 after snapshot 8 exists, and
  deleting a middle one does not let the number be reused. They accumulate on purpose; pruning is a
  separate, explicit act. `list-backups`, `restore-backup` (which snapshots what it replaces first).
- **Automatic pre-flight snapshot** on every destructive op — `reset-db`, `remove-module`,
  `remove-version`, `remove-namespace`, `purge-test-data` — taken after the confirmation and before the
  first mutation. `--no-backup` / `REGISTRY_AUTO_BACKUP=false` is honoured but *announced*.
- **`registry purge-test-data`**, dry run by default. Removes test accounts, namespaces, modules and the
  orphans under them, in an order that respects the foreign keys.
- **A prefix-matching module in a *production* namespace is reported and skipped** unless
  `--include-prod-namespaces`. It may be a real published module with users; its name matching is not
  consent to delete it.
- **A production version authored by a purged account is kept and only disowned** (`published_by` →
  `NULL`). The three options were: delete the module (catastrophic), fail the purge (a test account that
  ever published to prod could never be removed), or keep the module. The third, reported in the plan.
- **An empty prefix matches nothing**, guarded in the repository, the planner and the CLI. That is the one
  bug that would make this command indistinguishable from `reset-db` on a live box.
- New `delete_account` handles what a naive delete could not: `PRAGMA foreign_keys = ON` and six tables
  reference `accounts(id)` with only `reviews` cascading, so the order *is* the function.

### Also

- **The parity guard now enumerates both modes.** It compared a production app's routes, so the polygon's
  `DELETE` endpoints would have shipped unwrapped with the gate passing — exactly the drift that blocked
  webui publishing in 0.8.1. It also asserts the polygon's route set is a strict superset, so a mode can
  never hide an endpoint.
- **Scope note**: `purge-test-data` does not become redundant now that production refuses test data. The
  guard is prospective only; everything published before it existed, or while a box was still a polygon,
  still has to be swept.

## [0.11.3] — 2026-08-11

Adopts `just-dna-compiler` / `just-dna-enricher` **0.5.3**. `just-dna-format` stays at **0.5.0**.
Digest-neutral upstream (all eleven reference examples recompile byte-identical), so no republish —
but this release **does change a stored facet**, and ships a migration for it.

### A module that joins to no VCF is no longer advertised as trusted

Compiler 0.5.3 reports what a VCF cannot join: resolution is scoped to `variants.csv`, so an
rsid-authored PGx or heteroplasmy table compiles clean, validates, publishes — and has a null
`chrom`/`start` on every row, matching nothing. That finding exposed a defect on our side.

`is_trusted` read `resolution_mode == "strict" or fully_resolved`. For a module with no
`variants.csv`, `fully_resolved` is `all()` over an empty list — vacuously `True` — so the disjunction
granted trust on an empty quantifier. Measured on the format's own reference examples:
`pgx_slco1b1_simvastatin` (9 of 9 rows unplaced) and `cyp2c19_star_alleles` (106 of 106 `haplotypes.csv`
rows carrying a `start` with no `chrom` — CPIC puts the position on `sequence_location` and the
chromosome on `gene`, so there is no `chrom` column at all). Both were served under the fully-baked
facet while annotating nothing.

- **`trusted` is now three-valued in earnest.** `false` when the compiler reported any positional
  table that joins by rsID only — checked *before* the mode, since `resolution_mode` and
  `fully_resolved` both describe `variants.csv` alone and a module can resolve its SNP core perfectly
  while shipping an unjoinable `haplotypes.csv`. `null` when nothing was ever resolved and no warning
  was raised (a coordinate-authored PGx module is probably fine, and "probably" is not a verdict).
  `true` otherwise, unchanged.
- **Not blame.** rsid-only identity is legal by the format's own models, and 0.5.3 keeps it a warning
  in both modes on purpose. The facet answers "can a consumer use this", and for the unjoinable part
  the answer is no.
- **Migration, not a republish.** The manifests are correct and immutable; only our reading of them
  moved. `_migrate_0_11_3_trust` re-projects `trusted` for exactly the two affected populations, with
  predicates that stop matching once fixed (idempotent without a marker table). `fully_resolved` is
  left as the compiler stamped it — this reinterprets, it never edits.
- **Prose-coupled, deliberately and visibly.** The verdict keys off the compiler's warning text,
  because the manifest carries no structured record of which checks ran — the thing we asked upstream
  for as S8 (tracked there as RM43). A test compiles a real spec through the real compiler and asserts
  the marker still matches, so a reword breaks the build rather than silently re-granting trust.

### The enrichment cost guard was blind to the module family that needed it

`enrich_max_variants` counted `validation.stats.variant_count` — `variants.csv` and nothing else. The
enricher has collected subjects from the PGx tables since 0.5 and from `heteroplasmy.csv` since 0.5.3,
so a PGx module reported **0** subjects to a guard that then let every row through. Verified on
`pgx_slco1b1_simvastatin`: `variant_count` absent, nine subjects.

- `SpecStats.table_rows` now carries the compiler's per-table row counts, and
  `enrichment_subject_count()` sums `variants.csv` plus each table the enricher actually asks about.
- An upper bound on purpose: the enricher de-duplicates by `variant_key`, so a locus named in three
  tables is counted three times and asked once. Over-counting costs a publisher a `422` they can
  argue with; under-counting costs the deployment the rate limit it cannot buy back.
- The `422 too_many_variants` message now says "enrichment subject(s)" rather than "variants".

### Also

- **Free from upstream**: `heteroplasmy.csv` joined the enricher's subject list, so such a module
  resolves at all now (previously it enriched to nothing, and 0.5.3's new warning would have named a
  gap no tool could close).
- Incidental transitive bumps came with the lock refresh: **starlette 1.4.1 → 1.6.0**, platformdirs
  4.11.0 → 4.11.2, typing-inspection 0.4.2 → 0.4.3. Full suite green on all of them.

## [0.11.2] — 2026-08-10

Adopts `just-dna-compiler` / `just-dna-enricher` **0.5.2**. `just-dna-format` stays at **0.5.0**:
like 0.5.1, this was a two-package network-tier release that touched no model, parquet column or
manifest field, which is what makes it patch-legal inside the closed 0.5 digest window. Nothing about
a published artifact's identity changes, so no republish and no reindex.

### An empty `clin_sig_conflicts` now says which empty it is

`clin_sig_conflicts: []` meant two opposite things — "compared everything, nothing disagreed" and
"never compared" — rendered identically, with `would_publish: true` beside them. A deployment with no
ClinVar snapshot, or with `REGISTRY_ENRICH_VERIFY_CLINSIG=false`, was reporting a clean cross-check it
had never run.

- **`enrichment.clin_sig_not_checked`** on `/check`: `null` when the check ran, else `not_requested`,
  `no_snapshot`, or the enricher's prose for a module that declares it was drafted from the very
  snapshot the check reads (making the comparison a value against itself, and its zero structurally
  guaranteed). Structured, because a CI job needs a token to compare rather than a sentence to match.
- **The same reason in prose** on `enrichment.notes`, and on a failed publish's `warnings` — rendered
  from one helper beside the conflicts it qualifies, so the two can never diverge.
- **`not_requested` is reported here although the enricher's own CLI suppresses it.** There it is the
  author's `--no-verify-clinsig` echoed back; here it is a server setting the publisher cannot see.
- Never counts against `would_publish`, and must not start to: a check the *operator* disabled or has
  no snapshot for is not a defect in the module.

### What came for free from 0.5.2

- **The ClinVar panels are publishable in bounded time.** A batch coordinate lookup was
  `(chrom=? AND start=? AND ref=? AND alt=?) OR …`, which DuckDB cannot fold into a hash probe, so it
  scanned every row per allele — upstream measured a 297-gene panel at two hours and 12% CPU, which
  reads as a deadlock, against 0.21s for the temp-table join that replaced it. This is the tier the
  publish path's threadpool worker and `enrich_timeout_seconds` were sized against.
- **The tautology skip is where most of that check's cost was**: upstream measured 27.1s → 2.6s on a
  7,818-row provider-drafted panel, for a zero that was never evidence.
- `--no-resolve` with a `resolution.csv` present now warns instead of succeeding with no coordinate on
  any row. The registry always passes `resolve_with_ensembl=True`, so this cannot fire here; the floor
  is 0.5.2 anyway, since it is the only compiler-side change this tier could observe.
- `_cache_dir` loads `.env` itself, fixing a first-resolve-in-the-process asymmetry the registry was
  structurally immune to (`config.py` loads `.env` at import). `available_references` passes
  `load_dotenv_file=False`, which no longer covers the whole ladder; the docstring now says so rather
  than claiming a suppression that is no longer complete.

## [0.11.1] — 2026-08-10

### The dry runs now accept what the publish accepts

`POST /versions/import` has always taken a compressed spec archive; `/validate` and `/check` took
only loose multipart parts. Since `max_upload_bytes` bounds the bytes on the wire, that split meant
a large module could be **published but never rehearsed**: the three ClinVar panels are 34–180 MiB
authored, so the raw form is a `413` on every route, and the compressed form existed on exactly the
routes that write. A dry run that cannot accept the input the publish accepts predicts nothing.

- **Both pre-flight routes take `archive=`** (`.tar.gz` / `.zip`), resolved through the same guarded
  extraction the import route uses, including a nested module root so `tar czf spec.tar.gz spec/`
  works. Sending `files=` and `archive=` together is `422 ambiguous_upload`.
- **SDK + CLI**: `RegistryClient.validate(…, pack=True)` / `.check(…, pack=True)` compress a spec
  directory client-side, and either method accepts a path that already *is* an archive.
  `registry-client validate|check … --pack` is the same thing from the shell. Packing reuses
  `gather_spec_files`, so compiled parquets and `manifest.json` are still never uploaded.
- **Measured, not asserted**: packed, the panels are 2.2 MB (cancer), 1.8 MB (cardio) and 10.2 MB
  (pathogenic) — all comfortably inside the unchanged 25 MiB bound.

**`max_upload_bytes` stays at 25 MiB, and that is the point.** It mirrors the HAProxy request-body
cap in front of the deployment, so the registry answers an oversized body with its own structured
`413 upload_too_large` rather than letting the proxy cut the connection with something no client can
parse. Raising it does not raise the real ceiling — it moves the failure upstream and makes it
opaque. The proxy's limit is the constraint; the archive form is how a 180 MiB spec gets under it.

### Archive expansion is bounded (was: not at all)

0.11 added `max_upload_bytes` and checked it against an archive's *compressed* size, then extracted
whatever that became. Compression ratio is unbounded, so the archive route was the one path where a
25 MiB body could write arbitrarily much to disk — and widening it to two more routes without a
bound would have made that worse.

- New `max_extracted_bytes` (default **512 MiB**), summed from zip/tar member headers **before** any
  file is written, so a refusal leaves nothing behind. Over it → `413 archive_too_large`.
- Deliberately a separate knob from `max_upload_bytes`: reusing the transfer bound would have closed
  the hole by breaking the one route the large panels publish through (180 MiB extracted).

## [0.11.0] — 2026-08-08

Adopts `just-dna-format` **0.5.0** plus `just-dna-compiler` / `just-dna-enricher` **0.5.1**, and with
them the network tier the format grew in this release.

### Adopts 0.5.1 — the gated sources get a cache, and four workarounds are deleted

0.5.1 is a two-package network-tier patch (format stays at 0.5.0, since nothing in it touches a
model, a parquet or a manifest field). It answers the four RMs this repo filed during the 0.5 seam
audit, and adds the cache that makes a *hosted* `?pgx=` check legitimate rather than merely possible.

- **`?pgx=` is snapshot-first for every source (RM38).** PharmVar and CPIC were live-only, so the
  endpoint's real options were to fetch a source that forbids sale live, per request, on the
  operator's own acceptance and *personal* PharmVar key, or to skip. Both published rate figures are
  per IP, so a server multiplies its callers onto one allowance. Each leg is now snapshot → live →
  skipped-with-a-reason, `offline` means snapshot-only rather than "PGx is off", and
  `PgxCheck.routes` records which route answered, because a pinned file and a live API can differ by
  a release. New settings `REGISTRY_CPIC_CACHE` / `REGISTRY_PHARMVAR_CACHE`; **`REGISTRY_CLINPGX_SNAPSHOT`
  is renamed `REGISTRY_CLINPGX_CACHE`** for symmetry with the other five (free to rename — 0.11 is
  unreleased).
- **PharmVar no longer needs a key when a snapshot is present**, which is the configuration a public
  deployment wants: that key is non-transferable under PharmVar's terms §2, so serving third parties
  on it is the thing to avoid. It is also the one cache nothing publishes — the bulk data comes down
  under that same key — so `warm-caches` reports it as build-it-yourself rather than as a failure.
- **`registry warm-caches` covers all six snapshots**, in two groups, because they gate different
  things: resolution decides whether a *publish* works, PGx decides whether the *check* does. Only
  the resolution three are behind `enrich_require_cache` and the boot warning; folding the PGx ones in
  would have made a hosted PGx snapshot a condition of starting the server. `--pgx` opts in, and
  `--use` gates the two licence-gated pulls, because downloading is *taking* the data.
- **`src/just_dna_registry/retries.py` is deleted (RM42).** It walked the enricher's package at boot
  and assigned `policy.stop` on tenacity's objects. The floor is now
  `JUST_DNA_HTTP_RETRY_ATTEMPTS`, exported beside the other credentials and read per call — still a
  floor, so gnomAD and eutils keep their higher own defaults. `REGISTRY_HTTP_RETRY_ATTEMPTS` is
  unchanged for operators.
- **VRS coverage is the enricher's, not a recount (RM40).** `EnrichmentResult.vrs` carries the
  `MintResult` `enrich()` always computed and used to drop, so `services/enrich.py` no longer
  re-implements per-ALT slot counting — and cannot disagree with the manifest a publish stamps, which
  a new test asserts by doing both to one spec. It also brings `unmintable_reasons`, previously
  reachable only as a log line: surfaced on `VrsCoverage`, because "no refget table for GRCh37" is
  the tier's limit and a publisher shown only a shortfall would hunt for a mistake that is not theirs.
- **The ACMG check hands over a directory (RM41).** `verify_acmg_sf(spec_dir=…)` replaces loading
  `variants.csv` here through the compiler's *private* `_load_csv_rows` — which is now public as
  `load_csv_rows`, alongside `load_spec_variants`. The registry holds no copy of the empty-cell and
  build-injection rules, and in fact gained the second one: the hand-rolled call never re-stamped for
  a non-GRCh38 module.
- **The ClinGen dosage guard is gone (RM39).** It was the one pass with no `offline` parameter, so
  this file hoisted an `if not offline:` around it; it now takes the flag and reports
  `skipped_offline` itself.

### Changed
- **Publish is now enrich → compile strict, as two steps.** The enricher resolves rsIDs and writes
  `resolution.csv`; the compiler then consumes that file and never fetches for itself. This is the
  shape the format's constitution intends — what it forbids is the *compile path* importing the
  network tier, which is exactly what `compile_module(ensembl_cache=…)` does, so that parameter is
  gone from the registry entirely (it is deprecated upstream for removal at 1.0).
  **This is a breaking change for publishers.** `strict` refuses to emit a partial artifact when a
  variant is left without a genomic position, so an rsID-authored module that published on 0.4 now
  fails with `422 compile_failed` unless the server has a reference snapshot. That is the point —
  it is what makes `compiled_by=marketplace-server` worth trusting — but see the migration note.
- **`Settings.resolve_with_ensembl` is gone**, replaced by `compile_strict` + the `enrich_*` block.
  In 0.5 that flag gated the entire resolution path rather than just network lookups, so leaving it
  at its old default would have made the whole adoption a silent no-op. A stale
  `REGISTRY_RESOLVE_WITH_ENSEMBL` in a deployment's `.env` now logs a warning at boot rather than
  being swallowed.
- **`module.version` is no longer stripped.** 0.4 made the `module:` block `extra="forbid"` and the
  registry dropped the key to keep the pre-0.4 corpus importable; 0.5 turned it back into a real
  advisory field, so it is now *normalized* instead — an unquoted YAML integer (`version: 3`, which
  the entire legacy corpus has) is quoted, and the format coerces it to SemVer while recording the
  original. The registry still stamps `Identity.version`, which always wins.
- **Adopted the compiler's canonical `content_signature`** in place of the registry's own
  manifest-inputs Merkle root. It hashes the authored rows *as parsed* — `defaults:` folded in, the
  declared build included — so it survives a reformat, a row reorder, and a recompile against a
  different reference. `src/just_dna_registry/content.py` is deleted.
- **The SDK's new methods return Pydantic models rather than dicts.** The direction of travel for
  the rest of the client.

### Added
- **`POST /modules/{ns}/{name}/validate`** — validate a spec server-side without publishing. Returns
  findings, stats, the content signature, and any versions already built from identical data. A
  finding is a `200`, not a `422`.
- **`POST /modules/{ns}/{name}/check`** — the full publish dry run, including the network-tier checks
  (reference allele, `clin_sig` vs ClinVar, rsID currency, VRS coverage, optional gnomAD frequencies
  / literature / ACMG). Returns `would_publish`. Rate-limited hard and backed by a process-wide
  concurrency gate: the upstreams are unauthenticated and throttle by IP, so an overspend penalises
  the deployment rather than the caller, and gnomAD offers no key to raise the ceiling.
- **`?pgx=` on `/check`** — authored `function_status` against PharmVar, CPIC, ClinPGx and ClinGen
  dosage, plus **`?declared_use=`** (and `REGISTRY_DECLARED_USE`) gating all four. Every PGx upstream
  forbids sale, so on the default `unstated` each is skipped with a reason rather than queried;
  `commercial` is refused at acquisition with `422 license_refused`. PharmVar has no separate switch —
  the presence of `PHARMVAR_API_KEY` is the switch, so it cannot disagree with reality.
- **Content-signature lookup** on `GET`/`POST /modules/lookup` (`?signature=`), so a publisher can
  pre-check dedup *before* uploading. Requested by the format in `PROPOSAL_0_4_1.md`.
- **Trust and licensing facets** on cards and versions: `resolution` (mode, `fully_resolved`,
  `trusted`, VRS coverage) and `licensing` (tri-state `commercial_use`/`redistribution`, per-layer
  share-alike lists). `trusted` is deliberately nullable — `null` means the version predates the 0.5
  contract, which is not the same as untrustworthy.
- **`registry warm-caches`** — provision the reference snapshots enrichment needs. Dry-run doubles as
  a health check.
- **`registry rederive-signatures`** — the one-time content-signature migration, with a split/merge
  collision report and a refusal to apply a merge without `--allow-merges`.
- **`registry revalidate --strict-check` / `--recompile-check`** and a new `strict_blocked` status,
  so an operator can measure what a strict flip would cost *before* flipping it.
- **`registry upgrade --limit`**, and automatic detection of versions that predate the 0.5 contract
  (so the catalog migration is `--apply` rather than a `--force` people forget).
- **SDK**: `content_signature`, `is_published`, `lookup_by_signature(s)`, `validate`, `check` — plus
  `health()` and `issue_jwt_token()`, closing the two endpoints that had no client method.
- **CLI**: `registry-client validate` / `check` / `signature`. Note `signature --lookup` inverts
  `find-by-hash`'s exit code: it is a pre-publish gate, so a match is the failure.

### Fixed
- **The SDK dropped `genome_build` on import.** `import_module`'s `display` dict was filtered
  through a hardcoded five-key tuple, so the one form field that is *inside* `artifact.digest` never
  left the client: an SDK import of a bare GRCh37 archive was reversed as the GRCh38 default, minting
  `variant_key`s against the wrong assembly. Nothing downstream catches it — the recompile is
  internally consistent and `verify_manifest` re-derives the same wrong digest. `registry-client
  import-module --genome-build` too. The raw-HTTP path had been correct and tested since 0.11; only
  the wrapper was short, which is the half the webui and CLI call.
- **`versions()` could only ever see the first page.** The endpoint is paged server-side and the
  wrapper sent neither `page` nor `per_page`.
- **`list_modules(**filters)` is now fully named and keyword-only.** A server ignores a query param
  it does not know, so a misspelled facet was not an error — it came back as a *wider* result set
  that looks like a working search. `registry-client list` grew the filters it was missing
  (`--genome-build`, `--namespace`, `--owner`, `--license`, `--featured`) and paging.
- **SDK↔API parity is now asserted structurally**, not left to review: `test_client_sdk.py` compares
  the OpenAPI surface against a table of wrapping client methods, so a new route fails the suite by
  name. It also checks that every pre-flight query flag is spellable from both the SDK and the CLI —
  the drift that recurs, since each new enrichment pass adds one and a flag the client cannot send
  reads as a clean report on a question nobody asked.
- **Authenticated path traversal on the multipart publish path.** `spec_dir / filename` was written
  with no containment check, while the archive path had been guarded since it was written — so a part
  named `../../../x` escaped the temp directory. All four upload routes now share one bounded,
  containment-checked reader.
- **No upload bounds existed.** Added `max_upload_bytes` (25 MiB) and `max_spec_files` (64), checked
  from the spooled part sizes *before* anything is read.
- **Every JWT caller shared one rate-limit bucket.** `_rate_identity` keyed on the bearer's first 16
  characters, and every HS256 token begins `eyJhbGciOiJIUzI1`. Now keyed on the resolved account.
- **PGx-only modules could not be published, revalidated, or upgraded.** Three services hardcoded a
  `(module_spec.yaml, variants.csv, studies.csv)` triple that has been incomplete since format 0.3.
  Composition is the compiler's rule now; `specfiles.py` is the single recognized-file set.
- **Upgrade silently dropped every 0.5 sidecar.** It carried `manifest.inputs`, which by construction
  excludes `resolution.csv` and the fact tables — losing licence facts and, with them, the resolution
  table a strict recompile needs.
- **Two modules differing only in `defaults.curator` hashed equal** (RM37), so a genuinely distinct
  module could be refused as a duplicate. Fixed by the canonical signature.

#### From the 0.5 seam audit

A pass over every call into `just-dna-format` / `just-dna-compiler` / `just-dna-enricher`, against
those packages' own docs and their live signatures. Six findings, all in this repo.

- **`?frequencies=`, `?literature=` and `?acmg=` on `/check` raised `NameError`.** The router exposed
  all three; the functions they dispatch to did not exist anywhere in the package. Nothing caught it
  because no test had ever passed the flags — so they are now implemented, and each has one.
- **Every optional pass built its own enricher clients.** The outbound pacing that holds us inside
  gnomAD's 10-per-60s and NCBI's 3-per-second budgets lives *on the client object*, so a frequency
  pass with a fresh `GnomadClient` started its interval from zero and doubled the rate the resolution
  chain in the same request had just been paced at. All passes now take the shared bundle.
- **The publish path did neither.** It built fresh clients *and* took no concurrency permit, so on a
  deployment with `REGISTRY_ENRICH_OFFLINE=false` two concurrent publishes egressed at twice the
  intended rate against an IP-scoped budget with no key to raise it. Publish now shares the bundle
  and takes a permit from the same gate `/check` uses — but only when it will actually reach the
  network, since serializing an offline publish behind a limit of 1 would buy nothing.
- **An offline `?pgx=` skipped ClinPGx**, on the reading that the whole PGx family is online-only.
  That is true of PharmVar, CPIC and ClinGen and false of ClinPGx, which is snapshot-based and takes
  no `offline` argument at all — so a deployment with a snapshot built was skipping a check it could
  have completed with zero egress.
- **A legacy GRCh37 archive imported as GRCh38.** `genome_build` reaches a compiled module through
  `manifest.json` and no parquet column, so a bare parquet archive reverses to the format's default —
  and the build decides the identity key, so the recompile minted `ga4gh:VA.…` ids naming a base the
  module never carried, with a moved digest and nothing downstream able to notice. `import` takes a
  `genome_build` form field; the manifest still wins when the archive has one.
- **`?declared_use=` was passed through unvalidated**, so `non-commercial` — the enricher CLI's own
  hyphenated spelling — reached a gate whose entire job is that an undeclared purpose means *do not
  fetch*. Now `422 invalid_declared_use`.

Four upstream API asymmetries the same audit surfaced were filed as RM39–RM42 in
`just-dna-format`'s `docs/PROPOSAL_0_5_1.md`. **All four shipped in `just-dna-enricher` /
`just-dna-compiler` 0.5.1, and the workarounds are gone** — see *Adopts 0.5.1* below.

#### Publish became the idle lane

Following from the audit, and a behaviour change worth reading before deploying with
`REGISTRY_ENRICH_OFFLINE=false`.

- **Publish queues for an enrichment permit instead of failing on a full gate, with no deadline.**
  A dry run has someone waiting on the answer, so a full gate stays a fast `503`; a publish has
  nobody waiting and an upload already spent, and `503` there means re-uploading a module over a
  condition that clears in seconds. Publish is correspondingly exempt from
  `enrich_timeout_seconds` and `enrich_max_variants` — both were always `/check`-only bounds, and
  the variant cap is really about the frequency pass, which publish never runs. **Raise your client
  and reverse-proxy timeouts to match.**
- **A queued publish holds no threadpool worker.** It waits in the coroutine, so a backlog cannot
  starve the fixed pool that `/check` and every other blocking handler need in order to run. This
  is the concession that actually bites; the rest are scheduling hints.
- **A running publish gets its own niced thread**, discarded afterwards, rather than a shared
  worker. It has to be disposable: raising a thread's nice value is unprivileged and *lowering it
  back is not*, so a pooled worker niced once could never be restored and would hand the penalty to
  whichever request it served next — quite possibly the `/check` this exists to protect.
  `REGISTRY_PUBLISH_NICE` (default 10), `REGISTRY_ENRICH_IDLE_QUIET_SECONDS` (default 5).
- **Deference is at entry only, and the docs say so.** Once a publish is enriching it keeps the
  permit until it finishes and a concurrent `/check` still gets `503`. Nothing can preempt it —
  `enrich()` is one opaque call and Python cannot interrupt a thread. Real preemption needs a job
  queue with a broker, which is the horizontal-scaling answer rather than this one.
- **The enricher's outbound retry ceiling is raised to 5 attempts at boot**
  (`REGISTRY_HTTP_RETRY_ATTEMPTS`). It already retried — tenacity, exponential jitter, paced
  *before* the retry so an extra attempt spends a budget slot rather than bursting past it — but at
  `stop_after_attempt(3..4)` baked into import-time decorators, tuned for an author at a terminal
  who would rather see the failure than wait. Unattended server work wants the opposite. Raised
  only, never lowered, and the nine clients are **discovered** rather than listed, so one added
  upstream is covered; a test asserts the walk still finds them all.

### Migration
Run both, in order, in the same maintenance window:

1. `registry warm-caches --apply` — publish now *requires* enrichment. A server with no snapshot
   cannot publish an rsID-authored module at all.
2. `registry rederive-signatures --apply` — until this runs, pre-0.5 versions carry an empty
   signature and drop out of the dedup gate (safe, but incomplete).

Then, before enabling strict: `registry revalidate --recompile-check` reports which existing modules
a strict flip would stop accepting. `REGISTRY_COMPILE_STRICT=false` is the escape hatch while you
work through them.

**Bump clients to 0.5 first.** The version guard already treats a 0.x minor as a breaking contract
change, so a 0.4 client against a 0.5 server is refused — and the first symptom otherwise is a
blanket publish rejection with no obvious cause. Note also that 0.5 re-baselined `variant_key` onto
the VRS allele identity, so every recompiled module gets a new `artifact.digest`. Predecessors stay
published and verifiable; a pinned client is unaffected.

## [0.10.0] — 2026-07-15

### Changed
- **Adopted `just-dna-format` / `just-dna-compiler` 0.4** (pins `>=0.4.0`). 0.4 is a contract minor —
  the parquet schema and `artifact.digest` move — so the version-mismatch guard now requires client
  and server to both run `0.4` (mixed 0.3/0.4 pairs are rejected with an actionable message). New
  authored columns and the frozen `variant_key` flow through the server recompile automatically.

### Added
- **Structured per-version `authorship`** (format RM14) rides the manifest end to end: a
  `module_spec.yaml` `authorship:` block is recorded into the manifest (out of `artifact.digest`) and
  surfaces on the detail endpoint's inline `latest_manifest`, so consumers can route scrutiny by
  author-kind. No DB or API-model change — it flows through the whole-manifest projection.
- **`strip_registry_owned_keys`** on the server compile path. 0.4 made the `module:` block
  `extra="forbid"`, which rejects the registry-owned `module.version` (and `namespace`/`owner`/
  `canonical_id`) that every pre-0.4 spec archive carried. The server drops that set from the authored
  block before validate/compile on **publish, import, and upgrade**, and before the `revalidate` drift
  check — so importing/upgrading the pre-0.4 corpus keeps working and a legacy `module.version` alone
  is not misread as un-fixable drift. Byte-preserving on a clean spec; kept permanently.

- **Cross-name content dedup on publish** (`409 duplicate_content`). Publish/import now rejects a
  spec whose data is already published under a *different* `(namespace, name)`, so the same module
  can't be re-listed under another name. It keys on a name-independent signature over the data inputs
  (`variants.csv`/`studies.csv` hashes, excluding `module_spec.yaml`) — `artifact.digest` can't gate
  this because the module name is baked into the compiled parquets, so a rename yields a different
  digest. A collision under the *same* module (a later version with unchanged data) is still allowed.
  New `versions.content_hash` column (backfilled from stored manifests on migration) +
  `Repository.find_versions_by_content`.

- **`registry upgrade --force` / `--trim`** for migrating the catalog onto the 0.4 parquet shape.
  `--force` (alias `--recompile`) re-emits an already-on-contract module in the current schema even
  with no 0.3 drift (non-lossy). `--trim` drops columns *and* `module_spec.yaml` keys 0.4 now rejects
  (older schemas only warned) so a legacy spec compiles — LOSSY, so it requires `--force`; a version
  with such offenders and no `--trim` is reported *blocked*, never crashing. New
  `prepare_version_upgrade` + `offending_columns`/`trim_unknown_columns` and `offending_yaml_keys`/
  `trim_unknown_yaml_keys` in `services/upgrade.py`. Registry-owned `module:` keys are excluded from
  the trim (the always-on strip handles them).

### Dependencies
- Added `pyyaml` to the `server` extra (the publish path now parses `module_spec.yaml` directly to
  normalize registry-owned keys).

## [0.9.1] — 2026-07-10

### Added
- **`latest` version sentinel** for downloads. `registry-client download <ns> <name> latest <dest>`
  (and `--tarball`) resolves the module's current latest non-yanked version server-side; the SDK's
  `download`/`get_tarball` accept `"latest"` too (via `RegistryClient.resolve_version`).

### Fixed
- **The 0.9 rename silently moved the default DB path** `data/marketplace.db` → `data/registry.db`
  (the rebrand sweep hit the default string in `config.py`), orphaning existing local-backend
  catalogs. **Recovery:** `mv data/marketplace.db data/registry.db` (or set
  `REGISTRY_DB_PATH=data/marketplace.db`). New **startup guard** (`validate_db_path`): the server now
  **refuses to boot** if the configured DB is absent but a non-empty legacy `marketplace.db` sits
  beside it, instead of silently serving an empty catalog — with a message telling you to `mv` or
  set `REGISTRY_DB_PATH`.
- **`export-keys` no longer creates a stray empty DB / crashes with `no such table`.** Read-only ops
  refuse a missing/empty DB with a clear message showing the **resolved absolute path** (and the
  legacy-`marketplace.db` hint when present), before `connect()` can create a stray file; they also
  run the additive migration so a pre-0.9 DB is brought up to schema before reading. `reset-db`
  prints the resolved absolute path in its confirmation. The DB-location knob is `REGISTRY_DB_PATH`
  (documented in `.env.template`).

## [0.9.0] — 2026-07-09

**Renamed `just-dna-marketplace` → `just-dna-registry`.** "Marketplace" implied a paid/commercial
component that doesn't exist; this is a package **registry** (publish/version/install, like
npm/PyPI/Docker), and the app-store-style *one-click-install UI* is the **Store** — a webui concern
(`WEBUI-STORE.md`), not this backend. Hard rename (no compat aliases — nothing hardwired it yet).

### Added
- **Org accounts + fine-grained RBAC.** A `type='org'` account is now a first-class entity with
  members (`org_members`) whose role cascades to every namespace the org owns. Roles are
  hierarchical **owner ⊃ admin ⊃ member** (was owner/contributor), assignable at the org level
  *and* per-namespace; the effective role on a namespace is the highest of the two. Capability model
  (`permissions.py`): member = publish + amend/yank **own**; admin = + amend/yank **any** + manage
  namespaces/members + curate; owner = + assign roles + settings. Gates are now a single live
  `require_capability` resolver. New endpoints: `POST /orgs`, `GET/POST/DELETE /orgs/{org}/members`,
  `PUT /orgs/{org}/members/{m}/role`, `PATCH /orgs/{org}/settings`, `POST /orgs/{org}/namespaces`;
  CLI `create-org` / `{add,remove,list}-org-member` / `set-funding`; client `create_org`,
  `org_members`, `add_org_member`, `set_org_role`, `remove_org_member`, `update_org_settings`,
  `create_org_namespace`.
- **Per-version author tracking** (`versions.published_by`), captured at publish — drives own-scoping
  and the author funding link.
- **Donation / funding links.** `accounts.funding_url` (public http(s)) on both user and org
  accounts; settable via `PATCH /auth/whoami` (+ `issue-key`/`set-funding`) and `PATCH
  /orgs/{org}/settings`. Module cards/detail surface **two** links: `author_funding_url` (the latest
  version's author) and `org_funding_url` (the owning org).
- **Fixed the amend/logo/yank gap:** these said "Owner-only" but only required membership; they are
  now capability-gated (own for a member, any for admin+).
- **Admin ops for keys + reset.** `registry export-keys [-o file]` / `registry import-keys <file>`
  dump/restore the auth graph (accounts + API keys + namespaces + memberships) — for backup or a
  preprod→prod migration (the export holds live tokens; keep it secret). `registry reset-db`
  wipes the catalog (modules/versions/stars/reviews) but **keeps accounts + API keys** by default
  (`--wipe-keys` to clear them too); gated behind a typed **`RESET`** confirmation, and it never
  touches artifact storage. The Ed25519 signing key is a PEM file (`REGISTRY_SIGNING_KEY`), not in
  the DB — copy it directly to reuse across envs; `reset-db` leaves it alone.

### Changed
- **RBAC role rename `contributor` → `member`** (migrated in place). ⚠️ **Tightening:** an old
  contributor could amend/yank *any* version; a `member` is own-only. Re-grant `admin` to preserve
  broad rights. Versions published before 0.9.0 have no recorded author, so only admin+ can
  amend/yank them.
- Package `just-dna-registry`; module `just_dna_registry`; CLIs `registry` / `registry-client`;
  env vars `REGISTRY_*`; client class `RegistryClient` (+ `RegistryError`); version headers
  `X-Registry-*` and the `/version` field `registry`; discovery scheme `registry://`.
- **Consumers must update** (hard rename): the `registry://` source scheme + package/CLI/env names in
  just-dna-lite / discovery, and the live domain (`module-registry.just-dna.life`).
- **Retained deliberately:** the internal trust token `compiled_by="marketplace-server"` (a
  just-dna-format constant enforced by `verify_manifest`) is **unchanged** — it's not user-facing,
  and pivoting it would invalidate every published manifest until re-baked. Retire at the next
  format major cleanup. Server-side Ed25519 signing is unaffected (`REGISTRY_SIGNING_KEY`; the key
  is a PEM file, never hashed/stored in the DB — reuse it across envs to avoid re-signing).

## [0.8.1] — 2026-07-09

### Added
- **Userpic.** Optional `avatar_url` on the account (public http(s) URL) — settable via
  `PATCH /auth/whoami` and `issue-key --avatar-url`, returned by `whoami`. `""` clears it.
- **`RegistryClient` now mirrors the full API** (was the webui-publishing blocker). New methods:
  `whoami` / `update_profile`; `star` / `unstar`; `reviews` / `review` / `delete_review` /
  `highlight_review`; `yank` / `unyank`; `members` / `add_member` / `remove_member`; `groups`; and
  `catalog_stats(namespace=None, group=None)` — client-side aggregation of the card fields, since
  there's no dedicated stats endpoint. Previously these were HTTP-only (raw `client._http`).
- **Test infra:** `pytest-asyncio` (`asyncio_mode = "auto"`); the client SDK suite now drives the
  real app in-process (no stubbed HTTP) via Starlette's ASGI transport, bridging the sync client
  onto a worker thread.

### Fixed
- **Upgrade no longer re-upgrades a superseded version (immutability bug).** `registry upgrade`
  re-publishes a drifted version's spec as a *new* PATCH, but the original is immutable and stays
  drifted — so once `1.0.0` had produced `1.0.1`, every subsequent run minted another patch
  (`1.0.2`, `1.0.3`, …) from the same un-upgraded `1.0.0`, and `revalidate` flagged `1.0.0`
  `upgradable` forever. Now **only a module's latest non-yanked version is upgrade-eligible**: an
  older version masked by a newer one is skipped by `upgrade` and reported as **`superseded`** (not
  `upgradable`/`needs_upgrade`) by `revalidate` (`is_latest_version` in `services/upgrade.py`). A
  future contract that drifts the *latest* still upgrades it once.

## [0.8.0] — 2026-07-09

Listing groups + reviews/audits + account profiles — additive, registry-layer catalog features.
No contract change (pins stay `>=0.3.0`); `just-dna-format` is untouched. New tables/columns are
created idempotently by `init_db`, so a live catalog upgrades in place.

### Added — listing groups
Server-owned namespace grouping behind the webui's tabs. Membership is defined server-side (not in a
consumer) so the webui, the CLI, and any client agree on what each tab contains.
- **`?group=` on `GET /modules`** — `all | featured | curated | popular | new | test`, each a preset
  over the existing primitives: `featured`→`featured=true`, `curated`→has an owner-highlighted review,
  `popular`→`sort=popular`, `new`→`sort=recent`, `all`→everything. A group wins over the equivalent
  raw `sort`/`featured` params.
- **Test/sandbox isolation.** Namespaces matching `REGISTRY_TEST_NAMESPACE_PATTERN` (default
  `^(sandbox|test)([-_]|$)`) are classified `test`: surfaced only under `?group=test` and **hidden
  from every other tab** (including the default listing). A test space stays reachable by exact
  `?namespace=`. The regex is server config, never a client-supplied param (consistency + no ReDoS
  surface).
- **`GET /api/v1/modules/groups`** — discovery endpoint returning `[{key, label, description}]` so a
  UI renders tabs from server truth instead of hardcoding.
- Client CLI: `registry-client list --group <tab>`.

### Added — reviews & audits
A registry-layer social record about a published version. **Not a module feature: the manifest is
untouched** (reviews are mutable social data; the manifest is the immutable, content-addressed
artifact).
- **Open, version-scoped reviews.** `PUT/DELETE /api/v1/modules/{ns}/{name}/versions/{v}/reviews`
  (bearer) — anyone authenticated posts one review per version: a `rating` (1-5) plus an optional
  audit `verdict` (`verified|concerns|rejected`) and `notes`. Re-posting replaces (one per account
  per version). `GET .../reviews` (and `GET /modules/{ns}/{name}/reviews` across versions) list them,
  highlighted first. Anonymous reads.
- **Owner highlight (SO accepted-answer style).** `PUT/DELETE
  .../versions/{v}/reviews/{reviewer}/highlight` — the **namespace owner** highlights the good
  reviews; any number may be highlighted ("the more the merrier"). A highlighted review is the trust
  signal that `?group=curated` and the card `curated` flag key on (and, once a reputation system
  lands, will accrue to the reviewer as demonstrated expertise).
- **Card fields** `review_count`, `avg_rating` (mean 1-5, null when unreviewed), and `curated` (has a
  highlighted review).

### Added — account profiles
The `accounts` row is the single user primitive (auth stays token-based; no separate `users` table).
- **`email`** (private — returned only from `whoami`, unique when set) and **`display_name`** (human
  name, distinct from the `name` handle) columns, plus a GitHub-style **`type`** discriminator
  (`user` | `org`) so one identity primitive can be a person or an organization.
- **`PATCH /api/v1/auth/whoami`** — the account edits its own `email`/`display_name` (omitted fields
  unchanged; `""` clears; duplicate email → `409 email_taken`). `whoami` now returns `type`,
  `display_name`, `email`. `type` is set at creation by the admin CLI, not self-editable.
- `registry issue-key` gains `--email`, `--display-name`, `--type user|org`.

### Note
- Grouping operates over the **module listing** (which modules show per tab). A namespace-browse view
  (list spaces with aggregate stats) was considered and deferred — not needed for the tabbed listing.
- Reviews are **version-scoped**: an audit vouches for specific bytes; a new version starts
  un-highlighted. Editing a review leaves the owner's highlight untouched.

## [0.7.1] — 2026-07-08

Adopts **just-dna-format / just-dna-compiler 0.3.0** (pins bumped to `>=0.3.0`) and adds the
automation and the client/server guard that a contract bump needs. The 0.3 columns are additive and
the server recompiles every spec, so published modules gain them on their next publish with no
migration.

### Added
- **`registry upgrade`** (+ `services/upgrade.py`) — back-populates the additive 0.3 axes
  (`direction`, `stat_significance`, `clin_sig`, and a trimmed `state`) from the legacy
  `state`/ClinVar booleans by applying the format's own `VariantRow.upgraded()` derivation, then
  re-publishes as the next PATCH through the normal server-side compile path. Dry-run by default;
  `--apply` publishes; `-n`/`-m` scope it. The predecessor is never mutated, the transform is
  idempotent, and the logo carries forward (logs/provenance do not — they describe the predecessor).
- **Server/client version-mismatch guard.** The server advertises its versions — `GET
  /api/v1/version` (`{api, registry, format, compiler}`) plus `X-Registry-Version` /
  `X-Format-Version` / `X-API-Version` on **every** response — and the client sends its own as
  request headers. Before publish/import/download the client calls `assert_compatible()` and raises
  `VersionMismatchError` (409) with an actionable message when the API version or the
  `just-dna-format` contract can't interoperate (same MAJOR; and same MINOR while `0.x`, since a 0.x
  minor moves the parquet schema / `artifact.digest` — the 0.2→0.3 case). A differing registry
  *app* version is **not** fatal (the API is path-versioned). Escape hatch
  `REGISTRY_SKIP_VERSION_CHECK=1` (or `RegistryClient(check_version=False)`);
  `registry-client version` prints both sides and the verdict. Logic in `version.py`.

### Changed
- **`revalidate` now reports `ok` / `upgradable` / `needs_upgrade` / `skipped`.** Because the 0.3
  columns are additive, a legacy module still *validates* — the new `upgradable` status flags a
  version whose 0.3 axes can be losslessly back-populated (re-publish with `registry upgrade`),
  distinct from `needs_upgrade` (fails the current validator). `--set-flag` marks both.
- Contract pins `just-dna-format` / `just-dna-compiler` → `>=0.3.0`.
- Coding-standards doc (`CLAUDE.md`): logging policy switched to stdlib `logging` (Eliot is being
  retired); the new `version.py` / `client.py` follow it.

## [0.6.0] — 2026-07-08

Community & discovery features. No `just-dna-format`/`just-dna-compiler` change (pins stay `>=0.2.0`).
All schema changes are additive `ALTER`s / new tables applied idempotently by `init_db`, so an
existing live catalog upgrades in place — a pre-0.6 single-owner namespace is backfilled as an
`owner` membership automatically.

### Added
- **GitHub-style stars.** `PUT`/`DELETE /api/v1/modules/{ns}/{name}/star` (auth) toggle a favourite;
  the stargazer count and the caller's `starred_by_me` appear on the card, and `?sort=stars` ranks
  by count. Idempotent (starring twice keeps one star). A `module_stars` table is the source of
  truth; `modules.stars` is its maintained cache.
- **Namespace membership (owner / contributor).** Namespaces are no longer single-owner. A
  `namespace_members` join table grants access: both roles publish/amend/yank, but only an **owner**
  can add/remove members, promote to owner, or revoke access. `GET/POST/DELETE
  /api/v1/namespaces/{ns}/members` (owner-gated mutations; last owner cannot be removed) and ops
  commands `registry add-member|remove-member|list-members`. Revocation is **namespace-scoped**
  (removes the membership), not a global API-key kill.
- **Popularity.** `modules.views` (bumped on a module-detail view) and `modules.search_hits` (bumped
  for every module surfaced in a search page) blend into `?sort=popular`.
- **Download & last-updated refinements.** Per-version download counts (`VersionSummary.downloads`);
  artifact-file fetches via `.../files/<parquet>` now count as downloads (so presigned/CDN redirects
  are counted while log/provenance/logo fetches are not); a distinct module-level `created_at`
  (first publish) surfaced on the card alongside `updated_at`. (Download counts and `updated_at`
  themselves already existed since 0.x — this release refines them.)

### Note
- New sort keys: `?sort=stars|popular` (in addition to `downloads|recent|name`).
- New rate-limit category `social` (star toggles), configurable via `REGISTRY_RATE_SOCIAL_PER_MIN`
  (default 30/min).

## [0.5.0] — 2026-07-07

Accommodates **just-dna-format / just-dna-compiler 0.2.0** (pins bumped to `>=0.2.0`). The DB stores
each version's whole `manifest.json`, so the new manifest fields round-trip with **no schema
migration**; this release *surfaces* and *serves* them.

### Added
- **Structured provenance + gene-panel surfacing.** A published spec's `provenance.json` (per-variant
  rationale) is compiled, hashed, and served at `.../files/provenance.json`; the manifest carries the
  lean `provenance` summary. A `panel` (gene-panel) declaration and `display.icon_set` round-trip and
  appear on the module card.
- **ClinVar stat surfacing.** `CardStats` gains `clinvar_count` / `pathogenic_count` / `benign_count`.
- **Module logo.** A published `logo.{png,jpg,jpeg}` is compiled out of `artifact.digest`, served at
  `.../files/<logo>`, included in the download tarball, and exposed as `logo_url` on the card
  (consumers fall back to `icon`/`icon_set` when absent).
- **`POST .../versions/{version}/logo`** — owner-scoped logo replacement, mirroring `amend-changelog`.
  Metadata-only: the artifact/digest — and any signature over it — stay immutable, so **no version
  bump**. Client `amend_logo(...)` + `registry-client amend-logo`.
- **Optional Ed25519 signing (SPEC §5).** Set `REGISTRY_SIGNING_KEY` to an Ed25519 private-key PEM
  and the server signs each version's `artifact.digest`; `GET /api/v1/pubkey` serves the public key
  for clients to pin. `VersionSummary.signed` flags signed versions; `client.download(...,
  public_key=...)` enforces a pinned key. Unset (default) → unsigned, 0.4 behaviour unchanged.

## [0.4.5] — 2026-07-07

### Added
- **`GET /health` now reports `version` and `storage`** — so you can confirm which build is live
  without shell access to the box (`{"status":"ok","version":"0.4.5","storage":"hf"}`). The version
  is read from installed package metadata (`importlib.metadata`), not hardcoded — the FastAPI
  `app.version` (and `/openapi.json`) track it automatically on every bump.

### Note
- This does **not** change the large-publish path. A publish still couples one HTTP connection to
  the full server-side compile (~90 s for genome-wide modules); if that connection is severed
  (proxy header-timeout, or the worker dying — e.g. OOM on a 674k-variant compile) the client sees
  `RemoteProtocolError: Server disconnected`. Decoupling publish (`202` + background compile + poll)
  is tracked in ROADMAP 0.5.

## [0.4.4] — 2026-07-07

### Added
- **`registry remove-version <ns> <name> <v>`** — ops-only hard delete of a *single* version
  (row + facet rows + artifacts), recomputing the module's latest. Complements the whole-module
  `remove-module` and per-version `yank` — for surgically dropping one bad/partial version so it can
  be re-uploaded. `repo.delete_version(...)`.

## [0.4.3] — 2026-07-07

### Fixed
- **Publish no longer blocks the event loop.** `compile_module` (CPU-heavy — up to minutes for
  large modules) now runs in a worker thread (`run_in_threadpool`) instead of synchronously in the
  async handler. Previously a big publish froze the whole server for the duration and the
  connection was dropped mid-request (`RemoteProtocolError: Server disconnected`), even though the
  compile eventually finished with 201. Fixes publishing large modules (e.g. `pathogenic`, ~89 s).
- SQLite `busy_timeout=5000` to absorb brief write contention now that publishes run concurrently.

### Changed
- Client HTTP timeout default 120 s → **600 s**, and env-configurable via `REGISTRY_TIMEOUT`.

> Deployment note: a reverse proxy in front of the server (Caddy) must also allow long upstream
> responses for large publishes; otherwise it will cut the connection before the compile finishes.

## [0.4.2] — 2026-07-07

### Added
- **Amend changelog** — `PATCH /modules/{ns}/{name}/versions/{v}` updates a published version's
  changelog (metadata only; the artifact/digest stay immutable — not a re-publish). Owner-only,
  `append` option. Client `amend_changelog(...)` + CLI `amend-changelog`.

## [0.4.1] — 2026-07-07

### Added
- **Optional JWT sessions** — `POST /auth/tokens` exchanges a static API key for a short-lived JWT,
  also accepted as a bearer. Backwards-compatible: static keys always work; JWT is off unless
  `jwt_secret` (≥32 bytes) is set (`501 jwt_disabled` otherwise). Config: `jwt_secret`,
  `jwt_ttl_seconds`.

### Removed
- **Prebuilt-parquet upload / "trust-but-verify" mode** — dropped as planning legacy. It existed to
  avoid bundling the compiler, but the server recompiles from spec, so there's no prebuilt artifact
  to ingest. (Reproducibility, if ever needed, is better checked via parquet frame-shape +
  canonically-sorted content than byte digests.)

## [0.4.0] — 2026-07-07

Moderation, ops hardening, HuggingFace storage, and the webui page deliverable.

### Added
- **Featured namespaces** — `featured` flag; featured modules float to the top of every listing,
  `?featured=true` restricts, cards carry `featured`. Admin CLI `feature`/`unfeature`.
- **Blacklisted namespaces** — hidden from default `GET /modules`/search; reachable via
  `?namespace=`, `?include_blacklisted=true`, or direct detail. Admin CLI `blacklist`/`unblacklist`.
  New list filters: `namespace`, `featured`, `include_blacklisted`.
- **Key revocation** — `registry revoke-key` / `revoke-account`.
- **Rate limiting** (SPEC §7) — in-memory token buckets per caller × category on
  search/download/publish; `429 rate_limited` + `Retry-After`. Config: `rate_limit_enabled`,
  `rate_publish_per_hour`, `rate_download_per_hour`, `rate_search_per_min`.
- **`HfStorage` backend** — HF dataset repo (`data/{ns}/{name}/{version}/…`); commit writes,
  `HfFileSystem` reads, `302` to HF `resolve` URLs. Select with `storage_backend=hf`.
- **Docs** — `WEBUI-STORE.md` (registry-page deliverable for the webui).

### Migrations
- `namespaces.featured` / `namespaces.blacklisted` columns (idempotent, in-place).

### Deferred (see ROADMAP 0.4)
- Ed25519 signing, presigned PUT, prebuilt "trust-but-verify" mode, JWT/OAuth + orgs, download
  analytics. → 0.5: Postgres, FTS5/search. Excluded: S3/MinIO.

## [0.3.0] — 2026-07-07

Community-first, self-service onboarding — publish from the just-dna-lite UI without leaving the app.

### Added
- **Install-id proof-of-work** (`installid.generate_install_id` / `validate_install_id`, exported
  at top level) — the lite app mints one at first run; SHA-256 with ≥ `install_id_difficulty`
  (default 20) leading zero bits. Deters random/bulk spambot ids; O(1) to verify.
- **Self-registration** — `POST /api/v1/auth/register {install_id, account}` mints an account +
  API key (one per install-id). Gated by `allow_self_register` (default on).
- **Namespace claim** — `GET /api/v1/namespaces/{ns}` (availability) + `POST /api/v1/namespaces`
  (claim), up to `namespaces_per_account` (default 5) per account; `409 namespace_taken` /
  `403 namespace_limit_reached`.
- **Batch digest lookup** — `POST /api/v1/modules/lookup {digests:[…]}` (cap `lookup_batch_max`) to
  classify many local modules at once.
- **Client + CLI** — `RegistryClient.register / namespace_available / claim_namespace /
  lookup_by_digests`; `registry-client register | namespace-available | claim-namespace`.
- Provenance: `registry-client publish` now **stamps** the returned manifest into the local spec
  dir so a module is discernible as published-by-you (no `module_spec.yaml` change).
- Config: `allow_self_register`, `install_id_difficulty`, `namespaces_per_account`,
  `lookup_batch_max`.

### Changed
- DB: `accounts.install_id` (unique, nullable) added via an idempotent in-place migration.

## [0.2.1] — 2026-07-07

### Added
- **HF token startup guard** — when `storage_backend=hf`, the server validates on startup that the
  configured HF token is present, valid, and has **write** access to the dataset repo, and exits
  with code `1` otherwise. No-op for the local backend.
- Docs: `API-REFERENCE.md` (exhaustive REST reference), `CLIENT.md` (Python + CLI surface),
  `CHANGELOG.md`.

## [0.2.0] — 2026-07-07

Client-first packaging + a live deployment at <https://module-registry.just-dna.life>.

### Changed
- **Client-first library layout.** The default install is now the reference **client** only
  (deps: `httpx`, `typer`, `python-dotenv`, `just-dna-format`); `from just_dna_registry import
  RegistryClient`. The server (FastAPI app, `just-dna-compiler`, storage, admin CLI) moved to
  the **`server` optional extra** — `pip install just-dna-registry[server]`.
- Depends on the published PyPI packages `just-dna-format>=0.1.0` + `just-dna-compiler>=0.1.0`
  (no local path sources).

### Fixed
- `GET /modules/{ns}/{name}` (detail) now returns the **full** `stats.genes` list (SPEC §8.3);
  only list/search cards truncate to the top 3.

## [0.1.0] — 2026-07-06

Initial registry service (internal builds; superseded by 0.2.0 packaging).

### Added
- **Read / catalog API** — `GET /modules` (search `q`, facet filters `category`/`gene`/
  `genome_build`/`owner`/`license`, `sort=name|downloads|recent`, pagination), module detail,
  version list, full manifest.
- **Publish (server-side recompile)** — `POST …/versions` takes a multipart **spec** upload; the
  server runs `validate_spec` + `compile_module(compiled_by="marketplace-server")`, fills the
  registry manifest fields, stores the version, and indexes it. Guards: `401` auth, `403`
  namespace ownership, `422 invalid_version`, `409 version_exists`, `422 {invalid_spec|compile_failed|
  name_mismatch}`.
- **Archive import** — `POST …/versions/import` accepts a **zip/tar.gz**: a spec archive is
  recompiled directly; a legacy parquet-only archive is reverse-engineered (`reverse_module`, with
  client-supplied display metadata) then recompiled. Path-traversal-safe extraction.
- **Download + integrity** — `…/versions/{v}/download?format=files` (per-file `{name,url,sha256,
  size}`) and `?format=tarball` (streamable `tar.gz` of the whole version); `…/files/{path}` serves
  any manifest-listed file (parquet, log, input) or `302`-redirects. Verify-then-install via
  `just_dna_format.verify_manifest`.
- **Provenance logs over the API** — `…/versions/{v}/logs` lists per-version run logs (top-level
  `*.log` + a `logs/` per-role subtree), fetched through the files endpoint.
- **Digest lookup** — `GET /modules/lookup?digest=` returns published versions matching an
  `artifact.digest` (dedup / "already published?").
- **Auth** — static API-key bearer; `GET /auth/whoami`; namespace ownership gate on writes.
- **Yank / un-yank** — `POST …/versions/{v}/yank`; drops from default listings + `latest`, keeps
  the artifact fetchable.
- **Version-scoped storage** (`{ns}/{name}/{version}`) behind a `StorageBackend` interface;
  `LocalStorage` shipped (`HfStorage` pending). `artifact.digest` remains the content identity.
- **Debug logging** behind `REGISTRY_DEBUG` — request tracing, always-on exception tracebacks,
  and Eliot-structured publish/import step logs (one `task_uuid` per request).
- **Reference client** (`RegistryClient`) + **`registry-client` CLI** (list, download
  [+`--tarball`], publish, import-module, find-by-hash, update-module-version).
- **Admin CLI** (`registry`) — `serve`, `init-db`, `issue-key`, and ops-only hard removal
  `remove-module` / `remove-namespace` (purges DB rows + artifacts, frees the namespace; not yank).
- `.env.template`, `docs/SPEC.md`, `docs/ROADMAP.md`.

[0.8.1]: #081--2026-07-09
[0.9.1]: #091--2026-07-10
[0.9.0]: #090--2026-07-09
[0.8.0]: #080--2026-07-09
[0.7.1]: #071--2026-07-08
[0.6.0]: #060--2026-07-08
[0.5.0]: #050--2026-07-07
[0.4.5]: #045--2026-07-07
[0.4.4]: #044--2026-07-07
[0.4.3]: #043--2026-07-07
[0.4.2]: #042--2026-07-07
[0.4.1]: #041--2026-07-07
[0.4.0]: #040--2026-07-07
[0.3.0]: #030--2026-07-07
[0.2.1]: #021--2026-07-07
[0.2.0]: #020--2026-07-07
[0.1.0]: #010--2026-07-06
