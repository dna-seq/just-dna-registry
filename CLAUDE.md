# Agent Guidelines — just-dna-registry

This repo is the **annotation module registry**: a standalone, **server-side REST API
service** (FastAPI) that catalogs, versions, validates, and serves annotation modules for the
`just-dna-lite` ecosystem. **There is no frontend here** — the webui and Dagster pipelines are
*consumers* of this API. Any UI concern (Reflex, Fomantic, PRS widgets) belongs in `just-dna-lite`,
not in this repo.

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

This service **depends on `just-dna-pipelines`** for `validate_spec`, `compile_module`, and the
`ModuleManifest` models. Reuse that code; do not re-implement compilation or the manifest schema here.

---

## Running the service

- `uv run registry serve` starts the API (Typer CLI → uvicorn). `uv run pytest -q` runs tests.
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
  - **A validation finding is a `200`, not a `422`.** `/validate` and `/check` return `valid: false`
    with the reasons in the body; only a request no spec dir can be built from is a 4xx. Publish is
    the opposite. Getting this backwards makes the endpoints useless to the CI jobs they exist for.
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
  **And the bundle has to be *constructed*: bare `LookupClients()` is six `None`s.** Its docstring's
  "lazily built" describes `lookup.py`, whose functions do `clients.x or XClient()` and close what
  they made — nothing fills the dataclass. An empty bundle passes `None` into every `resolver=` /
  `gnomad_client=` / `eutils=` argument, so each pass builds its own client, the pacing is per call
  again, and `close_lookup_clients` closes nothing. `shared_lookup_clients()` builds all six.
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
  beside it. Note the divergence from the enricher's own CLI: it suppresses `not_requested` (there it
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
- **A read-only pre-flight must predict the operation it precedes.** `GET /namespaces/{ns}` reported
  `valid: true` for a name the claim then refused (S6). It now carries `requires_allow_test_data` and
  a warning instead — *not* `valid: false`, because the name is genuinely claimable with the flag, and
  flipping the field would be the same contradiction rewritten backwards.
- **Anything destructive snapshots first** (`backup._guard` in the CLI). The rolling index only counts
  up and never overwrites — it is not a ring buffer, and taking a backup must be the one safe act here.
- **A new route on either mode needs a `RegistryClient` method and a row in the parity table.** The
  guard enumerates *both* modes precisely because a mode-gated route would otherwise ship unwrapped.

---

## Spec layout (0.14) — the flat one is canonical, everything else is transport

The compiler reads one flat directory, so that is the spec. `specfiles.plan_layout` normalizes an
upload onto it and `services/publish.normalize_spec` applies the plan — called from `_finalize` and
from **both** dry-run workers, because a dry run that normalizes differently from the publish it
predicts is worse than one that does not normalize at all.

- **The folder convention is ours; the format says nothing about folders.** `derived/` holds the
  machine-written tables (`resolution.csv` + the fact sidecars) on the wire, in both directions. It
  exists because a spec mixes two provenances and marks neither — and `sources.csv` is genuinely
  both, the author's rows with the enricher's merged in.
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
- **Renames live in one map (`RENAMED_ON_UPLOAD`), and the second entry is `licensing.csv` →
  `sources.csv`** (0.16.2). Same repair as `MODULE.md` from the other direction: there we were ahead
  of the corpus, here we are *behind* it — format 0.6 renamed the licensing ledger (RM51) and every
  current authoring tool and reference example writes the new name, while this deployment compiles on
  0.5. The failure was not a dropped file but a **false facet**: the ledger reached storage and never
  the compile, so `manifest.sources` held the enricher's own Ensembl row and a module whose upstreams
  forbid sale advertised `licensing.commercial_use: true`. A warning would only have announced that.
  **Three things must hold before adding a name to that map, and all three were checked here, not
  assumed:** the two names are one table with one row model upstream (not a guess at intent, which is
  what keeps `_README_LOOKALIKES` a warning); the 0.6 header is field-for-field the installed 0.5
  `SourceRow`, which is `extra="forbid"`, so a schema drift would fail loudly rather than publish
  something wrong; and the destination is outside `SIGNATURE_INPUTS` and inside
  `RECOGNIZED_SPEC_FILES`, so the rename can neither move a `content_signature` nor be dropped by the
  `revalidate`/`upgrade` rebuild. A test asserts the last one over the whole map. Both present → the
  readable name wins with a warning, where upstream RM49 *refuses*; turning a publish that succeeds
  today into a refusal is a major, and their resolver arrives with the 0.6 lockstep anyway.
- **The split cannot separate what a downloader never receives.** The manifest has fields for `logs`,
  `logo`, `provenance` and the authored `inputs`, and none for the derived CSVs — only their
  parquets are in `artifact.files`. So `download(layout="split")` creates `derived/` only when
  something lands in it, and `download(include_inputs=True)` exists because `/download` lists
  `artifact.files` alone. Filed upstream as **S26**, with the second half: the compiler discovers
  authored tables at the spec root only, which is what keeps this layer transport-only.

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
  quantifier means — a table-only module is the case that finds out. **Positional joinability is the
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
