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
  `artifact.digest` that is the version's immutable content identity.

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
  at N× the intended rate. That sharing is only safe because the concurrency gate defaults to 1
  (`PacingGate` has no lock) — which means the two rules are one rule: **anything that takes the
  shared bundle must also take a gate permit.** `/check` and the publish path both do; publish takes
  it conditionally, since an offline publish reaches nothing and has nothing to serialize.
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
  mismatches. Each pass carries its own `warnings` for exactly this.
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

## Manifest & integrity (see SPEC §4–§6)

- The `manifest.json` is the contract and the source of truth. Registry-level fields (`namespace`,
  `version`, `owner`, `license`, `published_at`, `canonical_id`) are filled by **this service** on
  publish; compile-time fields come from `compile_module()`.
- **All hashes are SHA-256, lowercase hex, prefixed `sha256:`.**
  - `inputs[].sha256` — over raw input bytes (no normalization), byte-reproducible by any downloader.
  - `artifact.files[].sha256` — over the concrete written bytes (parquet is **not** deterministic
    across polars/arrow versions, so pin `compiler_version` + `ensembl_reference`).
  - `artifact.digest` — Merkle root: JSON array `[{"name","sha256","size"}, ...]` sorted by `name`,
    serialized with sorted keys and no whitespace, then hashed. This is the version's content identity.
- **`compile_success` is trustworthy only when this server compiled it** (`compiled_by ==
  "marketplace-server"`). Treat foreign `compiled_by` or `false` as untrusted.
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

## Related repos

Part of a multi-root ecosystem: `just-dna-lite` (main app + webui), `just-dna-pipelines`
(compiler/discovery — this service's dependency), `just-prs`, `prepare-annotations`, `dna-seq`.
Treat sibling repos as **read-only** unless the task explicitly targets them. This registry plugs
into the existing `Source` discovery model as *just another source* (`registry://`), so existing
HuggingFace/local modules keep working with zero migration.
