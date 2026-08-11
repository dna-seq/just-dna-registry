# just-dna-registry — Roadmap

Priority-ordered plan for building the annotation module registry, MVP-first. The full
contract lives in [SPEC.md](SPEC.md); this doc is the *build order*. Section references (§) point
into the spec.

## Guiding decisions

| Area | Decision |
|---|---|
| Manifest contract | The **`just-dna-format`** workspace (repo `dna-seq/just-dna-format`) holds two packages: **`just-dna-format`** (pure Pydantic schema/contract — DSL spec + manifest + integrity + identity) and **`just-dna-compiler`** (the transform, + polars/duckdb). Single source of truth for `just-dna-pipelines` and this service; prevents drift, and keeps Dagster/LLM deps out of both. |
| Artifact storage | **HuggingFace Hub** datasets via `HfFileSystem` (never `snapshot_download`). |
| Publish trust model | **Server-side recompile** — publisher uploads the spec only; the server runs `compile_module()` and produces the trusted manifest/digests (§7). |
| Auth | **Static API keys**; one account owns one namespace. JWTs, orgs, and membership are deferred. |

## Starting state (why M0/M1 come first)

The SPEC §10 prerequisite work does **not** exist yet in `just-dna-pipelines` (v0.1.6, a local
workspace member, not on PyPI):

- No `ModuleManifest` contract; `compile_module()` writes 3 parquets but **no `manifest.json`, no
  SHA-256 hashing, no artifact digest**.
- `validate_spec` stats expose `categories` as a list but `genes` only as a count.
- `_SPEC_SUFFIXES` is function-local and excludes `.json`.

So the integrity contract has to be built (M0) and wired into compilation (M1) before the service
can trust or emit manifests.

## MVP — the finish line

An authenticated author uploads a **spec** → the server **validates + recompiles** it against a
pinned Ensembl reference → writes the module dir + `manifest.json` to an **HF dataset repo** →
**indexes** it. Anyone can then **browse / search / filter / inspect versions**, **download** the
artifact, and **verify its integrity**. Authors can **yank**. Everything outside that loop is
deferred.

---

## Milestones

| # | Milestone | Scope | Status |
|---|---|---|---|
| **M0** | `just-dna-format` shared contract | Schema (DSL spec + manifest + integrity + identity) + reference compiler, as a 2-package uv workspace (§4–§6). **Blocks all publish/verify.** | ✅ **done** — 44 tests |
| **M1** | `just-dna-pipelines` integration | Repoint pipelines' `module_compiler` to `just-dna-compiler` (re-export shim), delete the duplicate, add `.json` on install (§10 A4). Cross-repo. | ⏳ **deferred** (cross-repo) |
| **M2** | Service skeleton | Config, DB projection schema, storage backend interface, FastAPI app, `/health`, admin CLI. | ✅ **done** |
| **M3** | Read / catalog API | Endpoints 1–4: list/search/facets, detail, versions, manifest (§8.1–§8.4). No auth. | ✅ **done** |
| **M4** | Publish pipeline | API-key auth, multipart spec upload → server-side recompile (`just-dna-compiler`) → store → index (§8.6–§8.7). | ✅ **done** (local backend; HF commit pending) |
| **M5** | Download + integrity | Download/files redirects + reference client verify-then-install (§5, §8.5). | ✅ **done** (local backend; HF redirect pending) |
| **M6** | Yank + finish | Yank/un-yank, `whoami`, basic rate limiting (§6, §7, §8.8). | 🚧 **yank + whoami done; rate limiting pending** |

**Dependency order:** M0 → M1 → M2 → M3 / M4 (M4 needs M0+M1+M2) → M5 → M6.

## 0.3 — community-first onboarding (shipped)

Goal: publishing from the just-dna-lite UI **without leaving the app**, community-foster over
security. Bootstrapping a publisher is now self-service, gated by a lightweight anti-spambot
proof-of-work rather than admin issuance.

- ✅ **Install-id (proof-of-work).** The lite app mints an install-id once at first run:
  `jdi1_<random>_<nonce>` whose SHA-256 has ≥ `install_id_difficulty` (default 20) leading zero
  bits (`installid.generate_install_id` / `validate_install_id`, shared in the base package).
  Open-source ⇒ not malpractice-resistant, but deters random/bulk AI-spambot ids; verify is O(1).
- ✅ **Self-registration.** `POST /api/v1/auth/register {install_id, account}` validates the PoW and
  mints an account + API key (one account per install-id; re-register re-issues a key). Gated by
  `allow_self_register` (default on).
- ✅ **Namespace claim, tied to install-id.** `GET /api/v1/namespaces/{ns}` (availability) +
  `POST /api/v1/namespaces {namespace}` (claim). Each account may hold up to
  `namespaces_per_account` (default **5**); over that → `403 namespace_limit_reached`, taken →
  `409 namespace_taken`.
- ✅ **Provenance without a spec change.** Downloaded vs custom is read from `manifest.json`
  (`compilation.compiled_by == "marketplace-server"` + `identity`); the client **stamps** the
  published manifest back into the local spec dir so "published-by-me" is self-marked. Batch
  `POST /api/v1/modules/lookup {digests:[...]}` classifies many local modules in one request
  (digests are already in each manifest — no client hashing, one indexed query). **The DSL
  `module_spec.yaml` is deliberately not changed** — provenance lives in the manifest (its layer).
- ✅ **Client + CLI:** `RegistryClient.register/namespace_available/claim_namespace/lookup_by_digests`;
  `registry-client register|namespace-available|claim-namespace`; `generate_install_id` exported.

DB: `accounts.install_id` (unique, nullable — admin keys exempt) added via an idempotent migration
so the live catalog upgrades in place. Still deferred: expiring JWTs / OAuth, org membership, and
true abuse-resistance (the PoW is a deterrent, not a wall).

## 0.4 — moderation, ops, HF storage, webui deliverable

Scope: everything outstanding **except** S3/MinIO (overkill for now) and Postgres (→ 0.5). A5
backfill dropped (existing annotators are processed elsewhere).

**Shipped**
- ✅ **Featured namespaces** — `featured` flag; float to the top of every listing; `?featured=true`
  restricts. Card carries `featured`. Admin CLI `feature`/`unfeature`.
- ✅ **Blacklisted namespaces** — hidden from default `GET /modules` + search; reachable via
  `?namespace=`, `?include_blacklisted=true`, or direct detail. Admin CLI `blacklist`/`unblacklist`.
- ✅ **Key revocation** — `registry revoke-key` / `revoke-account` (closes the leaked-key gap).
- ✅ **Rate limiting** (SPEC §7) — in-memory token buckets per caller × category on
  search/download/publish; `429 rate_limited`; configurable, on by default.
- ✅ **`HfStorage` backend** — HF dataset repo under `data/{ns}/{name}/{version}/…`; writes via a
  single commit, reads via `HfFileSystem`, `file_url` → HF `resolve` CDN URL so downloads `302`.
  Selected by `storage_backend=hf`; the startup token guard (0.2.1) gates it. *Live commit/read is
  integration-tested with a real token + public repo (offline unit tests cover paths/URLs).*
- ✅ **webui registry-page deliverable** — [WEBUI-STORE.md](WEBUI-STORE.md): the
  client + response shapes + provenance/onboarding wiring the webui builds its catalog page on.

- ✅ **Optional JWT sessions** — `POST /auth/tokens` exchanges a static API key for a short-lived
  JWT that's also accepted as a bearer. Off unless `jwt_secret` is set; static keys always work
  (backwards-compatible, 0.4 behaviour unchanged).

**Dropped (planning legacy).** The **prebuilt-parquet upload / "trust-but-verify"** mode is gone:
it only existed so the registry could avoid bundling the compiler — but we recompile server-side
now, so there's no prebuilt artifact to ingest. (If we ever need to *check reproducibility* of two
compiles, compare parquet **frame-shape + canonically-sorted content** rather than byte digests —
parquet isn't byte-deterministic across arrow versions. Not needed today.)

**Deferred within 0.4 (rationale)** — not blockers; each needs more than a quick pass:
- **Ed25519 signing** — would put a crypto dep in the *light* client (for verify) and needs
  server keypair ops; SPEC marks it "Future". Revisit deliberately.
- **Presigned PUT upload** — mainly matters once large-parquet HF uploads are the norm; multipart is
  fine now. Pairs with hardening `HfStorage`.
- **OAuth + org membership** — needs a provider/product decision; install-id self-register + optional
  JWT cover the community MVP.
- **Download analytics** — beyond the counter; low priority.

**→ 0.5:** Postgres migration; FTS5 / advanced search (grouped as the search-at-scale effort).
**Excluded:** S3/MinIO.

### Current state (2026-07-07) — v0.4.0, live

**Live** at <https://module-registry.just-dna.life>. Depends on the published PyPI packages
`just-dna-format>=0.1.0` + `just-dna-compiler>=0.1.0`. **39 tests green**; full integration run
passed against the live server. Packaged **client-first**: default install is the reference client
(`from just_dna_registry import RegistryClient`); the server is the `[server]` extra.

Shipped (beyond the core M2–M5 loop):

- ✅ **Publish** — multipart spec upload **and** zip/tar.gz **archive import** (spec archive or
  legacy parquet-only via `reverse_module`), server-side recompiled.
- ✅ **Download** — per-file verify-then-install **and** streamable **tar.gz** (`?format=tarball`);
  generalized `…/files/{path}` serves parquets, logs, and inputs.
- ✅ **Logs over the API** (`…/versions/{v}/logs` + file serving).
- ✅ **Digest lookup** (`GET /modules/lookup?digest=`).
- ✅ **Auth** (static keys) + ownership, **whoami**, **yank/un-yank**.
- ✅ **Ops-only hard removal** (`registry remove-module` / `remove-namespace`).
- ✅ **Debug logging** behind `REGISTRY_DEBUG` (request tracing + Eliot pipeline steps).
- ✅ **HF token startup guard** — `storage_backend=hf` validates a write-capable token or exits 1.
- ✅ **Reference client + CLI** (`registry-client`); docs: `API-REFERENCE.md`, `CLIENT.md`,
  `CHANGELOG.md`, `.env.template`.

What remains for a full MVP:

- **M1** (in `just-dna-lite/just-dna-pipelines`): repoint its `module_compiler` to
  `just-dna-compiler` (re-export shim + delete the duplicate) and add `.json` to `_SPEC_SUFFIXES`
  (§10 A4). Cross-repo, deferred pending the go-ahead to edit it.
- **`HfStorage`** backend (currently only `LocalStorage`) for real `302` CDN redirects + HF commit.
  (The startup token guard is already in place for when it lands.)
- **Rate limiting** (M6); cross-version provenance aggregation.
- **Ensembl at publish** is opt-in: `resolve_with_ensembl` defaults **off** (specs must carry
  positions); enable with a reference cache via `JUST_DNA_PIPELINES_CACHE_DIR` /
  `REGISTRY_ENSEMBL_CACHE`.

Run it: `uv run registry serve` · issue a key: `uv run registry issue-key <acct> -n <ns>`.

### M0 — `just-dna-format` shared contract package

Minimal package, Python ≥3.13, deps: `pydantic` + stdlib only.

- **Manifest models (§4):** `ModuleManifest` with `Identity`, `Display`, `Stats`, `Compilation`,
  `InputFile`, `Artifact`/`ArtifactFile`. Registry-only fields (namespace, version, owner,
  license, published_at, canonical_id) are `Optional`, filled on publish.
- **Integrity helpers (§5):** `sha256_file() -> "sha256:…"`; `artifact_digest(files)` (canonical
  Merkle root — JSON array of `{name,sha256,size}` sorted by name, `sort_keys`, no whitespace, then
  hash); `build_manifest(...)`; client `verify_manifest(dir, manifest)` (per-file hash → recompute
  digest → `compile_success` + `compiled_by == "marketplace-server"`).
- **Identity/versioning (§6):** name regex `^[a-z][a-z0-9_]*$`, `canonical_id`, SemVer
  parse/compare, `vN → N.0.0` legacy mapping.
- **Tests:** digest order-independent and stable; tamper-one-byte → verify fails; fixture round-trip.

### M1 — `just-dna-pipelines` integration (upstream, additive)

- **A2:** `compile_module()` writes `manifest.json` using the shared models — input hashes over raw
  spec bytes, artifact file hashes/sizes over written parquets, artifact digest.
- **A3:** expose `genes: list[str]` in `validate_spec` stats (filter `None`); normalize
  `variant_count` / `study_count` / `gene_count`. (`categories` is already a list.)
- **A4:** promote `_SPEC_SUFFIXES` to a module-level constant and add `.json` so `manifest.json`
  survives `register_custom_module`.

### M2 — registry service skeleton (this repo)

- **Deps** (`uv add`): `just-dna-format`, `just-dna-pipelines` (path/workspace), a DB layer (SQLite),
  `huggingface-hub`, `eliot`, `python-dotenv`. Drop `polars-bio` from direct deps unless the API
  reads parquet directly (stats come from the manifest).
- **Config** (Pydantic settings): HF dataset repo id + write token, pinned Ensembl reference, SQLite
  path, API-key store. Load `.env` before reading env.
- **DB schema (§9)** — a *projection* of `manifest.json`: `accounts`/`api_keys`, `namespaces`,
  `modules(namespace, name, …)`, `versions(module_id, version, digest, manifest_json,
  compile_success, yanked, created_at, downloads)`, and `version_genes` / `version_categories` facet
  tables.
- FastAPI app factory + `/health`, Eliot logging, Typer admin CLI stub.

Proposed layout: `src/just_dna_registry/{config,cli}.py`, `db/`, `storage/` (abstract
`StorageBackend` + `HfStorage`), `api/{app,deps}.py`, `api/routers/`, `services/`.

### M3 — read / catalog API (no auth)

Endpoints 1–4 (§8.1–§8.4): `GET /api/v1/modules` (search `?q`/`?category`/`?gene`/`?genome_build`/
`?owner`/`?license`/`?sort`, pagination `{items,total,page,per_page}`, `per_page` max 100),
`GET /modules/{ns}/{name}` (detail + readme + versions + `latest_manifest`), `.../versions`,
`.../versions/{v}/manifest`. Search = title/description match + facet joins. Explicit Pydantic
response models.

### M4 — publish pipeline (server-side recompile + API-key auth)

- **Auth:** static API-key bearer → account + owned namespaces; `{ns}` must be owned else
  `403 not_namespace_member`.
- **Init** `POST /modules/{ns}/{name}/versions`: declare version + files with client hashes;
  `409 version_exists`, `422 invalid_version`. **MVP upload = `multipart/form-data`** of the spec
  (SPEC-sanctioned MVP alternative to presigned PUT).
- **Finalize** `POST .../versions/{v}/finalize`: verify hashes → `validate_spec()` (`422` with
  `errors`/`warnings`) → `compile_module()` with the **pinned Ensembl reference** → `build_manifest()`
  (`compile_success`, `compiled_by="marketplace-server"`) → commit module dir (`data/{name}/v{N}/`
  incl. `manifest.json`) to the **HF dataset repo** → upsert DB + facet tables. Response `201` with
  the full manifest.
- **Ensembl provisioning:** download/cache the reference on first compile (fsspec, not
  `snapshot_download`). Compilation is CPU-heavy — run it off the event loop (executor/thread);
  a dedicated worker/subprocess is an optimization, not required for MVP.

### M5 — download + integrity

`GET .../versions/{v}/download` → `302` to the HF `resolve` URL for the module tarball;
`?format=files` → per-file `{name,url,sha256,size}`. `GET .../versions/{v}/files/{file}` → redirect
to the HF file URL. Increment the `downloads` counter. Ship a reference client verify-then-install
built on `just_dna_format.verify_manifest` (also the seed for the future webui `registry://`
source).

### M6 — yank + finish

`POST .../versions/{v}/yank` (+ un-yank): set `yanked=true`, drop from default listings and `latest`,
keep manifest/artifact fetchable. `GET /auth/whoami` (identity + namespaces). Basic per-key rate
limiting (publish/download/search buckets, §7) — a simple in-memory token bucket for MVP.

---

## Deferred — nice-to-haves (post-MVP)

- **Presigned PUT upload flow** (init → targets → finalize) for large parquet. MVP uses multipart.
- **Full auth:** `POST /auth/tokens` issuing expiring JWTs; **org namespaces + member management**.
- **Prebuilt "trust-but-verify" publish mode** (sandbox recompile + digest compare,
  `422 digest_mismatch`).
- **A5 backfill** of existing `just-dna-seq/annotators` into manifests + index (ops/CLI task).
- **Ed25519 signing** of `artifact.digest` + published pubkey (§5 "Future").
- **Postgres** migration; **FTS5** / advanced search; download analytics.
- **S3/MinIO** storage backend behind the same `StorageBackend` interface.
- **webui / Dagster consumer integration** (§11 — `registry://` source branch, catalog page) —
  lives in `just-dna-lite`, not this repo.

### Namespace curation & moderation

- **Featured namespaces** — an admin-set `featured` flag (on `namespaces`, or a `namespace_flags`
  table) so the catalog can surface a curated front page / `?featured=true` filter / a "featured
  first" sort. Purely additive to the projection.
- **Blacklisted namespaces (hidden by default)** — a moderation flag that removes a namespace's
  modules from default `GET /modules` listings and search; they are returned **only when directly
  requested** (e.g. explicit `GET /modules/{ns}/{name}` or an opt-in `?include_blacklisted=true` /
  `?namespace=<ns>`). Distinct from yank (which is per-version); this hides an entire namespace
  without deleting it. For spam/abuse.
- **Server-side hard removal (ops-only, not the API, not yank)** — ✅ **done**: admin CLI
  `registry remove-module <ns> <name>` and `remove-namespace <ns>` purge DB rows (versions +
  `version_genes`/`version_categories` cascade, modules, namespace ownership) **and** the stored
  artifacts (`storage.remove`), so the namespace is fully reclaimable — a new key re-submits with
  old versions gone. Off the public API (ops/console only), `--yes` to skip the confirm.

---

## 0.7 — format 0.3 adoption + upgrade automation (shipped)

- **Adopted `just-dna-format` / `just-dna-compiler` 0.3.** Pins bumped to `>=0.3.0`. The new columns
  (`direction`, `stat_significance`, `effect_size`/`effect_measure`, `flags`, `effect_allele`,
  `trait_efo_id`, `clin_sig`) flow through publish/recompile automatically — they are additive and
  the server recompiles every spec, so a published module simply gains them on its next publish.
- **`revalidate` now surfaces 0.3 drift as `upgradable`.** Because the 0.3 columns are additive, a
  legacy module still *validates*; the audit distinguishes `ok` / **`upgradable`** (validates, but
  the additive axes can be back-populated from the legacy `state`/booleans) / `needs_upgrade` (fails
  the current validator) / `skipped`. `--set-flag` marks both `upgradable` and `needs_upgrade`.
- **New `registry upgrade` command + `services/upgrade.py`.** Consumes the format's own
  `VariantRow.upgraded()` derivation to migrate a version's `variants.csv` (back-populate
  `direction`/`stat_significance`/`clin_sig` + trim `state`) and re-publish as the next PATCH through
  the normal server-side compile path. Dry-run by default; `--apply` publishes. The predecessor is
  never mutated (immutability) and the transform is idempotent. This is the automation of
  `docs/UPGRADE.md` step 3 for the 0.3 additive-column contract.
- The diplotype/copy-number *shapes* (format items 7/7b) stay representation-only until a consumer
  (just-dna-lite) can call them; nothing registry-side is needed for them yet.

### 0.7.1 — server/client version-mismatch guard

Bumping the format contract to 0.3 surfaced a real collision: a client on one `just-dna-format`
contract talking to a server on another produces a cryptic digest / catalog-shape error. 0.7.1 adds
an explicit guard:

- The server advertises its versions — `GET /api/v1/version` (`{api, registry, format, compiler}`)
  plus `X-Registry-Version` / `X-Format-Version` / `X-API-Version` response headers on **every**
  response — and the client sends its own versions as request headers.
- Before publish/import/download, the client calls `assert_compatible()`: it fetches the server's
  versions and raises `VersionMismatchError` (HTTP 409) with an actionable message when the API
  version or the `just-dna-format` contract can't interoperate. Contract rule: same MAJOR, and while
  `0.x` also the same MINOR (a 0.x minor moves the parquet schema / `artifact.digest` — exactly the
  0.2→0.3 case). A differing registry *app* version is **not** fatal (the API is path-versioned).
- A pre-0.7.1 server (no `/version`) can't be checked, so the guard warns and proceeds.
  `REGISTRY_SKIP_VERSION_CHECK=1` (or `RegistryClient(check_version=False)`) is the escape
  hatch; `registry-client version` prints both sides and the verdict. Logic in `version.py`.

## 0.10 — format 0.4 adoption

- **Adopted `just-dna-format` / `just-dna-compiler` 0.4.** Pins bumped to `>=0.4.0`. 0.4 is a
  contract minor (the parquet schema and therefore `artifact.digest` move), so the version-mismatch
  guard now requires client and server to both be on `0.4`. The new authored columns (`weight`,
  `effect_size`/`effect_measure`, `effect_allele`, `flags`, `requires_callable`, `acmg_sf`,
  `actionability`, `priority`, `negatives`) and the frozen compiler-managed `variant_key` flow
  through publish/recompile automatically — additive, server-recompiled. The 0.3 upgrade automation
  (`services/upgrade.py`, `VariantRow.upgraded()`) is unchanged and still correct: the 0.4 columns
  are additive with no legacy source, so `upgraded()` still touches only the 0.3 axes.
- **Structured per-version `authorship` (format RM14) flows through end to end.** A `module_spec.yaml`
  may carry an `authorship:` block (one `{who, role, kind}` entry per contributor — a human ladder or
  `ai`+scale). The compiler records it verbatim into the manifest (out of `artifact.digest`), the
  registry stores it in the projected `manifest_json`, and it surfaces on the detail endpoint's inline
  `latest_manifest` — so a consumer (review queue, human auditor) can route scrutiny by author-kind.
  No DB/API-model change was needed; it rides the whole-manifest projection.
- **Server strips registry-owned keys before validate/compile (`strip_registry_owned_keys`).** 0.4
  made the `module:` block `extra="forbid"`, which rejects `module.version` (and `namespace`/`owner`/
  `canonical_id`) — keys the registry fills itself and every pre-0.4 spec archive carried. The server
  now drops that registry-owned set from the authored block on every compile path (publish, import,
  upgrade) and before the `revalidate` drift check, so the pre-0.4 corpus keeps importing/upgrading
  cleanly and a legacy `module.version` alone is not mistaken for un-fixable contract drift. The strip
  is byte-preserving on a clean 0.4 spec and kept permanently (a robust, version-independent
  normalization — the registry is the identity authority). Format-side follow-ups for this friction
  are filed as consumer suggestions in `just-dna-format` `docs/CONSUMER_SUGGESTIONS.md`.
- **`registry upgrade` gained schema-recompile and column-trim, for a clean 0.4 catalog migration.**
  Plain `upgrade` still only fires on 0.3 back-population, so it left on-contract modules on their old
  parquet shape. `--force` (`--recompile`) now re-emits the latest in the current schema even with no
  drift (non-lossy — only `artifact.digest` moves). Because 0.4 made the row models `extra="forbid"`
  (older lax schemas only *warned* on unknown columns/keys), a pre-0.4 `variants.csv`/`studies.csv`
  *or* `module_spec.yaml` can carry a column/key a 0.4 compile rejects; `--trim` drops those so the
  spec compiles (LOSSY, so `--force`-gated), and a version with such offenders and no `--trim` is
  reported **blocked** rather than crashing the planner. `services/upgrade.py` now exposes
  `prepare_version_upgrade` + `offending_columns`/`trim_unknown_columns` (CSV) and
  `offending_yaml_keys`/`trim_unknown_yaml_keys` (module_spec.yaml); the old `plan_version_upgrade`
  is folded into it.

## 0.11 — compiler/format/enricher 0.5 adoption ✅

- **Enrich → compile strict on publish.** The enricher (the only tier permitted to fetch) writes
  `resolution.csv`; the compiler consumes it. Two steps, never one call — `compile_module`'s
  `ensembl_cache=` shim reaches into the network tier from inside the compile path, which the
  constitution forbids and which is deprecated for removal at 1.0.
- **Pre-flight REST surface.** `POST .../validate` (offline, cheap) and `POST .../check` (the network
  tier, expensive). Findings are `200`s; `would_publish` is the field CI branches on.
- **Enrichment cost control.** A per-caller `enrich` bucket, a process-wide concurrency gate, a
  variant cap, a wall-clock timeout, and one shared `LookupClients` — because the outbound pacing
  that keeps us inside gnomAD's budget lives on the client object, not in the process.
- **Canonical `content_signature`** + a client-reachable lookup endpoint, as the format asked for in
  `PROPOSAL_0_4_1.md`. One-time re-derivation via `registry rederive-signatures`.
- **Trust and licensing facets** projected onto cards and versions.
- **Operator tooling**: `warm-caches`, `rederive-signatures`, `revalidate --recompile-check`,
  `upgrade --limit`.
- **Fixed**: multipart path traversal, missing upload bounds, the JWT rate-bucket collision, the
  PGx-only rejection, and the sidecar-dropping upgrade.

## 0.11.2 — compiler/enricher 0.5.2 adoption ✅

- **`clin_sig_not_checked` on the dry run and the publish path.** Enricher 0.5.2 (S4) ends the
  ambiguity in `clin_sig_conflicts: []` — "compared everything, nothing disagreed" and "never
  compared" no longer render identically. Surfaced as a structured token on `/check` and as prose on
  `notes` / a failed publish's `warnings`. Never a publish gate: every reason is operator-side.
- **Free from upstream**: the quadratic ClinVar probe is gone (a 297-gene panel went from ~2h to
  seconds), and the tautological `clin_sig` cross-check on a provider-drafted panel is skipped with a
  reason instead of spending 90% of the resolve time on a guaranteed zero.

## 0.11.3 — compiler/enricher 0.5.3 adoption ✅

- **The trust facet stopped believing an empty quantifier.** `fully_resolved` is `all()` over
  `variants.csv`, so a table-only module got a vacuous `True` and the catalog served PGx modules that
  join to no VCF under the fully-baked facet. `trusted` is now `false` on a positional-joinability
  warning, `null` when nothing was ever resolved. Ships `_migrate_0_11_3_trust` to re-project stored
  rows — the manifests were always right, only our reading moved.
- **The enrichment cost guard counts enrichment subjects**, not `variants.csv` rows. A PGx module
  reported 0 to a guard that then let every row through.
- **Free from upstream**: `heteroplasmy.csv` joined the enricher's subject list.
- **Still owed upstream**: the trust verdict keys off warning *prose* because the manifest records no
  structured check state — S8 / RM43. When that field lands, `_UNJOINABLE_MARKER` goes away.

## Next registry version (post-0.11)

- **A successful publish drops its enrichment findings.** `EnrichOutcome.notes` is read in exactly one
  place — a *failed* compile's `warnings` (`services/publish.py`) — so on the happy path the ref-allele
  result, the non-fatal stale rsIDs, the PAR drops and the new `clin_sig_not_checked` reason are
  computed and discarded. The publisher is told least when the publish worked, which is backwards, and
  `/check` already reports all of it. The fix is to carry them on the publish response; the deeper half
  (a *downloader* can never learn which checks ran, because the manifest records none of it) needs a
  format field and is filed upstream as S8 in `just-dna-format` `docs/CONSUMER_SUGGESTIONS.md`.
- **Retire Eliot → stdlib `logging`.** (Carried over; still pending.)
- **Redis-backed limiter *and* concurrency gate.** Both are process-local today, so with two replicas
  every limit is 2× — and gnomAD pacing in particular does not survive horizontal scaling without a
  shared gate. The gate is the newer half of that problem and the easier one to forget.
- **An async job queue for `/check`**, if the synchronous form proves too slow in practice. Deferred
  deliberately: it is a whole subsystem (jobs table, runner, TTL, SDK polling) and the sync form with
  a 300s cap covers the offline and small-online cases, which is most of them.
- **gnomAD gene-constraint enrichment** (`enrich_gene_metrics`) on the publish path, once the
  constraint snapshot is routinely provisioned.

## Superseded (post-0.10)

- **Retire Eliot → stdlib `logging`.** Rewire the Eliot usage — `start_action` in
  `services/publish.py` and the Eliot→stdlib bridge in `logging_setup.py` — onto the standard-library
  `logging` system logger, and drop the `eliot` dependency from `pyproject.toml`. The
  `just-dna-format` packages already use only stdlib `logging`; this aligns the registry with them
  and with the CLAUDE.md logging standard. (Was bundled with the format-0.3 adoption; that shipped in
  0.7 without touching logging, so this is now a standalone task.)

---

## Verification

- **M0:** `pytest -vvv` on `just-dna-format` — digest order-independence/stability,
  tamper → verify-fail, fixture round-trip (§13).
- **M1:** unit-test `compile_module` emits `manifest.json` with `inputs[].sha256` matching
  `hashlib.sha256` of the source CSVs, non-empty `artifact.files[]`, `compile_success=true`,
  `stats.genes`/`categories` matching a fixture.
- **M3–M6:** FastAPI `TestClient` contract tests per endpoint — invalid spec on finalize → `422`
  with `ValidationResult.errors`; re-publish existing version → `409`; publish under an unowned
  namespace → `403`.
- **End-to-end (MVP done):** publish a fixture spec → appears in `GET /modules` with correct stats →
  download in a second client → `verify_manifest` passes → tamper one byte → verification detects the
  digest mismatch. Run the API with `uv run uvicorn just_dna_registry.api.app:app`.
