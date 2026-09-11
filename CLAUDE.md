# Agent Guidelines — just-dna-registry

This repo is the **annotation module registry**: a standalone, **server-side REST API
service** (FastAPI) that catalogs, versions, validates, and serves annotation modules for the
`just-dna-lite` ecosystem. The webui and Dagster pipelines are *consumers* of this API. Any
**install-side** UI concern (Reflex, Fomantic, PRS widgets, the Store) belongs in `just-dna-lite`,
not in this repo. What this repo *does* carry since 0.23 is its own **console** (`src/just_dna_registry/ui/`,
[docs/UI.md](docs/UI.md)): a browser page over the same API, for publishers and operators, served
at `/ui/` and by `registry-client ui`. "There is no frontend here" was the rule for twenty-two
releases and is recorded rather than deleted: the console is a *consumer* that happens to live in
the same tree, and the rules under *The console* below are what keep it one.

The founding design document is **[docs/SPEC.md](docs/SPEC.md)** — read it first. It is the source
of truth for the manifest contract (§4), integrity mechanism (§5), versioning (§6), and the REST
interface (§8). This file (`CLAUDE.md`) is the *how we code* companion to that *what we build* spec.

---

## What this service does (one screen)

- **Catalog index** — a queryable projection (SQLite for MVP → Postgres) of every published
  `(namespace, name, version)`. The per-module `manifest.json` is the **source of truth**; the DB
  is a rebuildable projection of it.
- **Artifact storage** — HuggingFace Hub datasets (hybrid backend: free CDN + git-revision
  versioning + existing `HfFileSystem` discovery), or S3/MinIO keyed by digest.
- **Server-side compile/validate gate** — on publish the server runs `validate_spec()` and
  (default) `compile_module()` itself, so `compile_success`, input hashes, and artifact digests are
  produced by the trusted party and cannot be forged.
- **Integrity contract** — SHA-256 per input CSV and per artifact file, plus a Merkle-root
  `artifact.digest` that is the version's immutable **byte** identity (the *content* identity is
  `content_signature`; see *Manifest & integrity*).

This service **depends on the `just-dna-format` workspace** for `validate_spec`, `compile_module` and
the `ModuleManifest` models — three packages, three tiers: `just_dna_format` (schema, pydantic +
cryptography), `just_dna_compiler`, `just_dna_enricher` (the only tier permitted to fetch). Reuse that
code; do not re-implement compilation or the manifest schema here. `just-dna-pipelines` is a *sibling
consumer*, not this service's dependency — an earlier version of this line said otherwise, which is
worth knowing if you meet the claim again somewhere it has been copied to.

**A migration must detect its own trigger, not be told about it.** `registry upgrade` decides whether a
published version needs recompiling by comparing its `compilation.compiler_version` stamp against the
installed compiler, under `version.contract_compatible` — the *same* rule that refuses a 0.5 client on a
0.6 server, because a 0.5-compiled artifact sitting in a 0.6 catalog is that same disagreement with
nobody to report it to. Before 0.18.0 the test was `content_signature is None`, true only of a pre-0.5
manifest: a witness for one era, which answered *no gap* for every 0.5-era version the moment we moved
to 0.6. The catalog-wide re-baseline silently became a no-op (5 of 11 reference modules), the operator
doc was corrected to say `--force`, and the hardcoded "recompiled under just-dna-format 0.5" sentence
would have been stamped — permanently, since manifests are immutable — onto everything the 0.6 sweep did
touch. **Never date a stored artifact by testing for a landmark; compare versions.** Three properties to
keep: a compiler *patch* is not a gap (it moves no schema, and acting would mint a PATCH per module per
dependency bump), an *unidentifiable* compiler is neither current nor stale and is counted and named
rather than skipped in silence, and `--force` means "no gap detected, do it anyway" — if it is ever the
documented normal path again, the detector is what is broken.

**The floor is a lockstep, not a minimum.** `version.contract_compatible` treats a `0.x` minor as a
breaking contract change, so the installed minor must match what clients speak; adopting a new format
minor is a coordinated cut with an operator procedure, never a dependency bump. See
[docs/UPGRADE.md](docs/UPGRADE.md).

**And a *patch* inside that minor can still be mandatory — check what it touches before floating it.**
0.17 floors at **0.6.1**, not 0.6.0, because upstream RM95 stored an uncanonicalized vocabulary
spelling *inside* `content_signature`: a signature this server publishes is a permanent global claim on
a `409 duplicate_content` slot that only a purge frees, so a floor below that fix lets one be minted
over a value upstream calls invalid. Two more of the eight land on our endpoints (RM93 — `validate` did
not predict `compile` for two shapes, which is S6's rule one tier down; RM97 — see the catching rule
below). The reasons are written into the `pyproject.toml` pins beside each floor, which is where the
next person will look.

**And the three tiers *could* move apart — through 0.19 the enricher floored at 0.6.4 while the other
two stayed at 0.6.1. Since 0.20 all three are 0.6.6 and that is no longer available**, because from
upstream 0.6.5 the compiler and enricher read format symbols that exist only there and upstream's own
inter-package floors are `>=0.6.6`. The reasoning below is kept rather than deleted: a partial cut is
still the right question to ask of the *next* enricher patch, and the three floors it describes were
each correct when taken. What changed is the answer, not the method — check whether the tiers still
resolve apart before assuming either way. The network tier touches no parquet, model or manifest field, so upstream can cut it alone —
and none of the three enricher floors is a symbol missing below it. **0.6.2** is one whose *meaning changes at*
it: our adapters catch `FrequencyUnavailable` and its siblings, which on 0.6.1 nothing raises, so those
arms would be dead code and `/check` would 500 over an outage again. **0.6.3** is the same shape moved
onto an argument — `load_dotenv_file` had reached none of the six cache resolvers, so the `False` we
had always passed to them was inert, and the release that makes the flag work is the release where
*keeping* it becomes the change. Read what a patch **does** before assuming a partial cut is optional,
and check the flags you already pass as well as the symbols you already import: upgrading all three in
step here would have been wrong, and so would treating an enricher patch as beneath reading.

**0.7 is a coordinated cut, and the two things to carry from it are a closed vocabulary and a lane
registry.** All three tiers go to 0.7.0 together. On the base install the floor is hard because
`VerificationRecord` is `extra="forbid"` and RM129 adds `producer` to it — serialised as `null` even
where nothing set it, which trips `extra_forbidden` exactly as a value would — and because RM193 adds
`variant_impact_agreement` to `VALID_VERIFICATION_CHECKS`, which that model *validates* against rather
than merely annotating. The general form outlives both: **a vocabulary is additive for the writer and
closed for the reader**, so validating a document against your own copy of one makes every future
member a break. Keep no copy of any of them here. On the enricher the floor is a registry we now read
rather than a symbol we import: `caches.CACHE_LANES` is upstream's list of every snapshot lane and
`prepare_caches` is how they are provisioned — see *Cache lanes* below.

**And having read one, be willing to say it is not load-bearing. `0.6.4` is the first enricher floor
here that is *not* hard** — one fix in upstream's ClinVar drafter, no public symbol moved, nothing this
service runs behaving differently, and a deployment left on 0.6.3 is not broken. It is the floor
because the lock had already resolved it and the release's suite ran on that trio, so leaving the floor
behind would permit an assembly nobody tested. Record which kind a floor is when you add one: the
0.6.2 and 0.6.3 comments run long because both were easy to mistake for optional, and that whole
argument is wasted if a later reader learns to skim every floor as mandatory.

**A fallback exercised routinely is a signal the detector is missing something — and that is not the
same as the detector being broken.** 0.20 told operators to run `upgrade --apply --force` to pick up
RM121's `stats.genes` fix, and that was the *correct* use of a fallback: nothing could measure the
drift, so `--force` was the only thing between an operator and a permanently stale catalog. 0.21 builds
the measurement (`services/rebuild.py`), so the everyday case is plain `--apply` and the lever goes back
to being an exception handler. Keep the two failures apart: 0.17's step 2 documented `--force` as the
normal path *because the detector was broken*, which is a defect; 0.20 reached for it *because the
detector could not yet see this axis*, which is a fallback doing its job and a prompt to extend the
detector. **The delegation rule underneath both**: `--dry-run` vs `--apply` is already the look-vs-act
discriminator, so asking for `--force` on a gap the software has just *measured* makes an operator
confirm what the software already knows.

**And a third witness landed in 0.24, from upstream, answering the interval instead of the field.**
`release_records.needs_recompile` (their RM126/RM127, our S62) states per-axis what a *release* changed
about compiled output, and `services/rebuild.declared_movement` is the seam. Four rules, each of which
cost a design argument. **Only a declared `correction` acts** — upstream separates it from `addition`
because a differ cannot, and acting on the `parquet_bytes` axis alone would re-baseline the catalog on
every dependency bump (10 of 16 reference modules move `artifact.digest` across a pure *patch*
interval). **The record can also withhold**: a contract-scale version gap over an interval it covers
with every driving axis measured `False` moved nothing, which retires the version comparison as a
*parallel derivation* and leaves it as the fallback for every artifact compiled before the first
release that has a record. **Three witnesses stay three** — a gap is about versions, a verdict is a
measurement of one artifact, a record is what a release did — because folding any two loses a
distinction only that one can draw. And **a declared change says what a release did, never which
artifacts it did it to**, so a sweep over-reaches; that is bounded at one PATCH per module ever by the
convergence rule and is filed upstream as S90, not worked around by parsing a target's spelling.

**And when you do extend it, the new trigger has to converge.** `rebuild.RebuildVerdict` refuses to act
on drift measured against the **identical** compiler, because a recompile derives the same value again
and acting would mint a fresh PATCH every sweep — the failure the patch rule exists to prevent, walking
back in through a different door. That refusal is also what bounds every false positive to one wasted
PATCH per module ever, since the successor is always `gap=none`. Two consequences to keep: a probe
recomputes from **authored** rows while `manifest.stats` may have been re-derived after the
symbolic-allele drop (`compiler.py:3822` vs `:4131`), so a disagreeing `variant_count` downgrades the
comparison to `cannot_say` rather than reporting drift; and probe only fields with a *reason* — one
added because a field merely exists is how a detector starts crying wolf.

**A version-gap check belongs to the thing that has versions.** Most of 0.6.3 is upstream's ClinVar and
ClinPGx *drafters*, and the honest answer for this service was that it has none — drafting is
authoring-side, so "modules published before this need a re-draft" is a message for module authors and
not a `registry upgrade` sweep. Nothing recompiles here: the compiler stayed at 0.6.1, and a compiler
patch is deliberately not a gap. Say that in the release rather than leaving a reader to infer it, or
the next operator runs the UPGRADE.md sweep expecting it to fix a drafted module, and it cannot.

**The other half of that: advice forwarded on somebody else's behalf is still ours to correct.** 0.18.1
passed upstream's remediation along as *those modules need a fresh upload from their publisher*, and
0.6.4 (S45) is upstream measuring what 0.6.3 had not — a re-draft of the existing spec **appends** the
corrected rows beside the ones they supersede, so the shorter instruction produces a module worse-formed
than either the old one or a new one. The publisher needs a fresh spec directory. Two things generalise.
A remediation we relay is a claim we made, so re-read it when its source is re-measured. And **before
building a detector for a defect like this, ask whether the artifact can even carry the evidence** — the
superseded rows are invisible from inside a published module (coordinate rows carry no `rsid`; the
obvious predicate finds 0 of 31), so a facet or `revalidate` rule would report clean on every affected
module, which is worse than having none.

---

## Running the service

- `uv run registry serve` starts the API (Typer CLI → uvicorn). `uv run pytest -q` runs tests.

  **Both of those are the post-cut form and neither runs on `format-0.7-adoption` as written.**
  `just-dna-format` 0.7.0 is bumped upstream and tagged nowhere, so a plain `uv run` resolves the
  floor against PyPI and exits *"requirements are unsatisfiable"*. On that branch, either of these,
  both run verbatim before being written here:

      .venv/bin/python -m pytest -q
      UV_FIND_LINKS=/data/sources/just-dna-format/dist uv run pytest -q

  The second re-locks `uv.lock` every time and the branch's lock is deliberately stale, so
  `git checkout uv.lock` before committing — the first form avoids that entirely and is what to reach
  for. **Never `uv sync` there**: it resolves the stale lock and downgrades the format tier out from
  under a branch that needs 0.7.0 from the sibling's `dist/`.

  Delete this note when a plain `uv run pytest -q` succeeds on the branch you are standing on, which
  is a thing to check rather than a date: run it and read the exit.
- The Typer CLI (`src/just_dna_registry/cli.py`) owns admin/ops tasks — `serve`, `init-db`,
  `issue-key`, and future backfill/reindex. Add new ops commands there, not as ad-hoc scripts.
- Deployable as one container + a bucket/HF repo + a DB. No heavyweight orchestration.

When adding a public command, let the **root package's `[project.scripts]`** own it. If `uv run <cmd>`
resolves to a dependency's script after a dependency upgrade, bump this package's version and re-run
`uv sync` so uv rebuilds the `.venv/bin` wrappers — never rename the user-facing command to dodge a
stale wrapper.

---

## Coding Standards

- **Avoid nested try-catch**: try/catch often just hides errors; use it only where an error is an
  unavoidable, handled part of the use case.
- **Type hints**: Mandatory for all Python code.
- **Pathlib**: Always use for file paths.
- **No relative imports**: Always use absolute imports.
- **No inline imports**: All imports at module top level. Never `from X import Y` inside a function or
  method. Only exception: a guarded `try/except ImportError` for optional deps at module level.
- **Polars over Pandas**: Use lazyframes (`scan_parquet`) and streaming (`sink_parquet`) for
  efficiency. Pre-filter dataframes before joining to avoid materialization.
- **Pydantic 2**: Mandatory for data classes — request/response models, config, and the manifest
  contract. FastAPI response models should be explicit Pydantic types, not bare dicts.
- **Typer CLI**: Mandatory for all CLI tools.
- **Logging**: Use the standard-library `logging` system logger.
- **Linting is ruff, and the config is a mirror**: `uv run ruff check .` must pass. `[tool.ruff]` in
  `pyproject.toml` is copied from `just-dna-format`'s, deliberately — the two repos are edited in the
  same sitting, and a rule that fires in one and not the other turns a lint run into a question about
  which checkout you are standing in. Take upstream's changes to that block rather than diverging;
  the recorded local differences are the `.claude/` exclude (gist-synced scripts, one-way by hand),
  the `tests/*` glob (one suite, not three member packages), and FastAPI's `Depends`/`Query`/`File`
  defaults folded into the existing B008 exemption. Reasons for the *unselected* rules live in that
  block too — add to them rather than rediscovering why BLE001 is off.
  **The one rule that must never be auto-applied here is SIM118.** Catalog rows are `sqlite3.Row`,
  whose `__contains__` scans **values**, not keys: `"downloads" in row` is `False` for a column that
  is genuinely present, so ruff's `key in dict` rewrite silently turns every optional projection off
  (`featured`, `needs_upgrade`, `downloads`, and the signed check). The four sites carry a `noqa` and
  `services/catalog.py` carries the proof. More generally, a `--fix` on this codebase needs the
  suite behind it: an "unused" import may be a **re-export** a test imports from us
  (`specfiles.LICENSING_CSV` is exactly that, and removing it broke collection).
- **Pay attention to terminal warnings**: Always check output for warnings, especially deprecation
  ones. AI knowledge of APIs can be outdated; these warnings are critical hints to update code.
- **No placeholders**: Never use `/my/custom/path/` or fabricated example values in code.
- **No legacy support**: Refactor aggressively; do not keep old API functions around.
- **Dependency management**: Use `uv sync` and `uv add`. **NEVER** use `uv pip install`.
- **Versions**: Do not hardcode versions in `__init__.py`; read from `pyproject.toml`.
- **Avoid `__all__`**: Avoid `__init__.py` with `__all__` — it obscures where things live.
- **Self-correction**: If an API mistake causes a crash or a real logic failure due to outdated
  knowledge, update this file with the correct API/pattern so future agents don't repeat it.

---

## REST API conventions (see SPEC §8)

- **Base path** `/(...)/api/v1`. All bodies JSON unless noted. Version the API in the path; do not
  break `v1` clients.
- **Pagination**: list endpoints take `?page` and `?per_page` (max 100) and return
  `{items, total, page, per_page}`.
- **Search/facets** on `GET /modules`: `?q=`, `?category=`, `?gene=`, `?genome_build=`, `?owner=`,
  `?license=`, `?sort=downloads|recent|name`. Facet filters (`gene`, `category`) join side tables,
  not full-text.
- **HTTP status contract** (match the spec exactly — clients depend on these):
  - `409 version_exists` — a published `(namespace, name, version)` is **immutable**; re-publish fails.
  - `409 duplicate_content` — the same module data is already published under a **different**
    `(namespace, name)`. Keyed on a name-independent data-input signature (`content_hash`), not
    `artifact.digest` (the module name is baked into the compiled parquets, so it can't detect a
    rename). A collision under the same module (later version, unchanged data) is allowed.
  - `403 not_namespace_member` — the bearer token's `namespaces` must include the path `{ns}`.
  - `422 invalid_version` / `422` with `errors[]`/`warnings[]`/`info[]` from `ValidationResult` on a
    bad spec; `422 digest_mismatch` when a prebuilt upload disagrees with a sandbox re-compile.
  - `413 upload_too_large` — the bytes on the wire exceed `max_upload_bytes`. Distinct from
    `422 too_many_variants`, which is a legal body asking for too much *work*, and from
    `413 archive_too_large`, where the archive *expands* past `max_extracted_bytes`.
    **`max_upload_bytes` mirrors the deployment's HAProxy request-body cap** — it exists so an
    oversized body gets our structured error instead of a severed connection. It is not a knob to
    turn when something does not fit; raising it above the proxy's limit only makes the failure
    opaque. Send the spec compressed instead.
    **Every spec route takes both wire forms** — loose `files=` parts or one compressed `archive=`.
    They are not interchangeable conveniences: a 180 MiB spec is a `413` raw and 10 MB packed, so a
    route offering only the raw form silently excludes the largest modules. Giving `/versions/import`
    an archive form while `/validate` and `/check` had none is what made the ClinVar panels
    publishable but impossible to rehearse. A new upload route accepts both, or it is unfinished.
  - `503 enrichment_unavailable` (+ `missing[]`) — the network tier cannot run **at all** (today:
    `just-dna-enricher` is not installed). **No `Retry-After`**: retrying does not help until an
    operator changes the deployment. 503 over 501 (the feature is implemented) and over 424
    (obscure). A *missing snapshot* is **not** this — it degrades per pass with a note in
    `enrichment.notes`, because an online run resolves through live Ensembl without one, and the
    earlier 503-on-empty-references refused the one configuration that works.
  - `503 enrichment_busy` / `504 enrichment_timeout` — the concurrency gate is full / the run
    exceeded `enrich_timeout_seconds`.
  - **The dry run grades where the publish grades, which is *after* enrichment.** `publish_version`
    validates modelessly first — that pass exists to reject a broken spec before spending enrichment
    on it — and lets `compile_module` apply strict at its real severity. `/check` must do the same,
    and until 0.24 it did not: format 0.7's RM141 made `validate --strict` refuse a partial resolution
    table, so grading the *pre-enrichment* tree returned `invalid_spec` with `enrichment: null` for
    every rsID-authored module, at the endpoint whose whole contract is to report. `resolve_with_ensembl`
    stays at its default on both sides — a pre-flight that silenced the fill would be *more optimistic*
    than the compile it precedes, the one disagreement direction the parity rule forbids. And
    `would_publish_module_level` is carried from the modeless gate by definition: strictness changes
    severity only, so every strict-only error is a per-row judgement belonging to the enrichment tier.
  - **A validation finding is a `200`, not a `422`.** `/validate` and `/check` return `valid: false`
    with the reasons in the body; only a request no spec dir can be built from is a 4xx. Publish is
    the opposite. Getting this backwards makes the endpoints useless to the CI jobs they exist for.
  - **The version handshake certifies compiled artifacts, not the authored row schema — and 0.22
    ships the residue as advice rather than closing the gap.** `version.contract_compatible` passes
    at `0.x` MINOR because that is the grain at which the parquet contract and `artifact.digest`
    move. The **row** models tighten at PATCH: they are `extra="forbid"` and a format patch may add a
    column (`StudyRow.curator`, 0.6.5), so a certified pair can still refuse a spec, and the refusal
    is pydantic's sentence for a *typo* (S18). **Do not narrow the guard to patch grain** — it would
    reject 0.6.6↔0.6.1, which is every pair we actually run. `schema_gap_advisory` reports the pair
    instead, on the dry runs and on `422 invalid_spec`. Two properties to keep. It is derived from
    the two version strings and **never** from the findings — verified: `curator` and `curatr`
    produce the identical line but for the name, so reading the error to decide whether to advise is
    the sentence-matching this file forbids one section along. And it is **not** conditioned on the
    verdict, because a note that appears only beside a failure makes its own absence ambiguous. What
    it still cannot say is which release introduced the column; that needs an input-side roster from
    upstream (filed as their S81) and **must not** be answered from format 0.7's `release_records`,
    whose `parquet_schema` axis describes compiled *output* and is silent on an authored column no
    module in the interval emitted.
- **SDK parity is part of the endpoint.** Every REST endpoint is wrapped by a `RegistryClient` method
  **in the same patch** that adds it, and covered in `tests/test_client_sdk.py`. SDK↔API drift is
  what blocked webui publishing in 0.8.1; a route with no client method is an unfinished route.
- **Every release carries a `**Client surface:**` line** — *unchanged*, or the methods whose
  signatures moved. Consumers call a handful of methods against a 35-endpoint API, so "did this
  release touch anything I call?" is their only real question, and without that line the sole way to
  answer it is to read a release in full or diff the client (S2: 0.9.1 → 0.12.0 cost exactly that,
  to conclude nothing had moved). A new method is *unchanged* for this purpose: it breaks nobody.
  Both reference docs are likewise stamped with the version range they are normative for — an
  unstamped schema is what makes a consumer write defensive code against a shape we specified exactly.
- **Downloads** redirect (`302`) to presigned/CDN URLs; the API serves JSON, not artifact bytes.
- **Auth**: Bearer tokens. Anonymous reads are allowed but throttled harder. Rate-limit with per-token
  buckets (publish 10/h, download 1000/h, search 60/min).
- **Async**: prefer `async def` handlers; never block the event loop with heavy CPU work (compilation,
  hashing) — offload to a thread/executor or a worker. An endpoint with an **external** cost needs a
  process-wide concurrency gate as well: a token bucket bounds one caller, not the server. Acquire
  such a permit in the coroutine (so queued callers do not each occupy a threadpool worker) and
  release it in the worker's own `finally` — `asyncio.wait_for` cancels the await, not the thread.
  **Whether a full gate is a `503` or a queue depends on who is waiting**: an interactive endpoint
  fails fast, an unattended one queues without a deadline. See *Enrichment on the server*.

---

## Enrichment on the server (0.11)

`just-dna-enricher` is the only tier permitted to fetch. It runs **before** the compile, as a
separate step, writing `resolution.csv` for the compiler to consume — the compile path must never
import it (CONSTITUTION Principle 2), which is why `compile_module(ensembl_cache=…)` is not used and
why `services/enrich.py` imports the enricher lazily, inside its functions. A test asserts the
boundary; keep it true.

Four rules that each cost a bug to learn:

- **Always pass the *configured* cache path, never the resolved one.** `enrich()` runs the resolver
  ladder itself and reads `None` as "find one for me" — so passing a resolved-to-`None` empty cache
  licenses the ambient discovery the explicit setting existed to prevent. `configured_caches()` for
  the call, `available_references()` for reporting.
- **Always `download=False`** on a request path. A missing snapshot is a well-defined `503`, not a
  five-minute HuggingFace pull inside a handler.
- **Never `mode="strict"` on a reporting endpoint.** Strict enrichment raises *before* writing
  `resolution.csv`, so a failure leaves nothing to diagnose from. Enrich best-effort and let the
  compiler's strict gate refuse — it names the offending variants.
- **One shared `LookupClients` per process, on *every* path that egresses.** The outbound pacing that
  keeps us inside gnomAD's and NCBI's limits lives on the client object, so per-request bundles egress
  at N× the intended rate. **Anything that takes the shared bundle must also take a gate permit** —
  `/check` and the publish path both do; publish takes it conditionally, since an offline publish
  reaches nothing and has nothing to serialize. Through enricher 0.5.3 that was two rules welded into
  one, because `PacingGate` had no lock and a limit above 1 would have *raced* it; 0.5.4 (S15) makes the
  gate thread-safe, with this server's threadpool named as the arrangement that provoked the fix. So the
  permit is now about the *budget*, not about the race: the pace is shared, so concurrent runs interleave
  on one spacing rather than going faster, and `enrich_max_concurrency` stays 1 as a latency choice
  rather than a correctness one.
  **And the bundle has to be *constructed*: bare `LookupClients()` is eight `None`s.** Its docstring's
  "lazily built" describes `lookup.py`, whose functions do `clients.x or XClient()` and close what
  they made — nothing fills the dataclass. An empty bundle passes `None` into every `resolver=` /
  `gnomad_client=` / `eutils=` argument, so each pass builds its own client, the pacing is per call
  again, and `close_lookup_clients` closes nothing. `shared_lookup_clients()` builds all eight.

  **It said "six" until 0.25, and the two it was missing were not a rounding error.** That dataclass
  carries **three different lazy-build semantics and which one a field gets is invisible at the call
  site**: `_lookup_live_loci` and `lookup_old_assembly` assign the client they build *back onto the
  caller's bundle*, so a shared bundle ends up pacing those whether you filled the field or not;
  `_check_pmcid` and `_lookup_frequencies` build-and-close per call, so an unfilled field there is
  per-request pacing however shared the bundle is. `gnomad` happened to be filled and `pmc_idconv`
  did not, which made the citation leg the one that would have egressed unpaced the moment it was
  exposed over HTTP. **Fill every field; do not reason about which ones matter** — the reasoning is
  what was wrong, not the count. Filed upstream as the real fix: one constructor, or one uniform
  lazy path.
- **`offline` means *snapshot only*, not "that source is off" (enricher 0.5.1 / RM38).** Every pass
  is snapshot → live → skipped-with-a-reason, so a provisioned deployment gets the full `?pgx=` check
  with zero egress. Assuming the family is online-only silently skips work a cache could have done.
  ClinGen dosage is the one genuine exception — CC0, live-only, no snapshot exists.
- **Pass the caches, and pass `offline` — never hoist a guard of your own.** A caller-side
  `if not offline:` reimplements a decision the pass now makes better than we can: it knows whether
  a *snapshot* client was injected, which is not egress.
- **A pass that could not run reports why, and never reports clean.** `unchecked` ≠ `clean` and
  `not_covered` ≠ `not_found`; an ACMG check with no list read must say `checked: 0`, not zero
  mismatches. Each pass carries its own `warnings` for exactly this. **An empty list is the trap** —
  it is the one shape where "nothing was wrong" and "nothing was checked" render identically, so
  every empty collection this tier publishes needs a sibling field saying which it is.
  `clin_sig_conflicts` had no such field until enricher 0.5.2 gave it `clin_sig_not_checked`; a
  deployment with no ClinVar snapshot was reporting a cross-check it never ran, `would_publish: true`
  beside it. The `/check` passes carry `unreachable` for the same reason, and it is
  the second half of the rule below. Note the divergence from the enricher's own CLI: it suppresses `not_requested` (there it
  is the author's `--no-verify-clinsig` echoed back), and we must not, because here the switch is
  `REGISTRY_ENRICH_VERIFY_CLINSIG` and the publisher cannot see the server's settings. **And a skip is
  never a publish gate**: the reasons are all operator-side, and failing a publish over one would make
  a publisher answer for a deployment they cannot configure. Two more of these landed with 0.5.4, and
  both are worth reading as the same lesson at a different altitude: `unreachable_rsids` beside
  `unresolved` (S20 — a key with no position says nothing about whether anybody *asked*, and an
  unanswered request reported as an absence is indistinguishable from a fabricated rsID), and
  `gene_loci_not_checked` beside `gene_loci` (S24). The rule generalizes past collections: **a field
  whose value can be produced by two opposite histories needs a sibling that says which happened.**
- **A skip is not a gate, but a *transient* failure is not an authoring defect either.** The advice
  attached to a refusal has to name the right actor. `unresolved` under strict really does refuse a
  publish, so `would_publish` stays `false` — but when the cause is an Ensembl that never answered, all
  three standard remedies (provision a snapshot, allow egress, author coordinates) send the publisher
  after work on a variant that is perfectly findable. The verdict is unchanged and the *hint* changes:
  re-run. Check `unresolved_hint` before adding a fourth remedy to that message.
- **The two callers want opposite things from a full gate, so there are two lanes.** `/check` is
  interactive: `try_acquire`, `503` on a full gate, because queueing behind a paced run turns a fast
  rejection into a slow timeout. Publish is idle: `acquire_idle`, no deadline, deferring to
  interactive demand — nobody is waiting on it and a rejection costs a whole re-upload. A queued
  publish must wait **in the coroutine**; waiting in a worker would starve the pool `/check` needs,
  which is the opposite of yielding. Deference is at *entry* only; a running publish cannot be
  preempted, and pretending otherwise in a comment would be worse than saying so.
- **Catch the unavailability subclass *above* its parent, and give each independent source its own
  `try`.** Since enricher 0.6.2 (RM101, our S37) every pass raises its own type, with "the source could
  not be reached" as a **subclass**: `FrequencyUnavailable(FrequencyEnrichmentError)` and five siblings,
  plus `AcmgListUnavailable`, which predates them. So the adapters no longer catch client types at all —
  `services/enrich.py` imports `httpx` nowhere — and the hazard moved from *which* type to *what order*.
  A parent arm above the subclass arm swallows the outage and reports it as a structural note with no
  `unreachable`: nothing raises, nothing 500s, and a check comes back looking clean while the source is
  down. That is worse than the bug it replaced, and it is what `test_no_adapter_catches_an_unavailability_subclass_with_its_parent_first`
  walks the AST for. **The parent arm is not redundant** — it now means *the question was put and the
  answer is a problem* (a `variants.csv` that will not load, a strict refusal), which is a different
  thing to report. Upstream's own upgrade table missed this shape because it assumes one
  `except (PassError, ClientError)` tuple; filed back as **S38**.
  The history is worth keeping because it is why the guards assert the *field* rather than a `200`:
  through 0.6.1 a pass let its client's type through untranslated (`enrich_frequencies` carries no
  `except` at all; `enrich_literature` calls `esummary` inside a bare `try/finally`), so a gnomAD 503
  was a **500 from `/check`** — an endpoint whose entire contract is to report, failing over somebody
  else's outage. The `try` granularity is the other half: the three
  PGx passes shared one until 0.17, so an unreachable ClinGen discarded the PharmVar/CPIC and ClinPGx
  findings already collected — the rule `enrich_pgx` already applies between PharmVar and CPIC one level
  down. `LicenseRefusal` stays outside the legs, because a `declared_use` contradiction is one statement
  about the whole request. Two corollaries worth keeping: **a source with no live route is never
  `unreachable`** (ClinPGx's API was retired — its failures are skips with a reason), and where one
  exception type covers two histories, **never discriminate on the sentence** — a warning's wording is
  upstream's to change, and only the pinned catalogue is an API. `ClinGenError` was that case: chained
  `from` the transport error for a fetch, raised bare for an unparseable local table, so we read
  `__cause__`. 0.6.2 makes it a type (`ClinGenUnavailable`) and the `isinstance` is gone — read a
  *structured* member where one exists, which is also why `AcmgListUnavailable.skip` is honoured rather
  than flattened: `unreachable` and `no_reference` send an operator to different places, and only the
  first is an outage. **And a new report field is only half a
  fix**: `registry-client check` prints per-pass *findings*, so three passes that print no summary
  rendered an outage as `✓ would publish` with the reason sitting unread in the JSON. Anything that
  distinguishes "unchecked" from "clean" has to reach the renderer too.
- **Cache lanes: read the registry, never a list (0.24 / RM176).** `caches.CACHE_LANES` carries every
  snapshot lane with its three stages (`resolve`, `rebuild`, `ensure`), its `env_var`, its licence
  terms and — for each stage it lacks — the **reason** as a field. `pullable_lanes`, `gated_lanes` and
  every resolver in `services/enrich.py` derive from it, and `warm-caches` provisions through
  `prepare_caches`. A hand-kept list is what this replaced: ours had drifted by eight lanes, and the
  one that mattered was `acmg` — a setting we had, a pass that read it, and a provisioning command that
  never mentioned it, so a box reporting everything green had the ACMG check falling back to a page
  serving SF v3.2. **`REFERENCE_NAMES` stays ours and stays narrow**: naming a lane there is a claim
  that something on this box opens it, and a lane named there that nothing reads is how `constraint`
  came to trigger boot warnings about a file no pass would open. Three rules that follow. **The route
  is a property of the lane, never a flag** — a published lane is pulled, an unpublished one is built,
  and both refusals carry upstream's own sentence. **`ready` is tri-state**: a lane needing a workbook
  only the operator holds has not failed. And **`export_lane_locations` before provisioning**, because
  `prepare_lane` resolves with no argument and follows the lane's own variable — without it a pull
  lands where the running server never looks.
- **Nice values are one-way.** Raising a thread's nice is unprivileged, lowering it back is not, and
  anyio reuses its workers — so anything niced runs on a thread we create and discard
  (`lowpriority.py`). A `finally: restore()` here does not work and cannot be made to.

These upstreams are **unauthenticated and throttle by IP**. gnomAD publishes a 10-per-60s budget and
offers no API key at any price, so there is no quota to top up and no per-caller scoping — an
overspend throttles the whole deployment. `NCBI_API_KEY` is optional and only tightens NCBI's own
pacing; `PHARMVAR_API_KEY` gates a leg rather than pacing it, and it is personal to an account under
PharmVar's terms §2 — so on a public deployment third parties would query it on the operator's.
**Prefer the snapshot to the key for that reason**: since 0.5.1 a built PharmVar cache runs the leg
with no credential, and it is the one cache nothing publishes (the bulk data comes down under that
same key), so an operator builds it once. That is also why the concurrency gate is not merely a cost
control: it is the only thing holding our aggregate rate inside a limit we cannot buy our way out of.

---

## The caching proxy (0.25) — what this box holds, other people can borrow

**A thin client's cache miss is answered by the registry, and the registry's own miss is answered by
the remote source.** The enricher's snapshot lanes are artifacts running to tens of
gigabytes, and every consumer that is not a provisioned server — a module author, an agent, a
`just-module-creator` session, a `just-dna-lite` install — has none of them. This box has them. So the
authoring half of the ecosystem, which was reachable only by whoever had already downloaded the
caches, is reachable through here: `GET /caches` says what is held, `POST .../derived` hands back the
enriched tables, `POST /drafts` runs the drafters, and `/hint/*` answers the lookups.

**It is an authoring and publish-time surface, and saying so is what keeps it one.** Annotation at
install time stays self-contained — a compiled module's parquets carry what a join needs — and if that
ever stops being true this whole layer has become a runtime dependency for every install, which is not
what it is for.

- **Drafting is still authoring-side and this service still drafts nothing of its own.** The recorded
  position above was about a `registry upgrade` sweep and it stands: a re-draft is not a catalog
  migration, and nothing here re-drafts a published module. What `POST /drafts` does is *rent the
  drafters out* — and it is stateless for exactly the reason that section gives, that a re-draft over
  an existing spec appends corrected rows beside the ones they supersede. The server holds nothing
  between calls, so it cannot do that to anyone across two of them.
- **Snapshot-only is the default on every one of these, and `offline=true` is the free tier.** A
  request path never downloads (a missing snapshot is a well-defined error, not a five-minute pull
  inside a handler), and an answer served from a snapshot costs the deployment nothing. That is the
  whole product, so it is what an anonymous caller gets.
- **The meter is per upstream and the units are not exchangeable.** `pacing.PaceLedger` is the third
  layer under `RateLimiter` (one caller's request rate) and `EnrichmentGate` (the process's
  concurrency): it answers *how much of a budget we cannot buy has this caller spent today, against
  which upstream*. One fungible egress counter would let a caller spend gnomAD's unbuyable
  ten-per-minute allowance at the price of a three-per-second eutils call. gnomAD's allowance is two
  orders of magnitude below the others and the reason sits beside the number.
- **The decay is a multiple of the upstream's own spacing, read off the client that paces it** — not
  a constant. `EutilsClient` picks 10/s with `NCBI_API_KEY` set and 3/s without, so a literal in
  `UPSTREAMS` describes the wrong deployment half the time. `PaceLedger(intervals=…)` is filled at
  boot from the live clients; the constants are the fallback.
- **The cooldown is on the allowance, not the tier.** Carrying the tier down one step per clean day
  was the first design and has a hole a caller can sit in forever: spending exactly twice the
  allowance every day ends each day at tier 1, carries 0, and returns the whole free tier every
  morning. Halving the allowance per consecutive over-day ratchets, and one clean day restores it.
- **A remedy is per upstream, and three of the four are not "get a key".** gnomAD sells none at any
  price, NCBI's paces whoever holds it (so ours cannot help a caller and theirs must not be sent
  here), OLS4 and HGNC issue none. The only remedy true everywhere is the point of the release:
  provision the snapshot, or run the enricher yourself. A generic "obtain an API key" is a lie the
  caller can check.
- **Use the batch, and know why.** An online *single* variant lookup egresses unconditionally —
  `_check_rsid_currency` puts every rsID to dbSNP whatever the snapshot said, because merge status has
  no snapshot in this tree. `POST /hint/variants` runs the offline pass over every key at zero cost
  and goes online only for the misses. A test asserts zero charge **and** zero egress with the socket
  tripwire armed; if that stops holding, this is a proxy and not a cache.
- **No filesystem path leaves the process, on any of these routes** — and since enricher 0.7 most of
  that is upstream's doing rather than ours. We filed it as **S93**: `checked` held an absolute
  snapshot path and a finding interpolated the same path, so a host had to scrub two places and
  re-audit on every new field. Upstream **split** them instead — `checked` is now labels, `snapshots`
  is the label → path map, and their docstring calls it *"the one place a path lives in the payload,
  so a host that does not want to publish its layout drops this field and audits nothing else"*.

  So the handling **inverted rather than grew**: report `checked` as-is, never serialize `snapshots`,
  and keep exactly one scrub, for the reason upstream names — a duckdb error's own first line
  contains the file it could not read, kept deliberately as evidence. `DraftReport.path` is still
  absolute and is still answered by reporting `csv_name`. Assert at the *rendered* body using paths
  this box actually resolves, not a list of likely-looking prefixes.

  **The general lesson is the one that cost the red test**: a filing that gets adopted changes the
  meaning of a name without changing the name, and a passthrough fix would have left us scrubbing a
  field that no longer needs it while serializing the one that does.

  **And a version floor cannot express a change that landed after its number did.** Ours is
  `just-dna-enricher>=0.7.0`; the split arrived *after* 0.7.0 existed as a version, so an install can
  satisfy the floor and still hand us the old shape. There is no floor to write. So `served_from`
  **withholds** an entry that looks like a path rather than passing it on or mapping it back — the
  first leaks, and the second invents a vocabulary of ours inside a field that is upstream's and is
  wrong for any snapshot this deployment does not configure. Nothing is lost: *a snapshot answered*
  is already said by the labels beside it and by the hint's own findings.

  **Generalise on the way out, not while documenting.** Every rule in this section was already a
  habit somewhere in this tree, correct, in the file where it was invented — `test_ui.py` had both
  denominator floors before any newer test missed them. The moment to catch that is not while writing
  documentation; it is **while writing the second instance of something**, asking what the first one
  knew. Neither of the two sessions that found all of this did that, and both wrote the second
  instance beside the first.

  **A note that schedules an action must name a *condition*, never a time — and the condition has to
  be one somebody can go and check.** "A condition you cannot query is a schedule wearing different
  words" is the sharper form, and it is the test to apply to your own replacement: the
  `positionally_joinable` facet passes it because *"has the last pre-0.6 version left this catalog"*
  is a query. Where a condition is only half queryable, say which half — the `compiled_by` note below
  is honest that the catalog side is answerable and the "what clients still hold" side is a
  judgement, because a condition that reads crisp and is not is the same trap one layer in.

  **And write the query next to it, in a form that runs as given.** There is a ladder here and every
  rung costs the same thing — the check not happening:

  1. naming a **date** ("at the next major cleanup");
  2. naming a condition nobody can **query** ("no install we support lacks it");
  3. naming a queryable condition and **not writing the query**;
  4. writing a command that **does not run as given** — a placeholder to substitute, a continuation
     to unwrap, `python` where the box has none.

  We have hit rungs 1, 3 and 4 in this repo alone, the last of them in the commit that added the rule
  about rung 3. Both live conditions now carry a command run verbatim from the repo root before being
  written down, with an explicit interpreter and on one line.

  **Mark a command you have *not* run as unrun.** A command you executed and a command you believe
  works are different artifacts and the prose cannot tell them apart — the same argument that makes a
  quoted passage carry its provenance, applied to a shell line. And note what a probe answers about:
  `uv run --isolated --no-project --with '<pkg>==<floor>'` answers about a **declaration**, so it is
  the tool for *may I delete this guard* and the wrong one for *why is this failing here*, which needs
  the project's own interpreter.

  Where only half a condition is answerable, say which half the command settles and which is left as
  a decision.

  **And check the probe before believing it.** Sweeping this repo's docs for flags that no longer
  exist, the first pass reported *"3 flags exist, 64 named in docs are absent"* — the traversal never
  descended, because `TyperGroup` is not an `isinstance` of `click.Group` in the installed click, so
  it read the two root commands and stopped. Three flags across two full CLIs is not a finding, it is
  a broken instrument, and reporting it would have manufactured sixty-four phantom defects for
  somebody to chase. Fixed (duck-type on `.commands`), it reports 109 real flags and **seven** doc
  mentions that are not ours — ruff's `--fix`, uv's `--isolated/--no-project/--with`, the enricher's
  `--no-verify-clinsig`, and the triage scripts' `--pending/--next`, all correct in context. A sweep
  whose count is implausible is reporting on itself; sanity-check the denominator before reading the
  numerator.

  **And put the sanity check *in the test*, as a denominator floor.** A subset check over an empty set
  passes and proves nothing, which is what an enumeration of a **foreign** symbol renders as when the
  import moves rather than when a name is renamed. Three guards here compared our rosters against
  `hints.DERIVED_TABLE_MODELS`, `draft.DRAFTABLE` and `cli.PANEL_SOURCES` with no floor, so an emptied
  import read as *"everything upstream reads is recognized"*. They assert the count first now, well
  under today's numbers. `tests/test_ui.py` already did this in two places (`assert routes` and
  `assert checked >= 30`), which is why the console's guards never had the problem — the pattern was
  in the tree and only the newer tests missed it.

  The failure this prevents is the worst on the ladder because it is the only one that produces
  *work*: rungs one to four end in silence, which gets ignored, while an instrument reporting on
  itself produces a plausible list that somebody sets about fixing.

  **A floor is not always a count, so do not sweep for one.** Three protections are equivalent and a
  grep for `assert len(...) >=` finds only the first: an explicit count; an **adjacent exact
  assertion** over the same set; and **direction** — a foreign set on the *left* of a `<=` fails when
  it empties, so `REFERENCE_NAMES <= cache_lanes()` is already safe and `PANEL_SOURCES <=
  DRAFT_SOURCES` was not. Triage by asking *"if the foreign enumeration came back empty, does this
  still pass?"*, never by pattern.

  **Two more shapes, both of which make an assertion vacuous by moving the haystack rather than the
  count.** Where a denominator comes from *splitting text*, floor the **split**: the marker exists,
  and the block is neither empty nor the whole file — a heading that moves turns the haystack into
  everything, and every name is then "present". The inverse is an **absence** assertion: `X not in
  body` passes on an empty body, so show the haystack is the answer you asked for before asserting
  what is missing from it. A count sees neither, because the block is the wrong *size* rather than
  the wrong length.

  **And for a *search*, the floor is an anchor rather than a count** — you cannot count what is
  outside the search path. When a sweep reports a name as undefined, look up the one you are most
  confident about first: if the anchor also comes back undefined the instrument is wrong, and if it
  resolves the finding may be real. `just-module-creator` lost two names to a search aimed at
  `src/` when the subject was a sibling subdirectory, and "not found" was a well-formed answer to a
  badly aimed question with nothing in the output to distrust. "Delete this when the
  floor moves to 0.7", "retire at the next major cleanup", "when RM44 lands, delete the facet and the
  test" — all three of those existed in this ecosystem, and they share a tell: whoever is standing
  there on the named day will simply obey. A note naming the fact it rests on gets *checked* instead,
  and the check is what catches the case where the fact never became true. Ours was the worst of the
  three, because it named the action *and* would have removed the guard together with the test that
  would have caught the regression; the `positionally_joinable` facet is the model to copy, since it
  says it retires "when the last pre-0.6 version leaves a catalog, **not on a release**".

  **A capability check comes out when its fact goes unconditional, never because a floor appears to
  guarantee it.** **And we minted one of these ourselves**: `pyproject.toml` was stamped `0.25.0` at
  03:45 and seven of the release's nine client methods landed at 03:57 and 04:09, so commits exist in
  this tree carrying that version with two of the nine. A version stamped mid-branch names a
  different surface at different commits, which is the "one release number, several answers" problem
  minted locally rather than inherited. Stamp at the cut, or expect a consumer pinning from a source
  checkout to get whatever that checkout happened to hold.

  `served_from`'s path filter will look deletable the day 0.7 is cut, and it is not:
  a floor that was never able to carry the fact does not start carrying it at a release, and there is
  no version to raise the pin to because the split has no version of its own.

  **One release number, three different answers depending on which install asks** — in a sibling's
  source tree, in the wheels built from it, and on PyPI. `layout.sidecar_key` was in all three states
  at once on the day it landed, and a note here named it as though it were available. Check the
  *installed* symbol before writing advice about it, and probe the **behaviour** rather than the
  symbol's presence where the two can differ: `hasattr` is the sentence-matching rule wearing an
  import.
- **`lane_status()` composes `lane_presence()`; it does not resolve a second time.** Two projections
  of one lane registry is the drift `CACHE_LANES` and `6ddd430` each exist to end. And `absent` is
  three states, not one: `partial` (a directory holding something that is not a readable snapshot) is
  the one provisioning *refuses* to act on rather than overwriting, so reporting it as absent tells an
  operator to run a pull that is going to decline.
- **An unregistered rate-limit category is silently unlimited.** `RateLimiter.allow` returns `True`
  for a category nobody put in `CATEGORIES`, so a route that egresses must land its bucket in the same
  commit as the route. `hint` and `draft` are there; the next one has to be.
- **`client_cli` may import nothing from `services/`.** Those modules import `just_dna_compiler` at
  module level and that tier is an optional extra, so one such import turns `registry-client` into an
  `ImportError` on every base install. Shared names live in `specfiles`. A guard walks the
  module-level imports of `client.py` and `client_cli.py`; it checks *top-level* imports only, because
  a guarded `try/except ImportError` inside a function is the documented exception and is how
  `content_signature` reaches the compiler tier without requiring it.

---

## Former names — retired, not forgotten

**"Marketplace" is a former name of this project.** It is recorded here rather than merely deleted,
because a purge with no note is how a retired name comes back: the next person meets it in a legacy
path or an old manifest, finds nothing explaining it, and reintroduces it as though it were current.

| former | current | status |
|---|---|---|
| package `just-dna-marketplace` | `just-dna-registry` | renamed in 0.9.0 |
| host `module-marketplace.just-dna.life` | `module-registry.just-dna.life` | retired; the old name is a legacy domain only |
| on-disk `just-dna-marketplace/` | `just-dna-registry/` | renamed; a symlink keeps the old path resolving for siblings that hardcode it |
| `compiled_by="marketplace-server"` | — | **deliberately kept.** It is baked into every published manifest and clients verify against that literal, so renaming it would invalidate the trust check on immutable data. Not a leftover |
| default DB `data/marketplace.db` | `data/registry.db` | renamed in 0.9.0; `validate_db_path` still detects the orphan, so the old name must stay spelled out in `startup.py` |

"Store" remains the app-store **UI** in the webui; the registry is this backend. Neither is "the
marketplace".

## Deployment modes (0.12)

`REGISTRY_MODE` is `prod` (default) or `test`. Two deployments of one image: production is
`module-registry.just-dna.life`; the **polygon** is `module-polygon.just-dna.life`, default port
+100 (8100). An unknown mode **refuses to boot** — a typo that resolved either way is invisible from a
running server, and one direction arms a delete endpoint on production data.

- **The mode is a server concept only. Never gate the client on it.** `RegistryClient` always exposes
  `delete_version`/`delete_module`; a client cannot know a host's mode before asking, and a method that
  silently vanishes depending on where you pointed it is worse than a documented `405`.
- **But the *admin CLI* is not the client, and it has to be told.** `REGISTRY_MODE` in a unit file or
  compose env reaches the server process and **not** an operator's shell, so an ops command run by hand
  on the polygon read the default (`prod`) and applied production's rules to the test box's catalog —
  0.17's own step 2 died on `test_data_on_prod` that way. `--mode` is on the **root callback** since
  0.17.1 (`registry --mode test upgrade …`), sharing `_apply_mode` with `serve --mode`, so a new ops
  command inherits the *flag* without doing anything. The `mode=… db=…` **echo is not inherited** — it is
  an explicit `_echo_mode(settings)` call, today on `revalidate` and `upgrade` only, because those are
  the long catalog-wide ones. Add it to any command whose behaviour the mode changes: a mode is invisible
  until a rule fires, and the rule fires minutes in.
- **Why the mode exists**: a published version is immutable *and* its data is claimed by a
  name-independent `content_hash` that **`yank` does not release**. So without a delete verb every
  rehearsal permanently burns a version number and the right to publish that data under any other name.
  A test subtree inside production cannot fix this — the claim is global, and only a hard purge frees it.
- **Production refuses test data at every door** (publish, namespace claim, `issue-key`), and the two
  identifier spellings differ: namespaces/handles take `test-`, module names take `test_` (they forbid
  hyphens). One flag, normalised per identifier — never configure it twice.
- **Since 0.14 that refusal is a default, not a ban: `allow_test_data=true` proceeds anyway.** It is a
  request field on publish/import, a body field on the namespace claim, and `--allow-test-data` on
  `issue-key`. The default stays "refuse" because the failure it prevents is silent and permanent — a
  mistyped namespace spends a version number and a global `content_hash` that only a purge frees —
  while the cost of asking explicitly is one parameter. **An accepted override always warns**
  (`testdata.accepted_anyway`), on the response and in the log, because production is then holding
  test-prefixed data and nothing else would say so.
- **The override and `purge-test-data` are aimed at the same prefix, and that is the sharp edge.**
  Data deliberately kept on production under a `test-` name is data a routine purge would remove. The
  purge lists before it deletes; that listing is the moment to notice. Say this whenever either is
  documented — a reader who learns only one of them has the dangerous half.
- **That guard is prospective only.** It does not clean what is already there, so `purge-test-data`
  stays necessary. Do not describe one as making the other redundant.
- **And prospective means it has nothing to say about a re-publish of data already in the catalog.**
  `upgrade_version` passes `allow_test_data=True` (0.17.1): the module is already published under that
  exact name, the identifier and its global `content_hash` are already spent, and the successor is a
  PATCH of the same identity — so there is nothing left to prevent. Refusing there did not protect
  anything; it made a catalog-wide re-baseline impossible to finish, with no flag to pass. Any future
  internal re-publish path inherits this question: ask whether the identifier is *arriving* or *already
  admitted*, because the guard is only about the first.
- **A rule written for one instance has to ask which one it is running on.** The listing hid
  test/sandbox namespaces from every tab but `test` on *both* deployments, so on the polygon — where
  those spaces are the whole catalog — the default listing, `group=all` and `?q=` all answered
  `total: 0` on a box `/health` counted as non-empty, and two unattended authoring runs concluded
  their rehearsal publish had failed (S17, fixed in 0.21.1). Nothing was broken: it is a
  single-catalog UI policy ("a sandbox space is noise in the default tab") applied to a two-instance
  world, and `settings.is_test_instance` was already read at the publish gate, in the CLI, at the
  delete router's mount and in the test-data check. The listing was the one place that never asked.
  **Two things generalise.** A `group=test` that also meant "everything" on the polygon was the
  tempting symmetry and would have been wrong — a *named* tab must mean the same thing on both
  instances or server-owned membership stops being worth anything; only the **default** may differ.
  And **a description is part of the behaviour**: `all`'s label said "test/sandbox spaces excluded",
  so fixing the query alone would have left a UI captioning a complete list with a sentence denying
  it. `groups_for()` serves the description the instance earns, which is also why the client is told
  to render what it is served rather than bake the string in.
- **And when an argument for publishing something rests on a premise, re-check the premise per
  instance.** `catalog_counts` justifies four unauthenticated numbers on `/health` as *facts a
  reader could already enumerate through `GET /modules`* — false on the polygon for as long as the
  listing excluded everything it held, where `/health` was the **only** route saying the box was not
  empty. The repair was to the listing, not the endpoint; the counts were right and were the one
  thing telling an author their publish had landed. The docstring now carries the standing
  instruction rather than just the correction, because it is the claim that licenses the endpoint.
- **A read-only pre-flight must predict the operation it precedes.** `GET /namespaces/{ns}` reported
  `valid: true` for a name the claim then refused (S6). It now carries `requires_allow_test_data` and
  a warning instead — *not* `valid: false`, because the name is genuinely claimable with the flag, and
  flipping the field would be the same contradiction rewritten backwards.
- **Anything destructive snapshots first** (`backup._guard` in the CLI). The rolling index only counts
  up and never overwrites — it is not a ring buffer, and taking a backup must be the one safe act here.
- **A new route on either mode needs a `RegistryClient` method and a row in the parity table.** The
  guard enumerates *both* modes precisely because a mode-gated route would otherwise ship unwrapped.

---

## Spec layout (0.17) — the flat one is canonical, everything else is transport

The compiler reads one flat directory, so that is the spec. `specfiles.plan_layout` normalizes an
upload onto it and `services/publish.normalize_spec` applies the plan — called from `_finalize` and
from **both** dry-run workers, because a dry run that normalizes differently from the publish it
predicts is worse than one that does not normalize at all.

- **The folder convention is ours; the format says nothing about folders.** `derived/` holds the
  machine-written tables (`resolution.csv` + the fact sidecars) on the wire, in both directions. It
  exists because a spec mixes two provenances and marks neither — and `sources.csv` is genuinely
  both, the author's rows with the enricher's merged in.
- **`overrides.csv` is authored, hashed, and the first file to join `SIGNATURE_INPUTS` since it was
  written (0.24 / RM124).** It is one row per correction the curator is making to a *derived* value,
  with `reason` required, which is what makes it a record rather than a knob. Recognizing it was
  upstream's one deadline item, and the reason is worse than for an ordinary table: dropping an overlay
  row on a re-publish silently restores the value the author rejected, and the module goes on compiling
  green. `content_signature` covers its **value cells only** (S87/RM180 excludes
  `reason`/`decided_by`/`decided_at`), so rewording a justification does not mint a fresh
  `409 duplicate_content` claim while changing what the overlay does correctly moves the identity. **Do
  not compute that hash here** — `integrity.content_signature` owns which columns are identity, and a
  second reader of that rule is the drift `RENAMED_ON_UPLOAD` exists to end.
- **It is safe only because `SIGNATURE_INPUTS` is entirely root-level.** Nothing that may live in
  `derived/` is in `content_signature`, so splitting a module cannot move its identity or its
  `409 duplicate_content` claim. A test asserts the disjointness. **Check it again before putting
  anything new in that folder** — the day a signature input becomes splittable, a downloaded module
  stops being republishable as itself.
- **Liberal in, strict out.** Any subdirectory is accepted on the way in (`metadata/`, `enriched/`,
  whatever a producer already ships); only `derived/` is ever emitted. Two exceptions: `logs/` and a
  top-level `*.log` are never moved, because the manifest attests those paths verbatim, and
  unrecognized files stay exactly where they are, because the compiler tolerates unknown files as a
  contract (S16 upstream) and a rule invented here would break it.
- **One root name from two paths is `422 ambiguous_spec_layout`, never a guess.** Only the author
  knows which copy is current, and picking one silently publishes the wrong table under a signature
  that looks perfectly valid.
- **`MODULE.md` is renamed to `README.md` on upload, not merely tolerated.** `README.md` is the one
  name the card reads (S5), and `MODULE.md` is what this project advised for two releases and what
  `just-module-creator` still writes — all 26 sample zips in `data/input/` carry one. Renaming is the
  difference between a rename we made and a republish every author pays for. Both present → the real
  name wins and the legacy file is carried untouched; overwriting prose the author wrote with prose
  they did not is the one thing this pass must never do.
- **Renames live in one map (`RENAMED_ON_UPLOAD`), and since 0.17 the sidecar entry is *derived*
  rather than written down.** The second entry is `sources.csv` → `licensing.csv`, computed from
  `just_dna_format.layout.SIDECAR_SPELLINGS` + `DEPRECATED_SPELLINGS`. **It pointed the other way in
  0.16.2, and the flip is the lesson**: under 0.5 our compiler read only `sources.csv`, so the ledger
  every current tool writes was dropped from the compile — not a missing file but a **false facet**,
  with `manifest.sources` holding the enricher's own Ensembl row while a module whose upstreams forbid
  sale advertised `licensing.commercial_use: true`. Under 0.6 the compiler reads both, prefers
  `licensing.csv`, and warns that the old name goes at format 1.0. Left pointing backwards, the same
  map would have stamped a deprecation warning into every published (and immutable) manifest and
  stored the one spelling that stops being read at all.

  **And since compiler 0.6.6 (upstream RM107) a duplicate `(source, layer)` row in that table is an
  error in both `validate` and `compile`, where it used to pass silently.** The pair was free to carry
  opposite `commercial_use` in the one file the compile gate reads, which is the same class of false
  facet as the 0.16.2 flip. Consequences to hold together: a spec that published before can now be a
  `422`, and a `--force` recompile of such a published version fails with nothing left to fix in place —
  so `upgrade --dry-run` before any forced sweep. The enricher's licensing writer collapses the pair but
  keeps the **last** row, so where two rows disagree the choice is the author's, not a tool's.

  So: **never hardcode a spelling here again.** Upstream owns which names exist and which are
  deprecated; restating that is precisely how the two got out of step. **Three things must hold before
  adding a name to that map by hand:** the two names are one table with one row model upstream (not a
  guess at intent, which is what keeps `_README_LOOKALIKES` a warning); the row model is
  `extra="forbid"`, so a schema drift fails loudly rather than publishing something wrong; and the
  destination is outside `SIGNATURE_INPUTS` and inside `RECOGNIZED_SPEC_FILES`, so the rename can
  neither move a `content_signature` nor be dropped by the `revalidate`/`upgrade` rebuild. A test
  asserts the last one over the whole map.

  **Both spellings present is a `422` since 0.17**, matching upstream RM49 — and note this is *not*
  the same answer as the readme's. `layout.resolve_sidecar` **raises** on two copies of one fact
  table, so warn-and-prefer would no longer produce a publish at all, only a `SidecarCollision` with
  our own upload as the cause. The readme keeps warn-and-carry because an extra markdown file makes
  the compiler do nothing, while overwriting authored prose is unrecoverable.
- **The split used to be unable to separate what a downloader never received — fixed by 0.6, in
  0.17.** The manifest had fields for `logs`, `logo`, `provenance` and the authored `inputs` and none
  for the derived CSVs, so nothing attested them and a client had no name to ask for. Filed as **S26**
  and answered by `manifest.derived` (RM49) plus `manifest.readme` (S5): `download(include_inputs=True)`
  now fetches the sidecars and the readme and hash-checks them, which is what makes a downloaded module
  recompile where it lands — the compiler never fetches, so `resolution.csv` has to travel with it.

  Two things from that episode survive it and are worth keeping. **A split can only separate files the
  downloader actually receives**, so `download(layout="split")` still creates `derived/` only when
  something lands in it — the folder is a consequence of the manifest's contents, never a promise made
  ahead of them. And the second half of S26 is still upstream's and still true: the compiler discovers
  authored tables at the spec root only, which is what keeps this whole layer transport-only.

---

## The console (0.23) — a consumer that lives in this tree

`src/just_dna_registry/ui/` is one HTML shell, one stylesheet and one bundled script, no framework,
served two ways: `mount.mount_ui` at `/ui/` on the app, and `standalone.serve` behind
`registry-client ui`, a stdlib HTTP server that proxies `/api`, `/health` and `/docs` to a remote
registry (the API sets no CORS policy, on purpose, so a local page needs something in between).
**The script is built, not written**: the sources are TypeScript under `console/` at the repo root
(`npm ci && npm run verify`; `npm run watch` while editing), esbuild bundles them into
`static/app.js`, and the bundle is committed so Python, the wheel and a deployment need no Node.
Never edit `static/app.js` by hand. `tests/test_ui.py` proves the committed bundle is built from the
sources **when Node is on the box and skips otherwise** — so a change under `console/src` with no
`app.js` diff beside it is a stale bundle however green the suite was; look for the pair in review.
The rules that keep it a consumer rather than a second API:

- **Nothing the console serves enters the OpenAPI schema.** Every handler in `mount.py` is
  `include_in_schema=False`, because `tests/test_client_sdk.py` enumerates `app.openapi()` and fails
  on any route without a `RegistryClient` method — and a page is not a route. `/docs` is the
  precedent. If the console ever needs an endpoint the API lacks (a facet-values route is the obvious
  candidate), it is added *as an API route* with a client method and a parity row, not as a page-only
  helper.
- **Every API path the page fetches lives in one `ROUTES` table in `console/src/api.ts`**, and
  `tests/test_ui.py` checks each template against `app.openapi()` in both modes and refuses an
  `/api/v1/…` literal in any other source file. A path the page fetches that the server does not
  serve is a panel that renders "nothing here" forever — the failure that looks most like working.
  The first `tsc` run over the port found the JS version had carried two `version` keys in that
  table (the ops endpoint and the module-version path); the object literal kept the last, so the
  header had been fetching a module template as the server's version. A duplicate key is a type
  error now.
- **`console/src/types.ts` mirrors `models/api.py` field for field, and a test holds the two equal.**
  Every response shape the page reads is an interface there; a field the server adds fails the
  suite until the page knows it, which is the SDK parity idea applied to the page's types. Names
  only: the annotation mapping is a reading of the same source and a wrong type is `tsc`'s to find.
  Add the interface when you add the model; the generator that drafted the file is a one-off
  `uv run python` over `model_fields` and is cheaper to rewrite than to keep.
- **Escape first.** Readmes, changelogs, descriptions, review notes and display names are publisher
  content. The markdown renderer's first act on a line is `esc()`, no raw HTML passes through, link
  targets are `http(s)` or fragments only, and server URLs go into `src` attributes and nowhere else.
  A test pins the escape-first shape. Do not swap in a markdown library that passes HTML through by
  default; that is the one property a library would cost.
- **The check renderer reads every "unchecked" sibling**, and a test names them. This is *A pass that
  could not run reports why* one tier up: the CLI renderer once printed `✓ would publish` over an
  outage because a field reached only the JSON, and a page is a renderer too.
- **Ask `/health` for the mode; never guess it from the host.** The delete controls render only when
  the instance said `mode: test`, which is consistent with *never gate the client on the mode* —
  the page asks the host first, which is what that rule requires of a client.
- **Facet suggestions come from the loaded page.** There is no facet-values endpoint; inventing one in
  the page (by paging the whole listing, say) would spend the anonymous search budget on every load.
- **The proxy forwards a whitelist, not everything.** `Authorization`, `Content-Type` (the multipart
  boundary lives there), `Accept`, `X-Format-Version` in; status, body, `Content-Type`,
  `Content-Disposition`, `Location` and the three version headers out. Cookies, `Origin` and `Host`
  stop at the proxy. `--token` injects a bearer only where the browser sent none, and binding that to a
  non-loopback host needs `--expose-token` said out loud — the socket is then worth what the key is.
- **`Element.replaceChildren` takes nodes, not arrays.** An array renders as its `toString()` and a
  `null` as the word "null"; the first screenshot of the console was a row of comma-joined URLs. Use
  the `put()` helper, which flattens and drops nulls.
- **The static files ship in the wheel** — `uv build` includes non-`.py` files under `src/`. It was
  checked (`unzip -l`), and a release that moves the static dir needs it checked again.

---

## Manifest & integrity (see SPEC §4–§6)

- The `manifest.json` is the contract and the source of truth. Registry-level fields (`namespace`,
  `version`, `owner`, `license`, `published_at`, `canonical_id`) are filled by **this service** on
  publish; compile-time fields come from `compile_module()`.
- **All hashes are SHA-256, lowercase hex, prefixed `sha256:`.**
  - `inputs[].sha256` — over raw input bytes (no normalization), byte-reproducible by any downloader.
  - `artifact.files[].sha256` — over the concrete written bytes (parquet is **not** deterministic
    across polars/arrow versions, so pin `compiler_version` + `ensembl_reference`).
  - `artifact.digest` — Merkle root: JSON array `[{"name","sha256","size"}, ...]` sorted by `name`,
    serialized with sorted keys and no whitespace, then hashed. This is the version's **byte**
    identity, *not* its content identity.
- **`artifact.digest` names bytes; `content_signature` names data. Never use the digest to ask "same
  module?"** A module that authors no `sources.csv` gets a fresh one from the enricher on every
  compile, with `fetched_at` stamped at second resolution — so two compiles of byte-identical inputs
  produce different digests whenever they straddle a second, which is most of the imported corpus.
  That is the digest doing its job (the bytes really did differ), and it is why the publish gate and
  `409 duplicate_content` key on `content_signature`, which is invariant across it. Upstream answered
  the same report as their S7 and fixed the same conflation in `docs/SCHEMAS.md`; ours outlived it
  until 0.16.1, where a test asserting digest equality across two publishes of one spec turned out to
  be a coin flip on how long the compile took.
- **`compile_success` is trustworthy only when this server compiled it** (`compiled_by ==
  "marketplace-server"`). Treat foreign `compiled_by` or `false` as untrusted.
- **A manifest flag scoped to one file is not a verdict about the module.** `fully_resolved`,
  `resolution_mode` and the VRS counts all describe `variants.csv` **only**. A module without one gets
  `fully_resolved=True` from an `all()` over an empty list, and reading that as trust is how the
  catalog spent 0.11.x advertising PGx modules that join to no VCF as fully-baked (`db/facets.py`).
  Before any new facet leans on a compile-time flag, ask what it quantifies over and what an empty
  quantifier means — a table-only module is the case that finds out.
  **`stats.genes` was the same lesson at a second field, and it was upstream's to fix (RM121, adopted in
  0.20).** It quantified over `variants.csv` alone while `Stats`'s own docstring said *derived from the
  spec*, so a module led by `haplotypes.csv` or `diplotypes.csv` published `genes: []` however many rows
  named a gene — and `db/repository.py` feeds the gene side table from exactly that field, so `?gene=`
  could not return the modules it most obviously exists for. Compiler 0.6.6 unions the column over every
  authored gene-bearing kind. Note what this cost us to find: nothing here was wrong, so nothing here
  failed, and the symptom was a facet quietly returning less than it should. **A field you only read is
  still a field to ask "over what?" about.** **Positional joinability is the
  separate question**: rows with no `chrom`+`start` match nothing in a VCF, it is legal and stays a
  warning in both modes (compiler 0.5.3), and it must never become a publish gate — the remedy is a
  compiler change (upstream RM43), **which shipped in 0.6**: the fill places rsID-keyed positional rows
  from `resolution.csv`, so the modules this warned about now join.
- **That facet reads counts since 0.17, and a warning *string* only for what predates them.** RM44 and
  S31 landed in format 0.6: `resolution_subjects` is the denominator `fully_resolved` quantifies over,
  and `positional_rows`/`positional_rows_placed` say how many of how many rows join to a VCF, where the
  sentence only ever said *some do not*. `db/facets.positionally_joinable` is the preferred read.

  **The instruction this file used to carry — "when RM44 lands, delete the facet and the test" — was
  wrong, and following it would have restored the defect 0.11.3 fixed.** Already-published artifacts
  carry neither counter, so for every version compiled before 0.6 the warning is still the only record a
  reindex can see once the spec directory is gone; deleting it would silently re-grant trust to exactly
  the modules that join to nothing. Upstream's integration note says the same — keep the fallback, add
  the fields as the preferred path. It retires when the last pre-0.6 version leaves a catalog, not on a
  release. Two rules while it lasts: **never widen the match** (only that fragment is frozen upstream;
  the sentence around it is free to improve), and keep the test that drives a real publish through the
  real compiler — an import proves the two spellings agree, not that the warning still fires.

  Two consequences to expect rather than treat as regressions. **The reference PGx example's verdict
  flipped `False` → `True`**, because RM43 places its 106 rows; the module changed nothing and the
  compiler learned to do what the warning complained about. And the negative case is now a hand-written
  fixture (`tests/test_specfiles.py::_publish_unjoinable`), because nothing in the upstream corpus is
  unjoinable any more — left to the corpus, that half of the facet would quietly stop being tested.

  **Adopting 0.6 re-judges nothing already stored**, which is why 0.17 ships no trust migration where
  0.11.3 needed one: the pre-0.6 branch is the 0.5 rule unchanged, asserted exhaustively over the
  24-shape pre-0.6 space in `tests/test_format_06.py`. Verdicts move only as versions are recompiled by
  `registry upgrade`.
- **Immutability + yank**: never mutate a published version's bytes. Yank sets `yanked=true` (drops it
  from default listings and `latest`) but keeps the manifest + artifact fetchable so existing installs
  keep verifying. Un-yank is allowed.
- Prefer **content-addressed storage** (`artifacts/sha256/<digest>/…`) — dedup and immutability for free.

---

## HuggingFace / fsspec access (storage backend)

**Never use `huggingface_hub.snapshot_download`.** It duplicates data into HF's blob store
(`~/.cache/huggingface/`) then copies/links to `local_dir` — wasteful and unreliable. Use **fsspec**
via `HfFileSystem` for direct, file-by-file transfers, which also keeps the backend swappable (S3, GCS,
HTTP) with minimal change:

```python
from huggingface_hub import HfFileSystem, get_token

fs = HfFileSystem(token=get_token())
for remote_path in fs.ls("datasets/org/repo/data", detail=False):
    if remote_path.endswith(".parquet"):
        fs.get(remote_path, str(local_path))
```

Never hardcode HF repo IDs or the Ensembl reference repo in Python — thread them through config
(Pydantic settings / env), mirroring the `modules.yaml` conventions the pipelines use.

---

## Test Generation Guidelines

- **Real data + ground truth**: use actual source data, auto-download if needed, compute expected
  values at runtime rather than hardcoding them.
- **Deterministic coverage**: fixed seeds or explicit filters; representative *and* edge cases.
- **Meaningful assertions**: prefer relationships and aggregates over existence-only checks; prefer
  set equality (`assert set_a == set_b`) over count checks.
- **Verbosity**: run `pytest -vvv`. Keep `pytest` in the workspace/dev dependencies.
- **Docs**: put new markdown (except `README`/`CLAUDE`) in `docs/`.

**Service-specific tests to write** (SPEC §13):
- Contract test per endpoint. `finalize` with an invalid spec → `422` carrying
  `ValidationResult.errors`; re-publishing an existing version → `409`.
- Integrity round-trip: publish → tamper one artifact byte → client verification detects the
  `artifact.digest` mismatch.
- Manifest correctness: `inputs[].sha256` equals `hashlib.sha256` of the source CSVs; non-empty
  `artifact.files[]`; `compile_success == true`; `stats.genes`/`categories` match a fixture.

**Avoid** these AI-generated anti-patterns: happy-path-only tests, hardcoded counts derived from data
inspection (`assert len(x) == 270`), mocking data transformations instead of running the real path,
and claiming a test "would have caught" a bug without demonstrating the failure on the buggy code
first. Hardcoding well-known **domain constants** (enum values from a spec) is fine; hardcoding
row/unique counts derived from inspecting data is not.

---

## Documentation & prose style

- Write in natural, human prose. Avoid AI-typical patterns (em-dash pile-ups, filler transitions,
  marketing voice). Never hallucinate documentation or overpromise unimplemented features.
- Keep READMEs concise; move deep implementation detail to `docs/`.
- When describing the platform, frame it as a bioinformatics tool that *joins* VCF data against module
  databases to add annotations. Never imply the VCF already contains annotations, and never claim the
  tool makes gene–disease inferences.
- Update `CLAUDE.md` and any affected `docs/` immediately whenever code is refactored.

---

## Consumer feedback is a conversation (the triage loop)

`docs/CONSUMER_SUGGESTIONS.md` is an **inbox**, and every item in it gets a maintainer reply written back
into the document beside the report. The runbook is **[docs/CONSUMER_TRIAGE_LOOP.md](docs/CONSUMER_TRIAGE_LOOP.md)** —
read it before answering one. Three dependency-free scripts run it:

```
.claude/triage-state.py [--pending] [--next]    # the ledger; --next claims the next id
.claude/triage-archive.py S3 [--dry-run]        # move answered items, verifying the prose moved verbatim
.claude/watch-suggestions.sh                    # debounced watcher, armed with the Monitor tool
```

Two of the three are Python and carry `.py` for it — run them or hand them to `python3`, **never to
`bash`**: bash ignores the shebang, executes the module docstring, and `import hashlib` reaches
ImageMagick's `import`, which silently writes 0-byte files named after each import into the working
directory. They were `.sh` until 2026-08-16.

- **The document is the state.** A reply carries `<!-- triaged: <version> · sha <12 hex> -->` holding a
  fingerprint of the *consumer's* text only, so re-running after our own write is a no-op. Not git — a
  consumer may commit their own addition, and "what changed on disk" is a different question from "what has
  been answered".
- **The loop commits as it goes** (standing instruction). One commit per answered batch, once the suite is
  green and the item is archived, so a commit is a whole answer rather than a half-edited document. Stage
  explicit paths, never `git add -A`: this loop routinely runs beside another session editing the same
  tree. Never push, never tag, and never commit in a sibling repo — an upstream filing is appended and left
  dirty for its own maintainer.
- **Answered items move to `docs/CONSUMER_SUGGESTIONS_HISTORY.md`**, so an empty inbox means nothing is owed.
  Ids are never reused, and `--next` computes the next one over **both** files — an empty inbox otherwise
  invites a second `S1`.
- **The consumer's prose is evidence: never edited, never re-wrapped**, not even when it is moved. Replies
  are appended. That is why archiving is a tool's job and why it verifies each fingerprint survived.
- **`new` never means "no work done".** Establish what already shipped (CHANGELOG, ROADMAP, `git log -S`)
  before reproducing, and reproduce before classifying — upstream's first run found two of eleven items
  already fixed.
- **Legality sizes the release; severity only orders the queue inside it.** A severe finding fixed by a new
  response field is minor; a trivial one fixed by renaming a query param is major. The table is in the
  runbook, along with the four traps (immutability, the global `content_hash` claim, the lockstep
  `just-dna-format` minor, and `REGISTRY_MODE` not being a repair).
- **A flush-left `#` inside a fenced block used to end the section there, and since 0.25 the scripts
  handle it.** The ledger and the archiver found an item's span with `BOUNDARY_RE = ^#{1,2} `, which
  knew nothing about code fences — so a `# comment` at column 0 inside a ```python block ended the
  section at that line. Our S62 carried one and was truncated mid-fence: upstream's archiver moved half
  of it to their history file and left the rest orphaned in the live inbox, reporting every fingerprint
  intact and being right to, because both halves hashed the same truncated span. **S19 then carried one
  too** — 55 of its 112 lines would have moved — which is what finally bought the fix rather than
  another restatement of the advice. `fence_mask` / `boundary_at` in both scripts now mask fenced lines
  out of every boundary test; see the runbook's §5 entry, which is owed to the gist.
  **Two things this does not license.** A reporter's prose is still never edited, which is *why* the fix
  had to be in the tool — the advice to indent the comment cannot be given retroactively to a report
  already filed. And it stays good advice for writing: `grep '^# '` is still fence-blind, and so is
  every other reader that is not these two scripts. What changed is that following it is no longer what
  stands between an item and being cut in half.
- **A fifth route exists here: upstream.** If the fix belongs to the manifest, compiler or enricher, restate
  the item in *their* terms in `../just-dna-format/docs/CONSUMER_SUGGESTIONS.md` with an id from *their*
  ledger — that file is the one writable path in a sibling repo, append-only, and never committed by us.
  Forwarding our wording verbatim gets it triaged as somebody else's problem.

The pattern is published as a gist (`gist.github.com/winternewt/54b94bda01812be937b892146d1bb254`) and the
scripts here are that copy with the `INBOX` default repointed. A change to the *pattern* belongs in the gist
too; a change to this repo's release table or routing does not. Sync is one-way and by hand.

---

## Related repos

Part of a multi-root ecosystem: `just-dna-lite` (main app + webui), `just-dna-pipelines`
(compiler/discovery — this service's dependency), `just-prs`, `prepare-annotations`, `dna-seq`.
Treat sibling repos as **read-only** unless the task explicitly targets them — the one exception is
`../just-dna-format/docs/CONSUMER_SUGGESTIONS.md`, which we append upstream items to (see above). This
registry plugs into the existing `Source` discovery model as *just another source* (`registry://`), so
existing HuggingFace/local modules keep working with zero migration.
