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
- ~~**Ed25519 signing** of `artifact.digest` + published pubkey (§5 "Future").~~ **Shipped in 0.5.0** (`REGISTRY_SIGNING_KEY`).
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
- **Answered upstream, and waiting on 0.6**: the trust verdict keys off warning *prose* because the
  manifest records no structured check state. Filed as **S13**, confirmed, and tracked as **RM44** for
  format **0.6** — one additive integer (how many rows resolution was applied to), which makes
  `fully_resolved=True` beside zero subjects self-evidently vacuous with no consumer reading prose.
  Kept separate from S8's `checks_run`/`checks_skipped` (RM43/RM45) on upstream's argument that
  resolution is not a verification pass, so a row count does not belong in a map of which checks ran.
  **Half done in 0.13**: the compiler 0.5.4 floor let `db/facets.py` import `compiler.UNJOINABLE_PHRASE`
  instead of holding the literal, so the two spellings can no longer drift apart. The prose coupling
  itself remains until RM44, and so does the test that drives a real publish through the real compiler —
  an import cannot tell us the warning still fires and still reaches `manifest.compilation.warnings`.
  When RM44 lands, delete the facet and the test.

## 0.13 — compiler/enricher 0.5.4 adoption ✅

- **`unreachable_rsids`: a failed lookup is no longer reported as an absence.** Enricher 0.5.4 (S20)
  splits `resolve_rsid`'s old `([], None)` into "asked, no GRCh38 locus" and "could not ask", so the
  registry can too. On `/check` as a field and in `notes`; on the publish path it retargets the strict
  refusal's hint from three remedies that assume a faulty spec or cache to the only correct one, which is
  to try again. `would_publish` is unchanged — a strict publish against an unreachable Ensembl really
  does refuse.
- **`gene_loci` / `gene_loci_not_checked` on `?identifiers=true`.** Enricher 0.5.4 (S24) compares a row's
  `gene` against the chromosome its own variant sits on — a relationship that can be false while both
  halves are true, which is how a real symbol beside an invented rsID passed every check we had. Moves
  `clean`, never `would_publish`, on the same rule as the rest of that pass.
- **The trust facet imports the phrase it used to spell** (`compiler.UNJOINABLE_PHRASE`, S13 — see 0.11.3
  above for the half that is still owed).
- **Corrected, not added**: `PacingGate` is thread-safe upstream now (S15), and the fix names this
  server's shared-bundle-on-a-threadpool as the arrangement that provoked it. Three comments claimed
  `enrich_max_concurrency = 1` is what makes sharing the bundle *correct*; that was true through 0.5.3 and
  is now wrong. The default stays 1 — the IP-scoped budget it protects has not changed, and concurrent
  runs now interleave on one shared pace rather than going faster — but it is a latency choice.
- **Free from upstream**: a `.csv` one edit from a real table name now warns instead of being silently
  ignored, a binning table with no grounding evidence anywhere warns, and a hand-declared `literature`
  source row stops being reported as unused — which had been advising authors to delete the exact row the
  compile licence gate reads.

## needs_rebuild — a third axis, specified and built ✅

Two questions are answered today and a third is not, which is why 0.20.0's gene-index fix needed an
operator to know to pass `--force`:

| axis | question | answered by | verdict on the 0.6.1 → 0.6.6 case |
|---|---|---|---|
| input legality | is the stored spec still legal? | `revalidate` (re-runs `validate_spec`) | `ok` — correctly, nothing is wrong with the spec |
| contract | was this compiled under a contract-incompatible compiler? | `upgrade`'s `ContractGap` | `patch` — correctly, the parquet shape did not move |
| **output drift** | **would recompiling produce different output?** | **nothing** | — |

The third is the one RM121 raises. **Built in 0.21.0** (`services/rebuild.py`): for a manifest field
that is a pure function of authored rows, the current answer is recomputed from stored inputs with
`compiler.spec_tables` + `compiler.module_stats` — no enrichment, no parquet, no network — so a measured
difference acts under plain `--apply`. One field pair is probed today (`stats.genes`/`gene_count`); the
surfaces that need a real compile (`artifact.digest`, `compilation.warnings`) are named as `cannot_say`.
0.20.1's contribution stands underneath it: the `patch` bucket is counted rather than skipped in
silence. Still open upstream as **S62** — a `rebuild_hints(compiled_under, current)` keyed on the
interval, with an explicit `unknown_interval`, `content_signature` on its own axis, and the declaration
guarded by a diff of the reference examples rather than hand-kept.

**When it can be built, the contract is:** `needs_rebuild` is **tri-state** — `yes` / `no` /
`cannot_say` — never a bool, because the two histories behind a `False` are "checked and current" and
"nothing could check". It composes the three axes above rather than replacing any of them, and it keeps
the decision here: upstream supplies facts about what moved, this service decides whether a version
number is worth spending, because that cost is ours and differs per consumer.

**Two things not to do**, both already tried or already rejected once:

- **Never date a stored artifact by a landmark.** A version exception for `0.6.6` is the 0.18.0 defect
  with more entries. Compare versions, or check the data.
- **Ask whether the artifact can carry the evidence before building a predicate.** The 0.6.3 re-draft
  case could not (coordinate rows carry no `rsid`; the obvious predicate finds 0 of 31), so a detector
  would have reported clean on every affected module. The `stats.genes` case *can* — `revalidate`
  already rebuilds a spec dir from stored inputs — which is what makes a local predicate viable here and
  not there.

## 0.20 — format/compiler/enricher 0.6.6 adoption ✅

- **The partial-cut era ends, and not by choice.** 0.17–0.19 pinned the three tiers apart on purpose
  (`0.6.1 / 0.6.1 / 0.6.2→0.6.4`), each floor argued in `pyproject.toml`. From upstream 0.6.5 the
  compiler and enricher read format symbols that exist only there, and upstream's inter-package floors
  are `>=0.6.6` — so the question "is a partial cut available?" now answers itself. Ask it anyway next
  time; the method was right even though the answer changed.
- **The format floor is hard for a shape not seen here before: a new authored *column*.**
  `StudyRow.curator` (RM120) under `AuthoredModel`'s `extra="forbid"` — a spec carrying it is refused
  by a 0.6.1 install, not merely stripped. `ProvenanceItem.outranks` (RM117) is the opposite case on a
  permissive model. The `extra` setting is what decides which.
- **A defect of upstream's whose only victim was our gene index (RM121).** `manifest.stats.genes` was
  derived from `variants.csv` alone and `db/repository.py` fills the gene side table from it, so a
  `haplotypes.csv`/`diplotypes.csv`-led module published `genes: []` and `?gene=` could not return it.
  Nothing here changed to read it. **It reaches published versions only through `upgrade --force`** —
  a compiler patch is deliberately not a gap (0.18.0), so the sweep will not run itself, which is the
  detector working and is said out loud in the release for exactly that reason.
- **A tightening operators must know about (RM107).** A duplicate `(source, layer)` row in the
  licensing ledger is now a compile error in both `validate` and `compile`. A publish that worked can
  `422`, and a `--force` recompile of such a version fails on already-published bytes. Measured that
  the pre-flight and the gate agree (S6's rule), and swept the 27 sample specs: none carries one.
- **One new response field**, `enrichment.literature.titles_as_quotes` (RM118 / their S54): the PMIDs
  whose quote is the cited article's own title, which the grounding check cannot fail on. Reading it is
  what makes the enricher floor hard again after 0.6.4's deliberately soft one — the floor followed the
  adoption. It reaches `registry-client check`, because a field nothing prints reaches nobody.
- **Owed: nothing new.** `content_signature` does not move, so no `rederive-signatures` and no trust
  migration; the `db/facets.py` fallback recorded under 0.17 remains the only outstanding item.

## 0.17 — format/compiler 0.6.1 + enricher 0.6.2 adoption ✅

- **A contract cut, not an attribute chase.** Every `artifact.digest` moves and a 0.5 client is
  refused outright, exactly as 0.11 did for 0.4→0.5. `content_signature` moves nowhere (0/11 upstream),
  so no `rederive-signatures` and no dedup claim changes hands. Operator sequence in
  [UPGRADE.md](UPGRADE.md) § 0.17; the reassurances it makes are tested in `tests/test_format_06.py`
  rather than asserted.
- **RM44 landed and the prose fallback stayed** — see *Manifest & integrity* in `CLAUDE.md` for why
  the standing "delete the facet" instruction was superseded rather than followed. The counters
  (`resolution_subjects`, `positional_rows`/`_placed`, `expanded_keys`/`_rows`) are projected into
  columns and onto every `resolution` object, `null` throughout for a pre-0.6 compile.
- **`specfiles.py` is built on `just_dna_format.layout`** instead of mirroring it, which is what the
  0.16.2 incident argued for. The licensing rename inverted and is now derived rather than written.
- **Three new blocks on the detail** (`weighting`, `gwas_effects`, `verification`) and five new
  fact-table filters on `GET /modules`.
- **Free from upstream**: RM43's positional fill makes rsID-keyed PGx tables joinable, which flips
  the reference example's trust verdict and removes the last unjoinable module from the corpus.
- **The floor is 0.6.1, and the patch is load-bearing.** RM95 let a non-vocabulary spelling into
  `content_signature`, RM93 made `validate` stop predicting `compile` for two spec shapes, and RM97
  is upstream's half of the escaping-exception bug below. Reasons are written into the `pyproject.toml`
  pins, where the next floor bump will be read.
- **An upstream that does not answer stopped being a `500`.** Every `/check` pass caught its own error
  type while the pass let the *client's* through; each now reports `unreachable`, and the CLI prints
  it. Filed upstream as **S37** and answered the same day as RM101 in enricher 0.6.2: unavailability is
  a per-pass **subclass**, so the distinction is a type rather than a cause chain.
- **That fix reintroduced the bug once, which is the durable lesson.** A subclass lands in a parent
  `except` arm written above it, so our outage arms went dead and `/check` reported clean passes over a
  dead source — silently, with no status change for a test to notice. Arms reordered, client catches
  dropped, and an AST guard now fails on any shadowed `except`. Filed back as **S38**: upstream's
  upgrade table assumes one `except (PassError, ClientError)` tuple and has no row for two arms.
- **Owed, and newly the only thing owed here**: the fallback in `db/facets.py` and its differential
  baseline in `tests/test_format_06.py` retire together, when the last pre-0.6 version leaves a
  catalog. That is an event to watch for, not a release to schedule — a deployment that has run
  `registry upgrade` over its whole catalog is done, and one that has not, is not.

## 0.18.2 — enricher 0.6.4 adoption + ruff ✅

- **A floor that is deliberately not hard, and labelled as such.** Upstream 0.6.4 is one fix in the
  ClinVar drafter (S45): no public symbol moves, no pass this server runs behaves differently, and a
  deployment left on 0.6.3 is not broken. The pin moves because the lock had already resolved 0.6.4
  and the release's suite ran on `0.6.1 / 0.6.1 / 0.6.4`, so leaving it behind would permit an
  assembly nobody tested. Recorded as the first soft floor in `pyproject.toml`, because the long
  arguments attached to 0.6.2 and 0.6.3 stop working if every floor reads as mandatory.
- **A remediation this project relayed turned out to be incomplete, and correcting it is the release.**
  0.18.1 forwarded upstream's *those modules need a fresh upload from their publisher*. S45 measured
  it: drafting appends, so re-drafting an existing spec adds the corrected rows **beside** the ones
  they supersede (`MLH1`: 996 → 1,061 where a fresh draft is 1,030, with 31 rows a fresh draft does
  not contain). The publisher needs a fresh spec directory. Corrected in
  [UPGRADE.md](UPGRADE.md) and the changelog.
- **No detector to build, and the reason is recorded.** The superseded rows cannot be seen from inside
  a published module — coordinate rows carry no `rsid`, so the obvious predicate finds 0 of 31. A
  facet or `revalidate` rule would report clean on every affected module.
- **ruff adopted and applied**, config mirrored from `just-dna-format` rather than invented. 403
  findings → 0 across 54 files, suite unchanged at 417. The sweep found a shadowed
  `namespaces_for_account` live since 0.12.0 (removed; it never ran) and one rule that would have
  introduced a bug — `SIM118` against `sqlite3.Row`, whose `__contains__` scans values rather than
  keys.
- **Open, deliberately not in this release:** `whoami` reports owned namespaces only, not the union
  with membership. Not an authorization defect (`effective_role` reads membership directly); widening
  it changes what an existing response field contains, which is minor-sized here. Reasoning is beside
  `effective_role` in `api/deps.py`.

## 0.18.1 — enricher 0.6.3 adoption ✅

- **An argument we already passed stopped being inert, which is a dependency bump with no import to
  grep for.** Upstream S39 threads `load_dotenv_file` through the six cache resolvers, where it had
  reached none of them. `available_references` had passed `False` from the start on the reasoning that
  `config.py` loads the `.env` — true in a checkout, false in a container, because python-dotenv walks
  up from the *installed package* and the enricher walks up from the **CWD**. Flag dropped, so the
  report reads what the run reads; measured showing the pre-fix code reporting the host's stray
  platformdirs cache rather than the configured one, which is `configured_caches`'s forbidden ambient
  discovery arriving through the reporting door.
- **The rest of 0.6.3 is upstream's drafters (S41, S44) and does not reach this service**, which is
  itself the finding worth recording: "modules published before this need a re-draft" is authoring-side
  and has no `registry upgrade` answer. Said explicitly in the release and in
  [UPGRADE.md](UPGRADE.md) so nobody runs the sweep expecting it to fix a drafted module.
- **No sweep, no migration, no schema move.** Format and compiler stay at 0.6.1; a compiler patch is
  deliberately not a contract gap (0.18.0), and this is not even that.

## 0.25 — the caching proxy ✅

The registry becomes the box other people borrow snapshots from. Four surfaces, all shipped:
`GET /caches` (which lanes are here, and for an absent one why), `POST .../derived` (the enriched
tables a client with no Ensembl cache cannot make), `POST /drafts` (the drafters rented out) and
`/hint/*` (the authoring lookups, metered per upstream). The principle and the rules it turns on are
in [CLAUDE.md](../CLAUDE.md) under *The caching proxy*; the reasoning per surface is in the changelog.

**Still open, and deliberately:**

- **A console page for the hint proxy.** The cache dashboard got one; the hints did not, because the
  console is a publisher-and-operator surface and a variant lookup is an authoring one. If
  `just-module-creator` or the webui wants it, it is a page over routes that already exist and needs
  no API change.
- **A durable pace ledger.** `pacing.PaceLedger` is process-local, like `RateLimiter` and with the
  same consequences written down: two replicas is two budgets, a restart forgives a streak. That is
  honest for one instance and wrong for a horizontally scaled one, and the fix is a shared store —
  **not** a table in the catalog DB, which is a rebuildable projection of the manifests and would
  either wipe the ledger on reindex or have to preserve rows it cannot derive.
- **Production and the polygon share one IP** (`57.128.215.86`, confirmed by resolution and
  independently by `just-module-creator`). So they share gnomAD's single unbuyable allowance while
  each holds its own process-local gate *and* its own process-local ledger. This is already true of
  `/check` today; the hint proxy makes it easy to reach. Until that is untangled, the polygon should
  run with `REGISTRY_HINT_ALLOW_GNOMAD=false` — which is the default — and any argument in this repo
  that reasons about per-instance limits should be re-read knowing there is one budget, not two.
- **Upstream, filed as S91–S95** in the format tree: a read-only `lane_status()` in `caches.py`;
  `LookupClients`' three lazy-build semantics; the absolute snapshot paths in the lookup payload; a
  resolver-ladder rung pointing at a peer; and a spend counter on `PacingGate`. The first three are
  the ones that would remove work from here rather than add it.

---

## 0.28 — format 0.8 adoption, with the rename and the client fixes (scope; sized by the pm)

Sized 2026-11-04 with the maintainer, from the liaison's adoption map (`docs/UPSTREAM_COMPILER.md`, "The
coming minor", rows M1–M7, and M8–M11 added the same day from the branch at `503730c`) and the open entries under *Next registry version*. The lead builds it; each
entry's detail stays where it is filed, and this section says only what the minor holds and why.

**One minor, and it waits for 0.8.** The maintainer chose to bundle: 0.28 ships when upstream cuts format
0.8 and carries everything below together. Rejected: shipping the non-0.8 items now as 0.28 and giving the
adoption its own minor later, as 0.17 and 0.24 had. What that costs, said once: the rename and the client
fixes wait for a date nobody has yet (on 2026-11-04 the `0.8` branch carried format 0.8.0 with compiler
and enricher still at 0.7.2/0.7.3, nothing installable). The compiler's lead, the same day: the cut follows
the round-1 audit fixes, audit round 2 and its fixes, a release-gate sweep and a docs pass, "roughly 5-8
hours from now"; it sets `>=0.8.0` floors, writes the 0.8.0 release record and finishes
`docs/INTEGRATION_0_8.md`, and is announced in `#just-dna-compiler`. The liaison re-maps then. The items that need no 0.8 may be **built** on the minor's branch ahead of the cut; only the release
waits. C1 and C2 are patches and are not held: they ship as 0.27.x as filed.

**0.8 is delayed, so the 0.8 items are pre-built too** (the maintainer, 2026-11-05: "wait on their 0.8
integration and pre-build on top of that to be ready for release"). Upstream's
`docs/INTEGRATION_0_8.md` on their `0.8` branch is being finished (a complete "What to change" through
RM379, an upgrade order, per-consumer checklists with the registry's block matched against M1–M11), and
the compiler's lead asked that nothing act on it before they announce the finished commit. From that
commit the lead builds the 0.8-dependent items (M1's code, M2, M4, M8–M11) on the 0.28 branch against
upstream's `0.8` branch, so 0.28 needs only its floors, lock and recompile once the cut is on PyPI. Three
limits: the branch is not merged and nothing ships until the floors are published (CLAUDE.md: "Pin what
is published"; no path or editable source in a tracked file); M3's recompile and the operator steps (the
Ensembl pull) wait for the cut; and the guide is re-read at the tag, since a branch can still move.
Rejected: waiting idle for the cut, which would put a whole minor's build after it.

**Holds, hardest first.**

1. **The 0.8 lockstep cut** (M1): floors for all three tiers, `uv.lock`, the operator procedure in
   `docs/UPGRADE.md`, CLAUDE.md's floor reasons. Required. Written only once upstream's floors exist.
   **The Ensembl snapshot's move goes with it** (M8, upstream RM372): `config.py`'s `ensembl_reference`
   default names `just-dna-seq/ensembl_variations`, and 0.8 pulls `just-dna-seq/ensembl_variations_split`;
   a cache mixing the two releases resolves to nothing. The default moves, and the operator procedure gains
   a 14.5 GB pull on both boxes **before** the 0.8 deploy. Required. About an hour of work plus the pull,
   which is the step most likely to set the deploy's date.
   **And `warm-caches` must see a wrong-release Ensembl cache** (found 2026-11-05 building M8, **unattended,
   with 0.28**, owner: lead): under 0.8 a 0.7 cache still resolves as present, and warm-caches leaves a
   present lane alone, so its dry run shows `✓` over the old release and the re-pull has to be upstream's
   `cache pull --only ensembl` (docs/UPGRADE.md, 0.28). The cache's `pull-record.json` names the repo it came
   from (`datasets/just-dna-seq/ensembl_variations/data` on the dev box), so the detector is a comparison,
   the `LaneAge` shape: a recorded repo that is not the lane's current one reads as stale and is re-pulled,
   an unrecorded one is *cannot say*. Ask upstream first whether `prepare_lane` already answers it on 0.8
   (it did not read the record at 5b1b73b8). About an hour.
2. **Six new spec tables** (M2). Required: an unrecognized `meta.csv` is dropped by the rebuild and moves
   the signature. The liaison's C4 (derive the row-model roster from upstream) ships earlier, as a 0.27.x
   patch with C1 and C2, because the roster already misses four tables on 0.7 (the lead's call,
   2026-11-04); M2 then only adds the six names.
3. **The catalog-wide recompile** (M3): one PATCH per variants module under plain `--apply`, `--dry-run`
   first. Required. Waits on upstream writing the 0.8.0 release record.
   **And it must survive the snapshot switch** (M12, upstream's guide § 1.30, the liaison's d351077): the
   sweep carries each stored 0.7 `resolution.csv` into a re-enrich against the new split snapshot (M8),
   and a module holding placements from both releases may refuse under strict
   (`rsid_placements_disagree`), so M3 can fail module by module. The lead decides before M3 between
   dropping the carried table (re-resolve from the snapshot, no egress, resolutions move as data) and
   re-deriving online (costly; offline leaves indel verdicts undecided); `upgrade --dry-run` shows the
   refusal either way. Required. About half a day, pre-buildable on the branch with the rest.
4. **The `/check` report shows 0.8's withheld placements and states** (M4), in the API model, the console
   types and both renderers. Required. **With it, a retired source says `retired`** (M10, RM361): never
   `unreachable`, in the ACMG list, both renderers and `unresolved_hint`, whose remedy is upgrading the
   enricher rather than re-running; this is "a pass that could not run reports why" with a new reason.
   Required. Two hours, built with M4. **Pre-built on branch `0.28`** (2026-11-05, against upstream's 0.8 at
   a4a401e7): M4 (158e239), M10 (84d4a6c, M13's test bd7fe67), C10/M14 (9f4e114), C17 (276df93), C8's minor
   half (af18b2e, the PGS leg on a paced gate ffe263d), M9 (c1706e3), M2 (be1d6db), M8 (59ddcd9, RM384 tie-back
   7a275a4). **M11 checked: nothing to change** (no code or fixture here reads a header-only sidecar; the
   full suite passes at a4a401e7, 620).
   **And `validate` takes the compile's switches** (M9, RM367): the three `validate_spec` calls pass what the
   compile gets, so the dry run and the publish reach one verdict. Required by the parity rule. Under an
   hour. **Header-only sidecars are gone** (M11, RM370): checked when the recompile runs, likely nothing
   to change here.
   **Three more report fields from 0.7, not 0.8, built here because they touch the same model and
   renderers** (added by the pm 2026-11-04/05 from the lead's b7cc45b and 22b7f52; the person was away and
   may move them to a later minor): C8's minor half (`trait_tables_not_read`, `gene_tables_not_read`, `pgs`,
   `pgs_not_checked`, and the PGS leg on a paced client in `UPSTREAMS`; its patch half ships as 0.27.x
   first) and C10 (`allele_mismatches` beside `unresolved`, a fourth `unresolved_hint` case) and C17
   (`PgxResult.recorded_use`, so a PGx leg stops reading `declared_use=unstated`). All additive. Rejected:
   a minor of their own after 0.28, which would add the same fields to the same four places a second
   time. About four to five hours together. C5's `GET /caches` cost joins them only if
   it turns out to be a new field.
5. **Publish recovery in the client** (*Decouple a large publish from its connection*, the client-side
   candidate): on a dropped connection, compare the server's stored `inputs[].sha256` with what was sent,
   with a stated deadline. Additive; the job route stays the later, real fix.
6. **The server reads the `.env` where it runs** (*`config.py` loads the `.env` above the installed
   package*): lands only with its `docs/UPGRADE.md` step checking each box's launch directory first.
7. **Rename an account's handle**, as filed (self-service and site admin).
8. **Verification records name their witness** (M5): carry `independence`, and say beside each check
   whether its agreement counts as evidence. Fits the strategy's "not a judge of the science".
9. **A ClinVar-tier facet** (M7, `stats.clin_sig_counts`): a new card filter. Needs its own short design
   before building: what an empty count means (upstream: *not counted*), and that a facet over a
   compile-time count must say over what it quantifies (CLAUDE.md, "A manifest flag scoped to one file").
10. **Name the format release a refused column arrived in**, client-side, as already shaped in its entry
    (one entry: the liaison's C3 duplicates it). Unblocked: both boxes serve format 0.7.1 since before
    2026-11-04.
11. **A real `GET /api/v1/stats`**, with `catalog_stats()` rewired and its signature kept.
12. **The toolchain as the reason a digest moved** (M7): shown where a digest moved with the content
    unchanged.
13. **Strict findings live in `errors` only** (M6): checked by the liaison (20536fe), nothing here reads
    an escalated finding from `warnings`. Kept on the list so the release notes say it was looked at.

**Not in 0.28**: dataset currency on the card (needs the operator refresh designed first), the `/check` job
queue and the online-tier paging (one subsystem, built once), Redis for the limiter and gate, the
`short_description` and `amend_display` items (wait on format), `httpx2`.

**Client surface**: moves (the rename, `catalog_stats` keeps its signature, publish recovery changes when
`publish()` raises). The release's `Client surface:` line names them.

---

## Next registry version (post-0.11)

- **A variant-level catalog, with a gene-level facet** (**decided by the person 2026-11-04 in the dream's
  triage, `docs/DREAMS.md` §7: "Yes, and gene-level facet also (should be semi-feasible with enricher)";
  after 0.28**; owner: lead; filed by the pm). Sizing: **minor**, a few weeks. Its design is the lead's
  first step: surveyed, put to a critic, and only the questions that shape it taken to the person.

  **The shape it starts from** (the dream's Opus idea 1). A rebuildable projection of every published
  version's rows (`variant_key`, allele, direction, weight, `clin_sig`, evidence), filled at ingest from
  the stored parquets, so the manifest stays the source of truth and a reindex rebuilds the table.
  `GET /variants/{key}` answers which modules say anything about, say, rs429358, and what they say. Both
  cards carry a cross-module conflict marker where two modules give one allele opposite directions. The
  gene level is the same view per gene: symbols normalised, and position-keyed rows attached to their
  gene through the enricher (HGNC currency, gene loci), snapshot-only on the request path as every proxy
  route is. A `pgs_id` facet comes with it, since modules already carry `pgs.csv`.

  **Limits it keeps.** It reports what modules say and never ranks one claim over another
  (`docs/STRATEGY.md`: not a judge of the science). A disagreement shown is a fact about two modules,
  not a verdict on either. Every new route gets a `RegistryClient` method and a parity row in the same
  patch. A gene facet built on `stats.genes` asks "over what?" first (CLAUDE.md, "A manifest flag scoped
  to one file").

- **Rename an account's handle** (**decided by the person 2026-11-04, "load up lead with user rename
  feature if we don't have yet one"; unattended**; owner: lead; filed by the pm). **Who may rename**, the
  person, 2026-11-04: "User themselves" "AND admin": an account renames its own handle, and a site admin
  may rename any account (the one site-admin act beside `merge-accounts`, so it belongs with it in
  `api/routers/admin.py` and `services/accounts.py`); rejected: site-admin only. Nothing changes `accounts.name` today: `PATCH
  /auth/whoami` edits the display name, email, avatar and funding links, and `merge-accounts` folds one
  account into another. Sizing: **minor** (a new route, a `RegistryClient` method, a parity row; no
  status moves), so it is built on the next minor's branch.

  **Facts that shape it.** A published manifest stamps `owner = account.name` (`api/routers/publish.py`).
  That field is registry-owned and outside both `artifact.digest` and `content_signature`, and the
  signature covers the digest only (`sign_digest`), so it can be amended in place as `amend_logo` and
  `amend_readme` already amend stored manifests. The person, 2026-11-04: "Its in meta, meta can be
  amended, its our item". So **a rename amends `owner` on every version the account published**, and the
  `modules.owner` projection agrees with the manifests again after a reindex. `identity.namespace` and
  `canonical_id` are a different matter, so a personal namespace claimed under the handle **does not**
  rename with it, and the response says so. Keys and `versions.published_by` are by account id, so auth
  and RBAC survive the rename.

  **Decided defaults, each reversible, listed for review.** The old handle stays reserved to the same
  account as an alias, for links and for installs holding an older copy of a manifest, so nobody else can
  claim it and inherit the look of those copies (the strategy's
  installers-first rule: an old `owner` must never point at a different person); rejected: releasing it.
  Production refuses a rename into a `test-` handle unless `allow_test_data=true`, as `issue-key` does
  (already the rule at every door, CLAUDE.md "Deployment modes").

- ✅ **done** (a96e8ac on `release-0.27.x`, in 0.27.1). **Derive `registry upgrade`'s row-model roster from upstream's** (**severity medium, unattended, first of
  the liaison's items**, owner: lead; the liaison's **C4** in `docs/UPSTREAM_COMPILER.md`). `services/upgrade.py`
  `_ROW_MODELS` is hand-kept and already stale on 0.7: it lacks `overrides.csv`, `expression_effects.csv`,
  `clin_sig_concordance.csv` and `clin_sig_authority_calls.csv`, all read by `extra="forbid"` models, so an
  unknown column in one is neither trimmed nor reported blocked and fails the recompile instead, the 0.10
  failure the roster's own comment describes. Derive it from upstream's `_TABLE_KINDS` and `_FACT_TABLES`
  (0.8 adds the public `AUTHORED_NON_KIND_TABLES`), with a denominator floor in the test. Sizing: **patch**.
  About an hour. Format 0.8 adds six more tables (the liaison's M2), which this makes free.

- ✅ **done** (in 0.27.1). **A declared correction reaches only the modules it names** (**severity low, unattended**, owner: lead;
  motivated by the liaison's **C1** in `docs/UPSTREAM_COMPILER.md`, upstream S90 / RM201, shipped in format
  0.7.0). `DeclaredChange` gained `requires`: the manifest paths a module must carry for the change to reach
  it, `()` for every module, `None` for unknown. `services/rebuild.declared_movement` reads `target`, `item`
  and `axis` and never `requires`, so a sweep still over-reaches, bounded at one PATCH per module by the
  convergence rule. Filter by `requires` against the stored manifest, `None` keeping today's behaviour, and
  correct the two CLAUDE.md passages that still call S90 open. Sizing: **patch** (no route, field or status
  moves; a sweep acts on fewer modules). About an hour with tests.

- ✅ **done, narrowed** (in 0.27.1; the bundle stays filled, because the passes here take single clients and an empty bundle would hand each `None`; the docs and the test were the real change). **Let upstream fill the shared lookup bundle** (**severity low, unattended, after the item above**, owner:
  lead; the liaison's **C2**, upstream S92 / RM206, shipped in 0.7.0). `LookupClients.ensure(name, factory)`
  makes every leg's lazy build one locked path and `close()` walks `CLIENT_FIELDS`, so
  `services/enrich.shared_lookup_clients()` constructing all eight eagerly is now redundant, not wrong.
  Hand over an empty shared bundle, keep one test that a leg's client is reused across two calls, and
  rewrite the CLAUDE.md paragraph that describes an upstream which no longer exists. Sizing: **patch**.
  About an hour.

- ✅ **The enricher gets the configured PubMind and CIViC caches** (**done 2026-11-04, 1beb158, in 0.27.1**;
  **severity high**, owner: lead; the liaison's **C7**, upstream RM134 §B / RM170, checked against the code
  2026-11-04). Both `enrich()` calls in `services/enrich.py` pass `ensembl_cache` and `clinvar_cache` only,
  though `configured_caches()` holds `pubmind` and `civic` and the installed `enrich()` takes both. The server
  never runs `export_lane_locations` outside `warm-caches`, so `None` licenses the ambient discovery CLAUDE.md's
  first enrichment rule forbids, and what it finds feeds `published_refutation` and
  `evidence_status_currency` into `verification.json`. Pass both, one test that the configured path is what
  `enrich()` receives. Sizing: **patch**. Half an hour.

- **`check_identifiers` runs on every module, not only one with `variants.csv`** (patch half ✅ **done** on `release-0.27.x`, in 0.27.1; the minor half rides 0.28) (**severity high,
  unattended**, owner: lead; the liaison's **C8**, upstream RM155 / RM156 / RM163, checked 2026-11-04).
  `services/enrich.py` returns "no variants.csv … nothing to check" before calling it, so `/check` tells a
  PGx-only module there is nothing to check while the installed pass reads every table that carries the
  columns. Two halves, by what they move. **The patch (0.27.x):** drop the early return; pass
  `write=False` (its default merges licence rows into the scratch spec); pass `check_pgs=False`, because its
  PGS Catalog client is outside the shared bundle and `pacing.UPSTREAMS`; and put the pass's `*_not_read`
  lists and "PGS accessions not checked" into the existing `warnings`, so nothing it skipped reads as clean.
  **The minor (0.28):** carry `trait_tables_not_read`, `gene_tables_not_read`, `pgs` and `pgs_not_checked`
  as fields in the API model, the console types and both renderers, and run the PGS leg on a paced client
  registered in `UPSTREAMS`. Rejected: shipping it whole in 0.28, since the wrong answer is live now; and
  dropping the early return without the warnings, which would turn an honest "nothing to check" into a
  silent clean. Two to three hours across both.

- ✅ **done** (on `release-0.27.x`, in 0.27.1). **A setting for the enricher's dataset probes** (**severity medium, unattended**, owner: lead; the liaison's
  **C9**, upstream RM85, checked 2026-11-04). `enrich(verify_datasets=True)` is the default we inherit: every
  run probes ClinVar's live VCF header and the PGS Catalog's `/rest/info` through clients outside the shared
  bundle and the pace ledger. Add `enrich_verify_datasets` beside `enrich_verify_clinsig`, passed through (with
  `release_probes=` where it applies). **Default off**, because an unpaced probe on every `/check` is egress the
  ledger cannot see; the record then says the check was not run, which is the honest state, and an operator
  turns it on. Rejected: default on (today's behaviour), which keeps the unmetered egress. Sizing: **patch**
  (a setting, no route or field). About an hour.

- **Four small corrections, one patch commit each** (**severity low, unattended, with the 0.27.x patches**,
  owner: lead).
  - ✅ done (4ecbffd, main). *The card subtitle is 240 characters, not 120* (noticed by the liaison 2026-11-04):
    `client.py:1066`, `client_cli.py:483`, `api/routers/publish.py:779` and `models/api.py:319` still say
    120 where `services/publish.SHORT_DESCRIPTION_MAX_CHARS` is 240. Minutes; a test that the four read the
    constant's number would keep them true.
  - ✅ done (db072b8, in 0.27.1). *`pacing.py:291-296`* says nothing downstream reports what it spent and names S92; `PacingGate.spent`
    exists since 0.7.0 and the filing was S95 (the liaison's **C6**). Correct the text. **Decided: the meter
    is not reconciled from `spent`**; charging before the call is what lets the ledger refuse, and a second
    count after it would be two ledgers. Rejected: reconciling. Minutes.
  - ✅ done (in 0.27.1). *Strictness can add a finding* (the liaison's **C11**, upstream RM218 with RM141 / RM143): the comments at
    `services/enrich.py` around `would_publish_module_level` and CLAUDE.md's "the dry run grades where the
    publish grades" say strictness changes severity only, and upstream's strict validate now adds an
    aggregate finding of its own. The verdict holds (`_would_publish` also requires `validation.valid`).
    **Decided:** where that strict-only finding is module-level (a recorded wrong build is about the module,
    not a row), `would_publish_module_level` goes `false`, read from the finding's **code**, never its
    sentence; if upstream gives it no code to read, the field stays as it is, the text is corrected, and the
    gap is filed upstream. Rejected: leaving it `true`, which tells an author the module is fine and only rows
    need work. **Upstream's answer (their S129, relayed by the liaison 2026-11-05):** coded errors are their
    RM378, placed in their 0.9 (a correction from their triage, 2026-11-05), so the match holds through 0.8; until then the two strict-only refusals carry published, test-pinned fragments
    (their RM377, `docs/COMPILER.md` "The refusals only strict adds"), already in the installed 0.7.2. So the
    flip **matches the frozen fragment now**, as `UNJOINABLE_PHRASE` does: only the build disagreement
    (`whose coordinates the enricher diagnosed as another assembly's`) is module-level; the per-row aggregate
    (`have unresolved genomic positions after resolution`) is not and leaves the field alone. Never widen the
    match past the fragment, and move to the code when RM378 ships. About an hour.
  - ✅ done (in 0.27.1). *`gather_pmids` reads `studies.csv` only* (the liaison's **C12**, upstream RM132):
    `revalidate --check-pmids` misses PMIDs in `pharm_variants.csv` and the binning kinds; use upstream's
    `compiler.load_citing_rows` / `table_citations`. About an hour.

- **Read what upstream made public instead of mirroring it** (**severity low, unattended, after the 0.27.x
  patches**, owner: lead; the liaison's **C5**, **C13** and **C15**). `caches.lane_status()` (RM204) does what
  our `lane_status(settings)` loop does, with `occupied` for our `partial`: compose it and keep the
  `declared_use` licence skip and the path scrub, one word for the third state. `GET /caches` can then say what a
  pull costs from `CacheLane.approx_mb` and `provisioning_closure` (RM229). `enrich.collect_subjects` is public
  since RM158, so the mirrored table list at `services/enrich.py:720` goes. Sizing: **patch** unless the
  `GET /caches` cost is a new field, which goes with 0.28. About three hours together.

- **Say when the source answered and the allele did not match** (**severity low, unattended, with 0.28**, owner:
  lead; the liaison's **C10**, upstream RM154). `EnrichmentResult.allele_mismatches` (typically a strand flip) is
  read nowhere, and `unresolved_hint` offers three remedies that are all wrong for it. Carry it beside
  `unresolved` and give the hint its fourth case. Sizing: **minor** (a response field). One to two hours.

- ✅ **done** (on `release-0.27.x`, in 0.27.1). **An online run's withheld indel gets the re-run remedy, not the authoring one** (**severity medium,
  unattended, second of the 0.27.x patches after C4**, owner: lead; the liaison's **C16**, upstream RM268 in
  v0.7.3). On an online run, a REST indel whose reference base could not be read is withheld: it lands in
  `unresolved`, and the enricher says why only in a log line this server does not keep (`unanchored_rsids` reaches
  `EnrichmentResult` in 0.8's RM272, M4). `unresolved_hint` checks only `unreachable_rsids`, so this case falls
  through to "provision a fuller snapshot … or author chrom/start", sending a publisher after an outage. The
  patch: on an online run, the third branch also says an indel may have been withheld because the sequence service
  did not answer, and to re-publish once before changing anything; correct `pyproject.toml`'s 0.7.3 comment, which
  says every 0.7.3 change reaches us through existing routes. The structural fix rides M4 in 0.28. Sizing:
  **patch**. Twenty minutes.

- **`/check` says where a PGx leg's declared use came from** (**severity low, unattended, with 0.28**, owner:
  lead; the liaison's **C17**, upstream RM252 / S105 in 0.7.1). With no `declared_use`, the PGx legs read the
  module's own recorded declaration, and `PgxResult.recorded_use` says so; nothing here reads it, and
  `registry-client check` prints `declared_use=unstated` beside a CPIC leg that ran under the recorded one (upstream's
  own S105 symptom, in our renderer). Carry the field in `models/api.py`, `console/src/types.ts` and both
  renderers. Sizing: **minor** (a response field). An hour.

- **Rederive an uploaded `resolution.csv` on `/check`?** (**severity low, waits until the 0.27.x patches are
  merged; weigh first**, owner: lead; the liaison's **C18**, upstream RM268 / RM271). An uploaded pre-0.7.3
  `resolution.csv` keeps rows 0.7.3 would now derive differently; `enrich(rederive=True)` re-asks every subject,
  and `EnrichmentResult.rederived` reports what moved. Neither call passes it. Rederiving spends egress on an
  unprovisioned box, so the question is whether it runs snapshot-only (free) or not at all. Two hours once
  weighed.

- **The ClinVar counts on `stats` say what they count** (**severity low, waits until upstream tags RM299**,
  owner: lead; the liaison's **C19**). `models/api.py`'s `pathogenic_count`, `clinvar_count` and `benign_count`
  carry no description in the OpenAPI schema, the misreading behind S123. Take upstream's descriptions once their
  patch is tagged. Sizing: **patch**. Fifteen minutes.

- ~~**Serve manifests compressed**~~ (the liaison's **C14**, upstream RM138: `carried` makes a manifest 1.84×
  raw, 1.06× gzipped). **Canceled: already true, 2026-11-04.** `api/app.py` adds no GZip middleware, but both
  boxes answer `content-encoding: gzip` with `vary: Accept-Encoding` (their proxy does it). The check, run
  2026-11-04 on both hosts:
  `curl -s -D - -o /dev/null -H 'Accept-Encoding: gzip' 'https://module-registry.just-dna.life/api/v1/modules?per_page=100' | grep -i content-encoding`.
  A deployment without such a proxy would need the middleware; none is known.

- **`config.py` loads the `.env` above the installed package, not the one where the server runs**
  (**severity low, open — needs an operator step, not scheduled**; motivated by **S27**). The module
  calls a bare `load_dotenv()` at import, and python-dotenv walks up from the calling *file*, so it
  finds whatever `.env` sits above `site-packages/just_dna_registry/`. The 0.18.1 entry above already
  measured the consequence: in a checkout the walk and the working directory agree, and in a container
  they do not, so the enricher (which uses the working directory) and our own settings can read two
  different files. 0.27.1 fixed the same shape in `registry-client`, where it was sending a project's
  commands to whatever server the checkout's `.env` named. The server was left alone on purpose.

  **Why not the same one-line fix here.** `usecwd=True` changes which file a *running deployment*
  loads, and nothing from this repo can see how either box is launched (its working directory, a
  unit file's `EnvironmentFile`, a compose `env_file`). If a box relies on the walk finding the
  checkout's `.env` while it runs from elsewhere, the change silently drops its configuration at the
  next restart, and a server that boots with defaults does not look broken until a rule fires. The
  right fix is `usecwd=True`, or moving the load out of import into `registry serve` and the admin
  CLI's root callback. It lands together with an UPGRADE.md step that checks each box's launch
  directory first. Moving it out of import also stops every `Settings()` in the test suite reading a
  developer's `.env`, which is its own small win.

- **Decouple a large publish from its connection** (**severity medium, open — not scheduled**;
  motivated by **S26**, and **restored**: the 0.4.4 changelog said "Decoupling publish (`202` +
  background compile + poll) is tracked in ROADMAP 0.5", and no roadmap since has carried it). A
  publish holds one HTTP connection across the whole enrich and compile, and a genome-wide ClinVar
  panel takes long enough that a proxy closes it first. The server finishes and indexes the version;
  the client sees `RemoteProtocolError` for a publish that landed. 0.27 makes the retry *safe* (the
  late `409 version_exists`, which also closed an overwrite of the stored bytes) and documents
  *verify before retrying*. Neither stops the false failure, and the panels grow with every ClinVar
  release.

  **Candidates, and what is wrong with the ones that are wrong.**

  - *A job route* (`202` + a job id + polling), which is what the reporter asked for first. It is the
    real fix and a whole subsystem: a jobs table, a runner that outlives a restart, a TTL, an SDK
    method that polls, and a decision on what an abandoned job holds. The `/check` queue bullet below
    is the same subsystem, and the two should be built once.
  - *Make an identical re-publish a `200`*, the reporter's second option. It changes the status a
    client already sees on this route from `409` to `200`, which the legality table sizes as
    **major**, and "identical" needs a definition: `artifact.digest` is not one (it moves between two
    compiles of one spec), so it would have to be `content_signature` plus every non-signature file.
    Out.
  - *Recover in the client.* On a dropped connection, `publish()` asks the server for the version and
    compares `manifest.inputs[].sha256` with the bytes it sent, which needs no compiler tier because
    those hashes are over raw input bytes. A match returns the manifest as though the response had
    arrived. It is additive (a call that raised now succeeds) and works against any server. It cannot
    tell *still compiling* from *never arrived*, so it needs a bounded wait with a stated deadline
    and has to say which one it gave up on. **The cheapest real improvement**; the job route
    supersedes it rather than competing with it.
  - *Raise `max_upload_bytes`*, from the reporter's closing note. Out, for the standing reason: it
    mirrors the HAProxy body cap, and raising it past the proxy only turns a structured `413` into a
    severed connection. `pathogenic` at 20 of 25 MiB packed is a real warning, and it goes to the
    operator who owns the proxy, not into this setting.

- **Tell a catalog reader that a module's source has published since it was drafted** (**severity
  medium, open — not scheduled**; motivated by **S24**, relayed from just-dna-format's RM85). Enricher
  0.7's `currency.check_dataset_currency` compares each `sources.csv` `dataset` label against the
  release its source publishes now, but it runs at enrich time and tells the **author**. The reader
  who needs it is browsing the catalog months later, and RM85 left the catalog side to us on purpose.
  Sizing when built: **minor** (a new response field, no status or verdict moves).

  **What already reaches a reader, and why it is not the answer.** When a publish enriches, a
  `dataset_currency` record lands in `manifest.verification` and the detail view carries it verbatim
  through `VerificationInfo.checks` (`source`, `release`, `skipped`, `checked_at`). That is the
  enrich-time answer: frozen at publish, so it goes stale by construction, and it is in the
  unverifiable-claim block that is deliberately never a facet. The ask is for a comparison made at
  *read* time, which nothing here does.

  **Candidates, and what is wrong with the ones that are wrong.**

  - *Probe the source on the request path.* Out. The listing and detail routes are anonymous reads on
    the 60/min search budget. A ClinVar probe streams up to 256 KB of the VCF, and the caching-proxy
    rule is that a request path never reaches a remote source to answer a read. Caching the answer
    per source does not fix this, because the first reader after expiry still pays the egress.
  - *An operator-side refresh.* A `registry` command, run on a schedule, asks each member of
    `currency.PROBE_SOURCES` once and stores `(source, current label, checked_at)` in the index. The
    detail view then compares each version's recorded labels against the stored ones. There is no
    egress on a request path and the table is a rebuildable projection. **This is the likely shape.**
    It needs `checked_at` shown beside the verdict, because "current as of the last refresh" is the
    only claim it can make.
  - *The box's own snapshot as a one-way witness.* `lane_status()` already reads each lane's
    `release_label`, so a held ClinVar snapshot names a release at zero cost. A snapshot *newer* than
    a module's recorded label proves `behind`. An *equal* one proves nothing, since the box may be
    stale itself. Usable as a supplement to the refresh, never as its replacement.

  **Rules the build has to keep.**

  - **Reuse the check, never re-derive it.** Call `check_dataset_currency(rows, probes=…)` with
    injected probes that return the stored label. Comparability lives there: `_label_kind` refuses to
    compare a `clinvar_<date>` label against a `clinvar_sha256:…` one, and that answer is
    `no_reference`, not a mismatch. The enricher is the optional tier, so import it lazily in
    `services/`, as the other passes do.
  - **Read `PROBE_SOURCES`, never a list.** The enricher installed here probes ClinVar **and** the PGS
    Catalog (RM163), so S24's "only ClinVar" was already out of date when it arrived. A hand-kept list
    would go stale the same way.
  - **Tri-state, with the reason beside it.** `DatasetCurrency.behind` is `True` / `False` / `None`,
    and every `None` carries `unchecked` ∈ `offline` / `unreachable` / `no_reference` /
    `unsupported`. `None` renders as unknown and never as current, on the page as well as in the
    JSON. The console's check renderer rule applies unchanged.
  - **"Recorded" comes from the stored sidecar, not the manifest.** `manifest.sources` summarizes the
    licensing table without its `dataset` column, so the labels have to be read from the stored
    `licensing.csv` / `sources.csv`. `services/rebuild.py` does the same kind of read for its probes.
    A version stored without the sidecar has no claim to compare, which makes it
    `nothing_to_check`, not current.
  - **A different trust class from `VerificationInfo`.** This verdict is computed here, from our own
    probe, so whether it may filter or sort is a decision in its own right. It must not inherit the
    publisher-claim block's "never a facet" rule by accident, and it must not be merged into that
    block either.
  - **A fourth witness, not a rebuild trigger.** `needs_upgrade` and `rebuild.RebuildVerdict` are
    about the *compiler* moving; this is about the *world* moving. A module behind its source is
    fixed by the author re-drafting from a fresh spec directory (a re-draft appends beside the
    superseded rows, so an in-place one makes things worse), never by `registry upgrade`.

- **Name the format release a rejected column arrived in** (**severity medium, unattended**: its gate, the format 0.7
  deployment in the next bullet, was met on 2026-11-04; owner: lead; motivated by **S18**, reopened and
  corrected by **S21**; the liaison's **C3** of 2026-11-04 restated it and was folded in here). 0.22.0 ships the half this service can compute on its
  own: `format_version` on every dry-run report and `format_advisory` when the caller's format is
  newer at patch grain. What it still cannot say is the sentence the consumer actually asked for —
  *`curator` is a 0.6.5 field* — because that needs a map from a spec column to the release that
  introduced it, and hand-keeping one here is how the `RENAMED_ON_UPLOAD` spellings got out of step
  with upstream in the first place.

  **0.24 update: the blocker is half gone, and the half that remains is a different ask.** Format 0.7
  ships RM146 — `base.since` declares the release a field first appeared in, and
  `base.field_first_seen(model)` reads it back as `{field: release}`. That is the input-side roster
  this item was waiting for, and upstream's own integration guide names this exact use: it is what
  tells an "Extra inputs are not permitted" finding apart from a typo.

  **0.25 correction (S21): the map is public, and this bullet said otherwise for a release.** The
  0.24 paragraph claimed the **filename → row model** mapping was only
  `just_dna_compiler.compiler._TABLE_KINDS`, private, and asked upstream for `first_seen` on
  `reference.authoring_reference()`'s field entries to route around it. `hints.model_for` is public,
  in the compiler tier, and is that map: `model_for("studies.csv") -> StudyRow`, composed with
  `field_first_seen` to give `'0.6.5'`. Upstream's S81 is answered and RM146 shipped, so no ask is
  outstanding. What survives is the **tier**, not the privacy — `model_for` is in `just-dna-compiler`,
  an optional extra for a thin client, so the surface degrades where the extra is absent rather than
  being unconditional. (`authoring_reference()` remains light-tier, keyed by class name, and carries
  neither filename nor `first_seen`; that is a description of it, not a gap anyone is waiting on.)

  **Two constraints on the shape, both of which rule out the obvious implementation.** It cannot run
  on the **server**: the advisory fires when the client is newer, so the server holds the older
  models and a 0.6.1 instance has no `curator` on `StudyRow` at all — `field_first_seen` over its own
  schema cannot by construction contain the column in question. And it cannot read the **finding**:
  `ValidationResult.errors` is `list[str]` with no structured `(file, field)`, so recovering the
  column name from *"studies.csv line 2 [curator]: Extra inputs are not permitted"* means matching
  pydantic's sentence, which is the wording rule in CLAUDE.md and the signature property S18's reply
  pinned a test around.

  **So the legal shape is a client-side enumeration**, derived from the two version strings and the
  schema alone:

  ```python
  {csv: {f: rel for f, rel in field_first_seen(model_for(csv)).items()
         if server_format < rel <= client_format}}
  ```

  rendered beside the advisory in `registry-client validate` / `check`. The author matches the
  refused column against that list; a column present in it means the instance is behind, a column in
  no list at any release is a typo. Nothing here reads an error string, which is the same property
  the current advisory has, kept by construction rather than by care.

  **Scheduled after the format 0.7 deployment, not before it.** The advisory is a *patch*-grain
  surface — it fires only within a minor — and the pair that motivated this (server 0.6.1, client
  0.7.0) is a MINOR gap that `compatibility_error` refuses outright. So this improves the first
  within-minor skew *after* the cut in the bullet below, and lands in the release following it.

  **Do not close this by reading `release_records`' `parquet_schema` axis.** Format 0.7 (RM126) ships
  a per-release record whose `parquet_schema` targets are spelled `file:column`, and for `curator` it
  would happen to give the right answer. It is a channel about compiled **output**: an optional
  authored column that no module in the interval set, or a column the compiler does not emit,
  never appears on it — so reading it as an input-schema roster is the same category error as using
  `artifact.digest` to ask "same module?". Upstream measured it after we filed **S81** (their ledger):
  the axis names **4 of 402** authored columns, and `curator` is one of them — the right answer for
  the case in hand and silent wrong answers for 398 others, where absence reads as *this column has
  always been legal*. `field_first_seen` is the input-side counterpart and it shipped as RM146; that
  is the roster to read, and this paragraph stays as the reason not to reach for the other one.

- **The instances run format 0.7 before this package is published to PyPI** (**done 2026-11-04**, measured: both
  instances answer `/api/v1/version` with registry 0.27.0, format 0.7.1, compiler 0.7.2, and PyPI serves
  just-dna-registry 0.27.0; motivated by **S20**). Kept for the ceiling argument below. Not a code item and deliberately filed here anyway, because it is the one
  release step whose omission breaks every consumer at once and nothing in the tree can assert it.

  0.25.0's own base dependency is `just-dna-format>=0.7.0`. So the day this package reaches PyPI, a
  fresh `uv sync` in any consumer resolves our client to a 0.7 client, and against the live boxes —
  both still answering format `0.6.1`, re-measured 2026-09-11 — every write path returns the `409`
  contract mismatch while reads
  keep working. That reads as a partial outage rather than a version skew, which is what makes it
  expensive to diagnose from outside. The trigger is ours as much as upstream's: even with the format
  cut timed by somebody else, publishing this package first arms the same failure with no consumer
  having chosen anything.

  **Order: deploy both instances on 0.25 / format 0.7, then publish.** The window is then zero rather
  than however long a deployment takes to schedule — which is the residue S18's ask 3 left behind, met
  properly this time instead of being flagged.

  **A format *ceiling* on our dependencies is not the fix, and the argument is worth keeping because
  it will be proposed again.** `just-dna-format>=0.7.0,<0.8` would turn "publishing is dead" into "the
  resolver holds you at 0.7.x", which looks strictly better and is not. It cannot help the release
  already on PyPI, which is ceiling-less and is what a consumer installs today. The claim would be
  false — a 0.7 client against a 0.7 server works; what fails is a *pairing with one instance*, and a
  dependency specifier cannot see an instance, so this is a static declaration standing in for a
  measurement that exists (`contract_compatible` over `GET /api/v1/version`, which is correct and
  which consumers already build on). And it never protects independently of the floor it travels with:
  adopting 0.8 moves `<0.8` to `<0.9` in the same release that moves the floor, so the window where
  the ceiling is wrong is exactly the window it was meant to cover, and outside that window it binds
  only a consumer wanting the new minor for reasons unrelated to us. **A floor states our own code's
  requirements and is true whatever anyone deployed; a ceiling here would state a third party's
  release schedule.** Only the first belongs in a dependency specifier.

- **Adopt `manifest.readme` when format 0.6 lands** (**done in 0.17**). Shipped as filed: publish
  and `amend_readme` both set the entry, `/files/{path}` and the tarball admit the file without their
  rules changing (they serve what the manifest attests), and `verify_manifest(check_readme=True)`
  re-hashes it on download. `tests/test_v05.py::test_the_readme_reaches_the_card_but_not_a_downloader`
  was rewritten rather than deleted — it was pinning a limitation, and this item named it as the one
  to change.

  Two decisions the item asked for, and what they resolved to. The DB projection is *derivable* in
  the sense that mattered: the text is a hash rather than a copy, so the manifest cannot carry the
  prose, but it now names **which file is the readme**, and the publish path reads
  `manifest.readme.name` rather than the constant. `upsert_module(readme=None)` still means "leave
  it" and should stay that way — that guard is about a caller that does not know about readmes, which
  no manifest field fixes. And on upstream's wider `README_CANDIDATES` ladder: ours stays a single
  `README.md` plus the `MODULE.md` rename, because following the manifest's own `readme.name` gets us
  their resolution for free wherever the compiler applied it, and inventing a second answer to "which
  file is the readme" is the drift this item existed to end (S7 stays a warning).
- **Decide what to do with `verification.json` once format 0.6 can attest it** (**done in 0.17** —
  the second half of **S11**). All three decisions were made deliberately and the evidence for them is
  in `tests/test_specfiles.py::test_a_publisher_cannot_forge_a_check_this_server_runs`, because the
  answers turned on a question nobody had measured: **how much of that block is actually ours**.

  **(1) Surfaced, on the detail only.** Not because it is trustworthy but because it is now partly
  ours: this server runs enrichment on the publish path and attests what it saw, and that record
  *displaces* an uploaded one for the same check. A publisher cannot forge a check we run. **(2)** A
  check we do **not** run is carried verbatim and is unverifiable — that is the residual surface, so
  nothing in the block is presented as a registry verdict, and it is deliberately not a card facet,
  not a filter and not a sort key. **(3)** The closure earns a boolean of its own: it is hash-bound,
  the compiler recomputes the binding and drops a closure whose authored bytes moved, so `closed:
  true` cannot be claimed by editing a file. `closed_by` remains free text and proves that somebody
  declared authoring finished, not who. An Ed25519 signature over it would add a *who*, and that is
  worth revisiting only if signed closures start appearing in the wild.

- **A successful publish drops its enrichment findings.** `EnrichOutcome.notes` is read in exactly one
  place — a *failed* compile's `warnings` (`services/publish.py`) — so on the happy path the ref-allele
  result, the non-fatal stale rsIDs, the PAR drops and the new `clin_sig_not_checked` reason are
  computed and discarded. The publisher is told least when the publish worked, which is backwards, and
  `/check` already reports all of it. The fix is to carry them on the publish response; the deeper half
  (a *downloader* can never learn which checks ran, because the manifest records none of it) needs a
  format field and is filed upstream as S8 in `just-dna-format` `docs/CONSUMER_SUGGESTIONS.md`.
- **A real `GET /api/v1/stats`** (open; minor — surfaced while answering **S4**).
  `RegistryClient.catalog_stats()` aggregates downloads/stars/views/reviews/genes/variants by
  **paging the entire catalog** — its own docstring says "there is no dedicated stats endpoint, so
  this rolls up the card fields". N requests for one answer, and it degrades as the catalog grows.
  The repair is one SQL aggregate behind an endpoint with `catalog_stats()` rewired onto it; the
  method's signature and returned keys can stay exactly as they are, so a consumer sees nothing but
  latency. Deliberately kept **off** `/health`, which stays cheap, unauthenticated and probeable:
  these are heavier, and the scoped forms (`namespace=`, `group=`) belong on a real route with an
  SDK method and a parity row rather than in a liveness body.
- **Publish the client surface as an enumerated contract** (open; minor — **S2** from
  `just-module-creator`, options 1 and 2). 0.13 shipped the cheap half: a `Client surface:` line per
  release and a normative-version stamp on both reference docs. The larger ask is a contract
  enumerated independently of the package version — "contract v1: these methods, these payloads,
  this error vocabulary; spoken by client ≥x, served by server ≥y" — so a consumer pins the contract
  and ignores releases that do not move it. Worth noting that the enumeration already exists and is
  machine-checked: `_WRAPPED_ROUTES` in `tests/test_client_sdk.py` pairs every route with its client
  method across *both* modes and fails when one gains a route the other lacks. What is missing is
  publishing it in a form a consumer can read, and a versioning axis of its own. The second is the
  commitment: a contract version that is not the package version is a promise to keep it stable
  across package releases, and breaking that is worse than never having offered it.

  **Option 2 (marking methods public-vs-internal in code) turns out to be already satisfied**,
  checked in 0.16.2 rather than assumed: `RegistryClient` exposes 54 public methods and exactly three
  underscored helpers (`_json`, `_raise_for_status`, `_fetch_file`), and every non-underscored method
  is one a consumer is meant to call. The convention is the leading underscore, not `__all__`, which
  this repo avoids — so there is nothing to mark, and what S2 actually wants from that half is the
  list *published* rather than merely inferable. That is the same gap as the paragraph above, which
  is where the remaining work is; do not re-open this as a separate task.
- **Retire Eliot → stdlib `logging`.** (Carried over; still pending.)
- **Redis-backed limiter *and* concurrency gate.** Both are process-local today, so with two replicas
  every limit is 2× — and gnomAD pacing in particular does not survive horizontal scaling without a
  shared gate. The gate is the newer half of that problem and the easier one to forget.
- **An async job queue for `/check`**, if the synchronous form proves too slow in practice. Deferred
  deliberately: it is a whole subsystem (jobs table, runner, TTL, SDK polling) and the sync form with
  a 300s cap covers the offline and small-online cases, which is most of them.
- **Page or sample the *online* variant tier** (open; medium — the second option in **S1** from
  `just-module-creator`). 0.13 answered the rest of that item: offline runs lost the ceiling
  entirely, the `422` now carries the module-level verdict, and `/validate` composes it into
  `would_publish_module_level`. What is left is the case where a large panel wants the checks only
  live upstreams can do — a reference allele against the genome, a `clin_sig` against ClinVar —
  which no amount of restructuring makes cheap: at ~6s per twenty subjects a 40k-variant panel is
  over three hours of pure pacing against a budget we cannot buy our way out of. So the repair is
  not a bigger ceiling but a partial answer with its coverage stated (`checked: n of m`, sampled or
  paged), and a partial answer nobody is waiting on is a job, not a request — which is why this sits
  behind the queue above rather than beside it. Sampling additionally needs a rule for what a clean
  sample licenses a caller to conclude; without one it is a `would_publish` that means less than it
  says, which is the failure 0.13 was fixing.
- **gnomAD gene-constraint enrichment** (`enrich_gene_metrics`) on the publish path, once the
  constraint snapshot is routinely provisioned.
- **`licensing.csv` is dropped silently, and the card then advertises a permissive licence**
  (**fixed in 0.16.2** — found 2026-08-12 while running the suite for S8/S9, not reported by anyone).
  Upstream's RM51 made `licensing.csv` the spelling of `sources.csv` and the PGx reference example was
  rewritten onto it, so `tests/test_specfiles.py::test_the_licensing_facet_surfaces_a_no_sale_clause`
  **failed at HEAD** (verified in a clean worktree at `a903a88`, so not a regression from that batch).
  It was worse than a red test: the file is not in `RECOGNIZED_SPEC_FILES`, so it never reached the
  compile, and the `sources` summary was left holding the *enricher's* single Ensembl row —
  `commercial_use: True`, `licenses: ["Apache-2.0"]` — for a module whose real upstreams carry a
  no-sale clause. A facet meaning "permitted" produced by a history that only means "nobody told us",
  which is the sibling-field rule from `CLAUDE.md` broken at the input stage rather than the output one.

  The item planned a warning and deferred the repair to 0.6 lockstep, on the reasoning that "passing
  the bytes through would put them in front of a reader that does not know the name". That reasoning
  holds for *recognising* the file and not for **renaming** it, which is what shipped: the 0.6 header
  is field-for-field the installed 0.5.4 `SourceRow` (checked, not assumed — and the model is
  `extra="forbid"`, so a drift would have failed the compile rather than published something wrong),
  so `licensing.csv` → `sources.csv` in `plan_layout` puts the ledger in front of a reader that knows
  the name exactly. The `SIGNATURE_INPUTS` question the item wanted answered deliberately is answered:
  the destination is a fact sidecar, outside the signature, so no spelling can move a
  `content_signature` or its global `409 duplicate_content` claim — and a test now asserts that over
  every entry in the rename map rather than for this one file. The facet test is green again with no
  change to what it asserts, and it now guards on the example's shape so the next upstream move fails
  with a sentence instead of a bare `assert True is False`.

  **Both remaining halves landed in 0.17**, and the pass found a third thing the item had not
  predicted. `licensing.csv` is recognized, and the rename **inverted**: the 0.6 compiler prefers the
  new spelling and warns on the old, so renaming forward is what keeps a legacy spec publishable at
  1.0 — and leaving it pointing backwards would have stamped a deprecation warning into every
  published manifest, permanently. Both spellings present is now a `422` rather than a warning,
  matching upstream RM49, because `layout.resolve_sidecar` **raises**: our warn-and-prefer would no
  longer have produced a publish at all, only a `SidecarCollision` with our own upload as the cause.

  The unpredicted part: the direction is no longer written down. `RENAMED_ON_UPLOAD` is derived from
  `just_dna_format.layout.SIDECAR_SPELLINGS`, so the next sidecar rename arrives with a floor bump
  instead of an incident.

- **Decide what to do about `httpx2` before starlette makes it not a choice.** The suite emits one
  warning and has since before 0.17: starlette 1.6 deprecates driving `TestClient` with `httpx` and
  points at `httpx2`. It is *not* ours to fix in a hurry — nothing in `src/` touches the test client,
  and the warning is about how the tests reach the app rather than about the app — but the SDK's own
  transport is `httpx>=0.28.1`, and that is the part with a decision in it: `RegistryClient` is the
  reference client, so its dependency is a consumer-facing choice and not an implementation detail.
  Two things to establish before moving: whether `httpx2` is a drop-in for the client's own calls, and
  whether a consumer already pinned to `httpx` 0.x can still install us if we move. Recorded here
  rather than acted on inside a contract cut, where an unrelated transport swap is exactly the change
  nobody would think to look at when something breaks.

- **Read a bounded `short_description` on the card when format publishes one** (**minor**, open — the
  card half of **S16**). `ModuleCard.description` is a bare required `str` (`models/api.py:260`), so one
  author writing a paragraph reshapes the grid for everyone: `just-module-creator` measured the
  production catalog at 8 to 79 words, six of seven rendering as two to five sentences, and four of the
  five reference specs ending in the *same* sentence — on a results page a subtitle four modules share
  is doing the opposite of its job. The fix is additive and small: prefer `short_description` when the
  manifest carries one, fall back to `description` exactly as today when it does not, so nothing
  published changes and no card goes blank.

  **It gates only on the field existing**, which is a weaker condition than the binding ruling the other
  half waits on — format can add a bounded `short_description` under either exit of their **S64**. **No
  interim length bound here**, and the reason is the sidecar-map lesson: a warning from `/validate` would
  invent the number the schema is being asked to own, and when `max_length` lands upstream its validator
  surfaces the bound through `/validate` for free, which is also the only version that reaches the author
  while they are still writing. Render-side truncation is rejected outright — the reporter rejected it
  first, and it hides prose the author chose while leaving the spec exactly as wrong.

- **`amend_display`, if and only if format splits the attestation binding** (**minor**, open and
  **conditional** — the endpoint half of **S16**, gated on upstream **S64**). The `Display` block —
  `title`, `description`, `report_title`, `icon`, `icon_set`, `color` — is out of `artifact.digest` and
  out of `content_signature`, which is the definition `amend_readme`'s own docstring uses for the amend
  family, and it is nonetheless unamendable: the block arrives inside `module_spec.yaml`, and
  `module_spec.yaml` is a `manifest.inputs` member. So the one piece of prose that renders first in the
  grid is the one that costs a version number and a `content_hash` `yank` will not release, and — per the
  reporter's measurement, which is upstream's to adjudicate — the module's closure record with it.

  **This is conditional and must not be read as a promise.** S64 offers format two exits and says a
  justification is a complete answer. If they justify the binding, **this entry closes as will-not-build**
  and a badly-shaped subtitle stays a new-version problem; only exit (b), splitting the binding along the
  line `content_signature` already draws, ends in an endpoint here. Build the whole `Display` model when
  it comes, not `description` alone: all six share the status, and six endpoints or one arbitrary subset
  both age worse than one.

  **A third route exists and is rejected on the record, so it is not rediscovered as a shortcut.** We
  could carry a registry-owned display override on the manifest the way `manifest.readme` is carried,
  touching no `module_spec.yaml` and needing nothing from format. It pre-empts S64 in *both* directions:
  redundant machinery we would keep forever if the binding splits, and precisely the substitution the
  justification would prohibit if it does not. It also costs what neither exit costs — a downloaded spec
  stops reproducing the card it came from, and a re-publish from that download silently reverts the
  amendment, which is S64's own *"two different answers to did my edit count"* moved one layer up.

  **Neither exit repairs the seven modules already published.** A binding split is prospective and those
  manifests are immutable; shortening one costs its author a version and their closure record, which is
  each author's call.

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
