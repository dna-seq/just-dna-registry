# just-dna-registry — REST API Reference

Exhaustive reference for the registry HTTP API (v1). For the design rationale see
[SPEC.md](SPEC.md); for the reference client see [CLIENT.md](CLIENT.md).

- **Normative for:** registry **0.14.x–0.16.x**, API `v1` (0.15 added no route; it wrapped an
  existing one in the CLI. 0.16 added no route either: one response field on the dry runs, and a
  verdict that stopped disagreeing with the publish gate). Written against the server at that version; a
  deployment reports its own with `GET /api/v1/version` (and its `mode` with `GET /health`). Every
  schema below is exact for a server in that range rather than indicative, so a consumer does not
  have to write defensive code against shapes we already specified (S2).
- **Base URL:** `https://module-registry.just-dna.life` (production; the polygon is
  `module-polygon.just-dna.life`). Ask the host which it is — `GET /health` reports `mode`.
  `module-marketplace.just-dna.life` is a **former** name from before the 0.9 rename, kept as a
  legacy domain and used in no current documentation. If you meet it somewhere, it is old, not a
  third deployment.
- **API prefix:** `/api/v1` (health lives at the root, `/health`)
- **Interactive docs:** `/docs` (Swagger UI), `/openapi.json`
- **Content types:** responses are JSON unless noted; publish/import use `multipart/form-data`;
  file downloads are `application/octet-stream` (or `302` redirect) and tarballs `application/gzip`.

## Authentication

Static API keys via a bearer header:

```
Authorization: Bearer mk_live_…
```

Keys are minted server-side with `registry issue-key <account> -n <namespace>` (or self-service
via `POST /auth/register`). A key's account owns one or more **namespaces**; publishing/yanking
under a namespace requires ownership. **Reads are anonymous;** only publish, import, yank, and
`whoami` require a token.

**Optional JWT sessions.** When the server sets `jwt_secret`, `POST /auth/tokens` exchanges an API
key for a short-lived JWT that is also accepted as a bearer. Static API keys always work — JWT is
purely additive; if `jwt_secret` is unset, `POST /auth/tokens` returns `501 jwt_disabled`.

## Pagination

List endpoints accept `?page` (≥1, default 1) and `?per_page` (≥1, default 20, clamped to **100**)
and return an envelope:

```json
{ "items": [ … ], "total": 47, "page": 1, "per_page": 20 }
```

## Errors

FastAPI shape: `{"detail": …}`. Simple guards use a string code; publish/import validation failures
use an object.

| Status | `detail` | When |
|---|---|---|
| `401` | `missing_bearer_token` / `invalid_token` | no/invalid `Authorization` on an authed route |
| `403` | `not_namespace_member` | token isn't a member of the path namespace |
| `403` | `not_namespace_owner` | member action requires the `owner` role (member management) |
| `404` | `module_not_found` / `version_not_found` / `file_not_found` / `account_not_found` / `not_a_member` | unknown module/version/file/account/member |
| `409` | `version_exists` | re-publishing an existing `(ns, name, version)` (immutable) |
| `409` | `last_owner` | removing a namespace's only owner |
| `409` | `duplicate_content` | the same authored data is already published under a different `(ns, name)` |
| `409` | `account_taken` / `email_taken` | self-registration collision |
| `413` | `{ "error": "upload_too_large", ... }` | the bytes on the wire exceed `max_upload_bytes` — summed multipart parts, or an archive's compressed size. Fix: send the spec as an `archive=` part instead |
| `413` | `{ "error": "archive_too_large", ... }` | the archive *expands* past `max_extracted_bytes`, measured from its member headers before anything is written. Compressing harder does not fix this one |
| `422` | `invalid_version` | version isn't SemVer `MAJOR.MINOR.PATCH` |
| `422` | `invalid_install_id` / `invalid_account` | bad proof-of-work / account name at registration |
| `422` | `lookup_needs_one_key` | `/modules/lookup` got neither or both of `digest`/`signature` |
| `422` | `{ "error": "<code>", "errors": [...], "warnings": [...], "info": [...] }` | spec/import failure (see below) |
| `429` | `rate_limited` | token bucket exhausted; `Retry-After` header |
| `501` | `jwt_disabled` | `POST /auth/tokens` on a server with no `jwt_secret` |
| `403` | `self_register_disabled` | `POST /auth/register` when the server has it off |
| `404` | `signing_not_configured` | `GET /pubkey` on a server that does not sign |
| `503` | `{ "error": "enrichment_unavailable", "missing": [...] }` | `/check` on a server where the enrichment tier cannot run at all (e.g. `just-dna-enricher` not installed). **No `Retry-After`** — retrying does not help until an operator changes the deployment. A *missing snapshot* is **not** this: it degrades with a note in `enrichment.notes`, since an online run resolves via live Ensembl without one |
| `422` | `license_refused` | `/check?pgx=true&declared_use=commercial` against a source that forbids sale — a contradiction, refused at acquisition, nothing fetched |
| `503` | `enrichment_busy` | `/check` while `enrich_max_concurrency` runs are already in flight |
| `504` | `enrichment_timeout` | `/check` exceeded `enrich_timeout_seconds` |

**A validation finding is a `200`, not a `422`.** `POST .../validate` and `POST .../check` return
`valid: false` with the reasons in the body; only a request no spec directory can be assembled from
is a 4xx. Publish is the opposite — there, an invalid spec *is* the failure.

Publish/import `422.error` codes: `missing_spec_files`, `invalid_spec` (carries
`ValidationResult.errors`/`warnings`), `compile_failed`, `name_mismatch`, and for import
`unsafe_archive`, `bad_archive`, `no_module_content`.

---

## Endpoints

| # | Method | Path | Auth | Purpose |
|---|---|---|---|---|
| 1 | GET | `/health` | — | Liveness + `mode`, uptime, gate occupancy, catalog counts |
| 2 | GET | `/api/v1/modules` | — | List / search (card grid) |
| 3 | GET | `/api/v1/modules/lookup?digest=` | — | Find versions by artifact digest |
| 4 | GET | `/api/v1/modules/{ns}/{name}` | — | Module detail |
| 5 | GET | `/api/v1/modules/{ns}/{name}/versions` | — | Version list |
| 6 | GET | `/api/v1/modules/{ns}/{name}/versions/{v}/manifest` | — | Full manifest |
| 7 | GET | `/api/v1/modules/{ns}/{name}/versions/{v}/logs` | — | Provenance/run logs listing |
| 8 | GET | `/api/v1/modules/{ns}/{name}/versions/{v}/files/{path}` | — | Fetch one file (parquet/log/input) |
| 9 | GET | `/api/v1/modules/{ns}/{name}/versions/{v}/download` | — | Per-file descriptors or tar.gz |
| 10 | POST | `/api/v1/modules/{ns}/{name}/versions` | bearer | Publish (multipart spec) |
| 11 | POST | `/api/v1/modules/{ns}/{name}/versions/import` | bearer | Publish from zip/tar.gz archive |
| 12 | POST | `/api/v1/modules/{ns}/{name}/versions/{v}/yank` | bearer | Yank / un-yank a version |
| 13 | GET/PATCH | `/api/v1/auth/whoami` | bearer | Identity + owned namespaces; edit own profile |
| 14 | POST | `/api/v1/auth/register` | install-id | Self-register → account + API key |
| 15 | GET | `/api/v1/namespaces/{ns}` | — | Namespace availability |
| 16 | POST | `/api/v1/namespaces` | bearer | Claim an available namespace |
| 17 | POST | `/api/v1/modules/lookup` | — | Batch digest lookup |
| 18 | POST | `/api/v1/auth/tokens` | api key | Exchange an API key for a JWT (optional) |
| 19 | PATCH | `/api/v1/modules/{ns}/{name}/versions/{v}` | bearer | Amend the version changelog (metadata) |
| 20 | POST | `/api/v1/modules/{ns}/{name}/versions/{v}/logo` | bearer | Replace the version logo (metadata, out of digest) |
| 21 | GET | `/api/v1/pubkey` | — | Ed25519 public key for verifying signed manifests |
| 22 | PUT | `/api/v1/modules/{ns}/{name}/star` | bearer | Star a module (favourite) |
| 23 | DELETE | `/api/v1/modules/{ns}/{name}/star` | bearer | Remove the caller's star |
| 24 | GET | `/api/v1/namespaces/{ns}/members` | bearer | List namespace members + roles |
| 25 | POST | `/api/v1/namespaces/{ns}/members` | bearer (owner) | Add / promote a member |
| 26 | DELETE | `/api/v1/namespaces/{ns}/members/{account}` | bearer (owner) | Revoke a member's access |
| 27 | POST | `/api/v1/modules/{ns}/{name}/validate` | bearer | Validate a spec without publishing (0.11) |
| 28 | POST | `/api/v1/modules/{ns}/{name}/check` | bearer | Full publish dry run incl. network checks (0.11) |
| 29 | GET | `/api/v1/modules/lookup?digest=\|signature=` | — | Find published versions by compiled digest **or** content signature |
| 30 | POST | `/api/v1/modules/lookup` | — | Batch lookup; body `{digests: [], signatures: []}` |
| 31 | POST | `/api/v1/auth/tokens` | api key | Exchange a static key for a short-lived JWT |
| 32 | GET | `/api/v1/version` | — | The server's API + `just-dna-format` contract versions, and its `mode` |
| 33 | POST | `/api/v1/orgs` … | bearer | Org create / members / role / settings / namespaces |
| 34 | GET/PUT/DELETE | `/api/v1/modules/{ns}/{name}[/versions/{v}]/reviews` | bearer (writes) | Reviews and audits |
| 35 | DELETE | `/api/v1/modules/{ns}/{name}/versions/{v}` | bearer | Hard-delete a version — **test instance only**, `405` on prod (0.12) |
| 36 | DELETE | `/api/v1/modules/{ns}/{name}` | bearer | Hard-delete every version — **test instance only** (0.12) |
| 37 | POST | `/api/v1/modules/{ns}/{name}/versions/{v}/readme` | bearer | Replace the card's readme prose (metadata, out of digest) (0.14) |

---

### 27. `POST /api/v1/modules/{ns}/{name}/validate`

Validate a spec server-side without publishing. Writes nothing, touches no network, and **the module
need not exist** — `{name}` is the name you intend to publish under. Requires `PUBLISH` on `{ns}`:
nothing is stored, but the real compiler runs over your CSVs, which is the same server CPU a publish
spends.

Multipart `files=` exactly as for publish, minus `version` — **or** a single `archive=` part
(`.tar.gz` / `.zip`), the same form `/versions/import` takes. Send one or the other; both together
is `422 ambiguous_upload`. Query: `?strict=` (default **true** — a dry run whose default disagrees
with the publish it predicts is a trap).

The archive form is not a convenience. `max_upload_bytes` bounds what crosses the wire and mirrors
the deployment's HAProxy request-body cap, so it is not a number to raise — a spec whose authored
CSVs exceed it (the ClinVar panels: 34–180 MiB) is a `413` sent raw and fine sent packed, 2–10 MB.
Before 0.11.1 only the publish routes accepted an archive, so those modules could be published but
never rehearsed.

```json
{
  "valid": true, "strict": true,
  "errors": [], "warnings": [],
  "info": ["dropped registry-owned `module.namespace` (the registry stamps it on publish)"],
  "stats": {"variant_count": 42, "gene_count": 3, "genes": ["…"], "categories": ["…"]},
  "content_signature": "sha256:…",
  "name_matches_path": true,
  "published_as": [],
  "published_elsewhere": [],
  "would_publish_module_level": true
}
```

`info` is what the server rewrote and accepted. `published_as` lists **every** version already built
from identical data, including earlier versions of this same module; `published_elsewhere` (0.16) is
the subset under a *different* `(namespace, name)`, which is the one publish refuses with
`409 duplicate_content`. Rate bucket `validate` (60/h).

**The two lists exist because a review pass is not a duplicate.** A version that changes no data —
one `authorship` entry appended, nothing else — has the same `content_signature` as its predecessor,
and the publish gate allows that under the same module while refusing a re-list under another name.
Until 0.16 the pre-flight ran the lookup without that carve-out and answered `would_publish
{_module_level}: false` for a publish that then returned `201`, so an automated publisher branching
on the field declined its own legal publish (S10). The same-module hit is still *reported*, because
"this data is already published as 1.0.0" is how an author confirms they changed nothing.

**`would_publish_module_level` (0.13)** composes the three publish gates that do not scale with the
variant count — `valid` under `strict`, `name_matches_path`, and an empty `published_elsewhere` —
into the one field a CI job can branch on here. It is derived server-side, from the same expression
`/check` builds `would_publish` on, so the two cannot drift.

It is deliberately **not** `would_publish`, and the distinction is the point rather than pedantry:
this endpoint never runs the network tier, so `true` means *nothing module-level blocks a publish*,
never *a publish would succeed*. A reference-allele mismatch or a withdrawn rsID still refuses one,
and only `/check` can see those. Reading the weaker field as the stronger one is how a caller ships
an upload that was already doomed — an empty finding list and an unrun check render identically,
which is why the name says what it quantifies over. What it buys you is that it has **no ceiling and
costs no egress**, so it answers for a panel far too large to check online (S1).

### 28. `POST /api/v1/modules/{ns}/{name}/check`

The full dry run: everything `/validate` does, plus what only the network tier can see — an authored
reference allele against the actual genome, `clin_sig` against ClinVar, rsIDs dbSNP has merged away,
GA4GH allele-identity coverage.

Body: `files=` or `archive=`, exactly as `/validate` — see there for why the compressed form exists.

Query: `?strict=` `?offline=` `?frequencies=` `?literature=` `?identifiers=` `?acmg=` `?pgx=`
`?declared_use=`.

The five optional passes are opt-in because each has a cost the base run does not, and each degrades
rather than failing — a pass that could not run reports **why**, in its own `warnings`, and never
reports a clean result it did not earn:

| Pass | Offline | What a missing prerequisite looks like |
|---|---|---|
| `?frequencies=` | no-op | gnomAD is online-only and there is no snapshot to ship (the v4.1 sites VCFs are 58 GB / 742 GB); `skipped_offline: true` |
| `?literature=` | no-op | PubMed / Europe PMC / Crossref are live; a PGx-only module carries no `studies.csv`, which is a note, not a defect |
| `?identifiers=` | no-op | OLS4 and HGNC are live and neither publishes a snapshot, so offline the pass reports that nothing was **asked** — `clean: null`, not `clean: true` |
| `?acmg=` | **works with a snapshot** | needs `REGISTRY_ACMG_SNAPSHOT_DIR` (build it with `just-dna-enricher acmg build`); without one, `checked: 0` and a warning — *unchecked*, never *clean* |
| `?pgx=` | **works with snapshots** | each leg is snapshot → live → skipped-with-a-reason; `REGISTRY_CPIC_CACHE` / `REGISTRY_PHARMVAR_CACHE` / `REGISTRY_CLINPGX_CACHE`. ClinGen dosage alone is live-only |

`?identifiers=true` checks authored `trait_efo_id` CURIEs against OLS4 and `gene` symbols against
HGNC — the generalization of "is the source stale?" from datasets to identifiers, since an EFO
retirement or an HGNC rename leaves a module well-formed and quietly out of date. rsIDs are **not**
here: they are checked inside `enrich()` and land on `enrichment.stale_rsids`, because their verdict
belongs on `resolution.csv`'s own columns. A CURIE in an ontology this tier has no route for comes
back under `unchecked` rather than as a finding. **Nothing it reports moves `would_publish`** — a
publish does not run this pass, so a finding predicts nothing about one.

Since 0.13 the same pass answers a second question: **does a row's `gene` name the chromosome the row's
own variant sits on?** `gene_loci` carries one line per row where it does not. This is a different axis
from `stale_genes`, which asks only whether HGNC still approves the symbol — a row can pair an approved
symbol with a variant on another chromosome and satisfy every other check, since both halves are true
and only the relationship between them is false. That is the shape a machine-written citation fails in:
a real gene name beside an invented rs number, which resolves anyway because dbSNP is dense enough that
almost any number hits something. Chromosome granularity only, deliberately — a row may legitimately
name a distal regulatory target (`rs1421085` sits in an *FTO* intron and acts on *IRX3*/*IRX5*), and a
pseudoautosomal gene's X/Y disagreement is a spelling rather than a contradiction. `gene_loci_not_checked`
says why the comparison did not run, on the same contract as `clin_sig_not_checked`; an rsID-only row is
compared using the `resolution.csv` the run just produced, and nothing is fetched for it.

`?pgx=true` cross-checks authored PGx assertions against PharmVar, CPIC, ClinPGx and ClinGen dosage.
**Provision its snapshots if you host this endpoint.** Without them the only alternatives are fetching
a source that forbids sale live, per request, on the operator's own acceptance and personal PharmVar
key, or skipping the check — and every published rate figure for these is per IP, so a server
multiplies its callers onto one allowance rather than each getting their own. They are small (CPIC
~256 KB) and `registry warm-caches --pgx --apply --use non_commercial` pulls them.

Two consequences worth reading:

* **`routes`** says `snapshot` or `live` per source. Recorded rather than implied, because a pinned
  file and a live API can differ by a release.
* **PharmVar needs no key when a snapshot is present**, which is the configuration a public
  deployment wants: that key is personal and non-transferable under PharmVar's terms §2, so serving
  third parties on it is the thing to avoid. It is also the one cache the registry cannot pull for
  you — nothing is published, because the bulk data comes down under that same key. Build it once
  with `just-dna-enricher pharmvar build`.

Prefer the **ACMG snapshot** to the scrape even online: NCBI's page still serves SF v3.2 while ACMG
published v3.3 in June 2025, so a disagreement against the page is as likely to mean the list is old
as that the module is wrong. Those are reported apart, under `unverifiable` rather than `mismatches`,
and never count against `would_publish`.

**`declared_use` is a third axis, orthogonal to `strict` and `offline`** (format Principle 5):
`strict` says how hard to fail on a finding, this says who is using the data and why, and it is
checked at *acquisition*, because that is when a data-usage policy is accepted. Every PGx upstream is
CC BY-SA **plus a no-sale clause**, so:

| `declared_use` | effect on a source that forbids sale |
|---|---|
| `unstated` (default) | **skipped**, with a reason — the registry will not declare a purpose on your behalf |
| `non_commercial` | fetched, and the declaration recorded |
| `commercial` | **`422 license_refused`**, nothing fetched |

Defaults to the deployment's `REGISTRY_DECLARED_USE`. A value outside the three is
`422 invalid_declared_use` — checked here rather than passed through, because the hyphenated
`non-commercial` (the enricher CLI's user-facing spelling) is the likely typo and an unrecognized
declaration must never resolve to anything other than a refusal. **PharmVar has no on/off switch** — the
presence of `PHARMVAR_API_KEY` on the server *is* the switch, so a flag can never disagree with
reality; unset simply means CPIC carries the check alone. That key is personal to a PharmVar account
under their terms §2, so on a public deployment it means third parties query PharmVar on the
operator's account.

**The enricher always runs `best_effort`, whatever `?strict=` says.** Strict enrichment *raises*, and
an endpoint whose purpose is to report cannot run in a mode that refuses to finish. `strict` grades
the validation findings and decides whether unresolved positions count against `would_publish`.

```json
{
  "validation": { "…as above…" },
  "enrichment": {
    "mode": "best_effort", "offline": true,
    "unresolved": [], "unreachable_rsids": [],
    "ref_mismatches": [], "clin_sig_conflicts": [],
    "clin_sig_not_checked": null, "stale_rsids": [],
    "vrs": {"alleles": 57, "identified": 55, "complete": false,
            "unmintable_reasons": {"indel/MNV: needs the reference sequence": 2}},
    "sources": ["cache"]
  },
  "would_publish": true,
  "elapsed_seconds": 0.21
}
```

`vrs` is the enricher's own coverage, not a recount — the same numbers the compiler stamps into
`manifest.compilation.vrs_alleles` / `vrs_alleles_identified`, so a dry run cannot disagree with the
publish it predicts. `unmintable_reasons` is the half that tells a publisher whether to act: an indel
with no sequence proxy, or a build with no refget table, is the tier's own limit and no authored edit
clears it, so a shortfall never counts against `would_publish`.

**`unreachable_rsids` (0.13) is the field to read before believing `unresolved`.** `unresolved` names
keys with no position and says nothing about why, so it reads as "no such locus" even when the truth is
that nothing came back: through enricher 0.5.3 a failed Ensembl request and an Ensembl that answered
"no GRCh38 locus" were the same result. They now differ, and only one of them may resolve on a re-run.
Always empty on `?offline=true`, where nothing was asked. It does **not** soften `would_publish` — under
`?strict=true` an unresolved key still refuses, because the publish really would refuse — but a `false`
verdict beside a non-empty `unreachable_rsids` means *re-run*, not *go author coordinates*. The same
reason appears in prose on `notes`, and on the publish path in the `422`'s hint.

**`clin_sig_not_checked` is the field to read before believing `clin_sig_conflicts: []`.** An empty
conflict list means two opposite things — "compared everything, nothing disagreed" and "never
compared" — and only one of them is reassuring. `null` means the check genuinely ran. Otherwise it is
`not_requested` (the operator set `REGISTRY_ENRICH_VERIFY_CLINSIG=false`), `no_snapshot` (no ClinVar
snapshot on this deployment — `registry warm-caches --apply`), or prose saying the module declares it
was drafted from the very snapshot the check reads, which makes the comparison a value against itself
and its zero structurally guaranteed. The same reason appears in prose on `notes`. None of them
counts against `would_publish`: a check the *operator* disabled is not a defect in the module.

`would_publish` is the field a CI job should branch on — it is derived server-side so the
strict-publish contract lives in one place.

**Expensive, and the cost lands on the whole deployment.** gnomAD is unauthenticated and throttles
by IP against a published 10-per-60s budget — there is no API key to raise it — so an overspend limits
*the server*, not the caller who caused it. Pacing is ~6s per 20 variants, so
`?frequencies=true` can take minutes. Rate bucket `enrich` (5/h) *plus* a process-wide concurrency
gate (`enrich_max_concurrency`, default 1) — the bucket bounds one caller, the gate bounds the
server. An invalid spec short-circuits before any of it is spent (`skipped_reason: "invalid_spec"`),
and a module over `enrich_max_variants` is refused with `422 too_many_variants`.

**That ceiling bounds pacing, so since 0.13 it applies to online runs only.** `?offline=true` issues
no outbound request for it to bound, and measured with the suite's socket tripwire armed an offline
run costs ~5s at 40,000 subjects, linear — under 2% of `enrich_timeout_seconds`, which together with
the concurrency gate is what actually bounds offline CPU. So a panel too large to check online is
still checkable against whatever snapshots the deployment holds. And an online refusal is no longer
empty-handed: the `422` body carries `subject_count`, `limit`, the full `validation` report and
`would_publish_module_level`, all of which the server had computed before refusing. The `error` code
is unchanged, so a client branching on it is unaffected.

The cap counts
**enrichment subjects**, not `variants.csv` rows: the enricher also asks about `pharm_variants.csv`,
`haplotypes.csv` and `heteroplasmy.csv`, so a PGx module with no `variants.csv` is not a module with
nothing to enrich. It is an upper bound — subjects are de-duplicated by `variant_key` downstream, so a
locus named in three tables counts three times here and is asked once.

### 29–30. `GET`/`POST /api/v1/modules/lookup`

Two identities, one endpoint, because they answer different questions:

* **`digest`** names the *compiled bytes*. It moves when the same spec is recompiled against a
  different reference, and it embeds the module name — so it moves on a rename too. It can also move
  on a plain recompile of an unchanged spec: a module that authors no `sources.csv` gets a fresh one
  from the enricher each time, carrying a `fetched_at` stamped to the second. Use it to ask *which
  published version has exactly these bytes*, never *is this data already here*.
* **`signature`** names the *authored rows*. Name-, reference- and metadata-independent, and what
  publish gates `409 duplicate_content` on — so it is the only one that can predict a rejection. A
  client computes it locally with `just_dna_compiler.compiler.content_signature(spec_dir)`, no upload
  and no recompile.

`GET` takes exactly one of the two (`422 lookup_needs_one_key` otherwise) and returns
`{digest, signature, matches: [{namespace, name, version, yanked}]}`. `POST` takes
`{digests: [], signatures: []}` — mixed is fine and usually what you want — and returns `{results: [...]}`,
each list capped at `lookup_batch_max`. Anonymous: a content signature is not a secret, and someone
about to publish a duplicate should not need an account to find that out.

---

### 1. `GET /health`
No prefix, no auth. Liveness, and since 0.13 enough to run a deployment from without opening a shell.

```json
{
  "status": "ok",
  "version": "0.13.0",
  "mode": "prod",
  "storage": "local",
  "uptime_seconds": 84213.5,
  "enrichment": {"active": 0, "queued": 0, "limit": 1},
  "catalog": {"modules": 12, "versions": 31, "yanked": 2, "namespaces": 4}
}
```

- **`mode`** is `prod` or `test`. It is the field that says *which deployment answered*, and it
  exists because with both instances live the two were otherwise byte-identical here. `GET
  /api/v1/version` reports it too; `RegistryClient(expect_mode=…)` asserts it.
- **`enrichment`** is the process-wide gate: permits in use, publishes queued behind them, and the
  ceiling (`enrich_max_concurrency`). `active == limit` is what a caller meets as
  `503 enrichment_busy`.
- **`catalog`** counts only what a reader could already enumerate through the listing routes —
  account and key counts are deliberately **not** here, since this endpoint is unauthenticated.
  `versions` includes yanked ones, with `yanked` beside it rather than subtracted out.
- **`status` is `degraded`, not a 5xx, when the catalog cannot be counted.** `catalog` is then
  `null` and `degraded_reason` names the failure. A liveness probe that fails on a sick database
  tells a balancer to pull a process that is still serving, and withholds the diagnosis exactly
  when it is wanted. Probe on the **HTTP status**; read `status` to decide whether to page someone.

### 2. `GET /api/v1/modules`
List/search the catalog (one **card** per module, its latest non-yanked version).

Query params: `q` (title/description substring), `category`, `gene`, `genome_build`, `owner`,
`license` (exact facet matches), `namespace` (restrict to one namespace), `featured` (`true` →
only featured), `include_blacklisted` (`true` → include hidden namespaces), `group` (a tab preset —
see below), `sort` = `name` (default) | `downloads` | `recent` | `stars` | `popular`, plus `page`,
`per_page`. Facet filters match modules with a non-yanked version carrying that gene/category.

**`group`** is a server-defined tab preset over the raw filters (a group wins over the equivalent
`sort`/`featured`): `all` (everything), `featured` (`featured=true`), `curated` (has an
owner-highlighted review — see reviews), `popular` (`sort=popular`), `new` (`sort=recent`), `test`. **Test/sandbox namespaces** — those matching the server-config
`REGISTRY_TEST_NAMESPACE_PATTERN` (default `^(sandbox|test)([-_]|$)`) — are surfaced **only** under
`group=test` and hidden from every other tab and the default listing; they stay reachable by an
explicit `namespace=`. Membership is server-owned so all clients agree. Discover the tabs at
`GET /api/v1/modules/groups`.

`200 → Page<ModuleCard>`. **Featured** modules float to the top of every sort (card has
`featured: bool`). **Blacklisted** namespaces are omitted by default — returned only with
`include_blacklisted=true` or an explicit `namespace=` (moderation, not deletion). Card
`stats.genes` is **truncated** (top 3); the full list is in the detail and manifest. Rate-limited
(`search` bucket). Each listed module also takes one `search_hit` (feeds `sort=popular`). When
called **with** a bearer token, `starred_by_me` reflects the caller; anonymous reads leave it
`false`.

```json
{
  "items": [{
    "namespace": "just-dna-seq", "name": "coronary", "title": "Coronary",
    "description": "…", "icon": "heart", "color": "#db2828",
    "latest_version": "2.0.0", "genome_build": "GRCh38", "license": null, "owner": "just-dna-seq",
    "stats": {"variant_count": 16, "study_count": 5, "gene_count": 8,
              "genes": ["APOE","LPA","PCSK9"], "categories": ["cardio"]},
    "downloads": 214, "stars": 12, "views": 340, "starred_by_me": false,
    "created_at": "2026-05-01T09:00:00Z", "updated_at": "2026-07-06T20:38:01Z"
  }],
  "total": 1, "page": 1, "per_page": 20
}
```

Sort keys: `downloads` (module download total), `recent` (`updated_at`), `stars` (stargazer count),
`popular` (blended `views + search_hits`).

### 2a. `GET /api/v1/modules/groups`
The listing tabs (groups) the catalog defines, for a UI to render. Anonymous. `200 →`

```json
[
  {"key": "all", "label": "All", "description": "Everything published (test/sandbox spaces excluded)."},
  {"key": "featured", "label": "Featured", "description": "Namespaces curated by the operators."},
  {"key": "curated", "label": "Curated", "description": "Has an owner-highlighted review/audit."},
  {"key": "popular", "label": "Popular", "description": "Most viewed, downloaded, and starred."},
  {"key": "new", "label": "New", "description": "Most recently updated."},
  {"key": "test", "label": "Test", "description": "Sandbox / test namespaces (hidden from other tabs)."}
]
```

Pass a `key` as `?group=` on the listing (endpoint 2). Membership is server-owned policy, not the
UI's — see the `group` param above.

### 3. `GET /api/v1/modules/lookup?digest=sha256:…`
Find published versions whose `artifact.digest` matches — the *compiled bytes*, not the data. For
"is this module already published?" use `?signature=` (endpoints 29–30): a recompile of the same spec
need not produce the same digest. `digest` is required. `200 →`

```json
{ "digest": "sha256:…", "matches": [ {"namespace":"just-dna-seq","name":"coronary","version":"1.0.0","yanked":false} ] }
```

`matches` is `[]` if none (not a 404).

### 4. `GET /api/v1/modules/{ns}/{name}`
`200 → ModuleDetail` = the card **plus** `readme` (the spec's `README.md`, see 37), the **full** `stats.genes`, the
embedded `versions` array (`VersionSummary[]`, includes yanked), and `latest_manifest` (the full
`ModuleManifest` inline). `404 module_not_found`. Each successful detail view increments the
module's `views` counter (feeds `sort=popular`); with a bearer token the card's `starred_by_me`
reflects the caller.

### 5. `GET /api/v1/modules/{ns}/{name}/versions`
`200 → Page<VersionSummary>` (paginated). `404 module_not_found`.

```json
{"version":"2.0.0","artifact_digest":"sha256:…","compile_success":true,"yanked":false,
 "downloads":214,"created_at":"…","changelog":"…","manifest_url":"/api/v1/modules/…/versions/2.0.0/manifest"}
```

### 6. `GET /api/v1/modules/{ns}/{name}/versions/{v}/manifest`
`200 →` the full [`ModuleManifest`](#modulemanifest). `404 version_not_found`.

### 7. `GET /api/v1/modules/{ns}/{name}/versions/{v}/logs`
`200 → {"items": [{"name":"v2.log","sha256":"sha256:…","size":1059987,"url":"…/files/v2.log"}]}`.
Empty `items` if the version has no logs. `404 version_not_found`.

### 8. `GET /api/v1/modules/{ns}/{name}/versions/{v}/files/{path}`
Fetch a single file recorded in the manifest — an artifact parquet, a provenance log (nested paths
allowed, e.g. `logs/reviewer.log`), or a spec input (`variants.csv`). `{path}` is a catch-all.
- `200` `application/octet-stream` (local storage streams the bytes), **or** `302` redirect to a
  CDN/presigned URL (external storage backends).
- `404 version_not_found` / `404 file_not_found` (path not in the manifest listing).
- Fetching an **artifact file** (a `manifest.artifact.files` entry, e.g. `weights.parquet`)
  increments the module + version `downloads` counters — so presigned/CDN redirects of the real
  bytes are counted. Fetching a log/provenance/logo file does **not** count.

### 9. `GET /api/v1/modules/{ns}/{name}/versions/{v}/download`
Increments the module's `downloads` counter **and** the version's `downloads` counter. `?format=`:
- `files` (default) → `200 {"digest":"sha256:…","files":[{"name","url","sha256","size"}]}` — the
  artifact files for verify-then-install; `url` points at endpoint 8 (or an external URL).
- `tarball` → `200` `application/gzip` (`Content-Disposition: attachment; filename="{name}-{v}.tar.gz"`),
  a streamable tar.gz of the whole version (`manifest.json` + artifact + logs + inputs).

`404 version_not_found`.

### 10. `POST /api/v1/modules/{ns}/{name}/versions`  *(bearer)*
Publish a new version. `multipart/form-data`:
- `version` (form, required) — SemVer.
- `changelog` (form, optional).
- `files` (one or more file parts) — the **spec**: `module_spec.yaml` + `variants.csv` +
  `studies.csv` required; `README.md`, `logo.*`, and logs (`*.log`, `logs/*.log`) optional. Nested
  names are honored (`logs/reviewer.log`).

Flow: ownership → version format → immutability → `validate_spec` → `enrich` → `compile_module`
(`compiled_by="marketplace-server"`) → fill registry fields → store (version-scoped) → index.
The spec's `module.name` must equal the path `{name}` (`422 name_mismatch`).

`201 →` the full `ModuleManifest`. Errors: `401`, `403 not_namespace_member`,
`422 invalid_version`, `409 version_exists`,
`422 {error: missing_spec_files|invalid_spec|compile_failed|name_mismatch|ambiguous_spec_layout}`.

#### Spec layout (0.14) — what may arrive, and from where

The compiler reads one flat directory, so that is the canonical layout and the server normalises an
upload onto it before reading anything. Applied identically by `/versions`, `/versions/import`,
`/validate` and `/check`, and reported on the dry runs' `info[]`:

- **A recognised spec file in a subdirectory is lifted to the root.** `derived/resolution.csv`
  publishes exactly as `resolution.csv` does. `derived/` is the folder this registry emits (see
  `--layout split` in [CLIENT.md](CLIENT.md)), but any folder name is accepted on the way in, because
  producers already ship `metadata/` and `enriched/` trees and refusing them buys nothing.
- **`MODULE.md` is renamed to `README.md`**, unless a `README.md` is also present — then the real
  name wins, the legacy file is carried unchanged, and a warning says so.
- **`licensing.csv` is renamed to `sources.csv`** (0.16.2), on the same rule and with the same
  both-present behaviour. They are one table under two spellings: format 0.6 made `licensing.csv` the
  name and deprecated `sources.csv`, this deployment compiles on 0.5, and every current authoring tool
  and reference example writes the new one. Until this landed the file reached storage but never the
  compile, so the `sources` summary was built from the enricher's own Ensembl row alone and a module
  whose upstreams forbid sale advertised `licensing.commercial_use: true` on its card. Nothing is
  guessed at here: upstream defines the two names as one table with one row model, the 0.6 header is
  field-for-field the 0.5 one, and `sources.csv` is a fact sidecar outside `content_signature`, so the
  rename moves no identity.

Two exceptions and one refusal:

- **`logs/` is never flattened**, and neither is a top-level `*.log`. The manifest records those
  paths verbatim, so hoisting one would rename a file the manifest attests.
- **Unrecognised files stay exactly where they are**, at whatever depth. The compiler tolerates
  unknown files by contract; a rule invented here would break it.
- **One root name claimed by two paths is `422 ambiguous_spec_layout`**, listing both. Only the
  author knows which copy is current, and picking one silently would publish the wrong table under a
  signature that looks perfectly valid.

**`verification.json` is recognised as of 0.16** (S11), so a `revalidate` or an `upgrade` rebuilds a
spec directory with the enricher's attestation still in it instead of dropping it — the same failure
`README.md` had before 0.14. Recognised is not read: nothing in this service parses the file, and
nothing will until the manifest can attest it. It is the *author's* record of what their enricher
checked against live sources, which a server that compiles offline cannot reproduce and must not
present as its own. `manifest.verification` and its signed `closure` block are format 0.6 work;
surfacing either is tracked in [ROADMAP.md](ROADMAP.md).

**The folder cannot move a module's identity.** `content_signature` is computed over
`module_spec.yaml`, `variants.csv`, `studies.csv` and the table-kind CSVs — all authored, all at the
root — so nothing that may live in `derived/` is in it, and a spec published flat and the same spec
published split are one module, with one `409 duplicate_content` claim between them.

**Publish is the low-priority lane, and it has no deadline.** On a deployment that enriches online
(`REGISTRY_ENRICH_OFFLINE=false`) it egresses through the same paced clients as `/check`, on the same
IP-scoped budget, so it takes a permit from the same process-wide gate — but it **queues** for one
rather than failing. There is no `503 enrichment_busy` here and no `enrich_timeout_seconds`: a dry run
has someone waiting on the answer, so a full gate is a fast rejection, while a publish has nobody
waiting and an upload already spent, and rejecting it would mean re-uploading a module over a
condition that clears in seconds.

Three things it concedes to interactive callers while it waits and runs:

* it **defers at entry** — a queued publish will not start within `enrich_idle_quiet_seconds` of any
  `/check` asking for the gate, granted or refused;
* it **holds no threadpool worker** while queued, so a backlog of publishes cannot starve the pool
  `/check` needs in order to run at all;
* it **runs niced**, on a thread of its own, so the compile yields CPU.

What it cannot do is give the permit back mid-run: once a publish is enriching, a `/check` arriving
in that window still gets `503 enrichment_busy`. Nothing can preempt it — `enrich()` is one opaque
call and Python cannot interrupt a thread.

**Set your client and proxy timeouts accordingly.** An online publish can legitimately stay open for
minutes, plus however long it queues. On the default offline deployment none of this applies: the
publish reaches nothing, takes no permit, and runs straight through.

### 11. `POST /api/v1/modules/{ns}/{name}/versions/import`  *(bearer)*
Publish from a **zip or tar.gz** archive (in-house packaging / legacy import). `multipart/form-data`:
- `version` (form, required), `changelog` (form, optional).
- `archive` (file, required) — a `.zip` / `.tar.gz`.
- Display metadata (form, optional): `title`, `description`, `report_title`, `icon`, `color` —
  used only for **legacy parquet-only** archives (reverse-engineered before recompiling).
- `genome_build` (form, optional) — **not display metadata**, and the one importable value that is
  inside `artifact.digest`. See below.

A spec archive (contains `module_spec.yaml`) is recompiled directly; a legacy archive (only
`weights.parquet`, no spec) is reverse-engineered via `reverse_module` then recompiled. Extraction
is path-traversal-safe. Same guards/response as endpoint 10, plus `422 {error: unsafe_archive|bad_archive|no_module_content}`.
The *Spec layout* rules under endpoint 10 apply here too, and this is where they matter most: a zip is
how a subfoldered spec and a legacy `MODULE.md` usually arrive. A single wrapping directory is
unwrapped as before; `derived/` (or any other subfolder) is flattened onto the root.

**Declare `genome_build` for a non-GRCh38 legacy archive.** The build reaches a compiled module
through `manifest.json` and no parquet column, so `reverse_module` recovers it from the archive's own
manifest — and a bare parquet archive has none, in which case the format's `GRCh38` default applies.
That is right for the common case and silently wrong otherwise, because the build decides the
*identity key*: on GRCh38 a resolved substitution is keyed by a `ga4gh:VA.…` minted against that
assembly's refget accession, so importing GRCh37 coordinates as GRCh38 mints an allele id naming a
different base, and the digest moves. Nothing downstream catches it — the recompile is internally
consistent and `verify_manifest` re-derives the same wrong digest. An explicit value always wins; a
spec archive, or a bare one that really is GRCh38, needs nothing.

### 12. `POST /api/v1/modules/{ns}/{name}/versions/{v}/yank`  *(bearer)*
Body (optional JSON): `{"yanked": true}` (default `true`; send `false` to un-yank). Owner-only.
Yank drops the version from default listings and `latest` but keeps its manifest/artifact
fetchable; `latest_version` recomputes over the remaining non-yanked versions.

`200 → {"namespace","name","version","yanked"}`. Errors: `401`, `403`, `404 version_not_found`.

### 19. `PATCH /api/v1/modules/{ns}/{name}/versions/{v}`  *(bearer)*
Amend a published version's **changelog** — descriptive metadata only; the artifact and its
`digest` are immutable and untouched (this is *not* a re-publish). Owner-only. Body
`{"changelog": "…", "append": false}` (`append=true` adds to the existing changelog).
`200 → {"namespace","name","version","changelog"}`. Errors: `401`, `403 not_namespace_member`,
`404 version_not_found`.

### 20. `POST /api/v1/modules/{ns}/{name}/versions/{v}/logo`  *(bearer)*
Replace a version's **logo** — multipart `logo` file (`png`/`jpg`/`jpeg`). Descriptive metadata only:
the logo is out of `artifact.digest`, so the digest (and any signature over it) stays immutable and
there is **no version bump**. Owner-only. `200 → {"namespace","name","version","logo":
{"name","sha256","size"}}`. Errors: `401`, `403 not_namespace_member`, `404 version_not_found`,
`422 invalid_logo` (bad extension). Cards expose the served logo as `logo_url`; consumers fall back
to `icon`/`icon_set` when a module ships none.

### 37. `POST /api/v1/modules/{ns}/{name}/versions/{v}/readme`  *(bearer)*
Replace a module's **readme** — the prose on its card — as a multipart `readme` file (markdown).
Out-of-digest metadata like the logo and the changelog, so the artifact, its digest and any signature
over it stay immutable and there is **no version bump**. Amend rights (own version for a member, any
for admin+). `200 → {"namespace","name","version","readme"}`. Errors: `401`,
`403 not_namespace_member`, `404 version_not_found`.

**Where a readme comes from in the first place:** publish reads `README.md` out of the uploaded spec
and projects it onto the module. That is the *only* recognised filename — earlier revisions of this
document and a comment in `services/upgrade.py` both named `MODULE.md`, but nothing ever read either,
so 0.14 settled on the ecosystem default. **An uploaded `MODULE.md` is renamed to `README.md`** (see
*Spec layout* under endpoint 10), so the corpus written against the old advice publishes with its
prose intact; a module published *before* 0.14 still ships its `MODULE.md` as opaque bytes, and this
endpoint is the fix that costs no version number.

The readme is **module-level**, matching the card it feeds: a republish carries the newest spec's
readme forward exactly as `title` does, and a spec with no `README.md` leaves existing prose alone
rather than blanking it. It is out of `artifact.digest` **and** out of the content signature, so
editing a caveat never mints a new content identity or trips `409 duplicate_content`.

### 21. `GET /api/v1/pubkey`
The server's Ed25519 **public key** for verifying signed manifests (SPEC §5). `200 → {"algorithm":
"ed25519", "public_key": "<base64>"}` when the server is configured to sign (`REGISTRY_SIGNING_KEY`
set); `404 signing_not_configured` otherwise. Pin this key and pass it to the client's verify step to
defend against a compromised storage backend. Signed versions are flagged `signed: true` in the
versions list; the `revalidate` audit flags contract-drifted versions `needs_upgrade: true`.

### 22–23. `PUT` / `DELETE /api/v1/modules/{ns}/{name}/star`  *(bearer)*
Star (favourite) a module GitHub-style, or remove the caller's star. Both are **idempotent** (a
double `PUT` keeps exactly one star; a `DELETE` on an unstarred module is a no-op). `200 →
{"namespace","name","stars","starred_by_me"}` where `stars` is the total stargazer count.
Errors: `401`, `404 module_not_found`. Rate-limited (`social` bucket). Sort the catalog by count
with `GET /api/v1/modules?sort=stars`.

### 27. `GET /api/v1/modules/{ns}/{name}/reviews` · `.../versions/{v}/reviews`
List reviews/audits — for the whole module, or one version. Anonymous. Highlighted reviews first.
`200 → [{"reviewer","version","rating","verdict","notes","highlighted","created_at","updated_at"}]`.

### 28. `PUT` / `DELETE /api/v1/modules/{ns}/{name}/versions/{v}/reviews`  *(bearer)*
Post/update (`PUT`) or remove (`DELETE`) **the caller's** review of a version. **Anyone
authenticated** — reviews are open, like a store. Body `{"rating": 1-5, "verdict":
"verified|concerns|rejected"?, "notes"?}`; one per account per version (re-posting replaces it, and
leaves the owner's highlight intact). Returns the version's current review list. Errors: `401`,
`404 version_not_found`, `422` (rating out of range / bad verdict). Rate-limited (`social`).

### 29. `PUT` / `DELETE .../versions/{v}/reviews/{reviewer}/highlight`  *(bearer — owner)*
The namespace **owner** highlights (or un-highlights) a reviewer's review — SO accepted-answer style;
any number may be highlighted. A highlighted review is what `?group=curated` and the card's
`curated` flag key on. Returns the updated review list. Errors: `401`, `403 not_namespace_owner`,
`404 review_not_found` (highlight) / `version_not_found`.

#### A review: a `reviews` row, or an `authorship` entry? (S12)

Both record that someone read a module and formed a view, and they are **not substitutes** — the
question is where the record has to survive.

- **`reviews` row (28) — the default, and what a catalog is for.** It costs no version number, it is
  projected onto the card (`review_count`, `avg_rating`, `curated`), it drives `?group=curated`, and
  it is moderatable. A reviewer who is not the author can post one. Reach for this unless one of the
  properties below is required.
- **An `authorship` entry in `module_spec.yaml` — when the record must travel with the module.** It
  is inside the spec, so it survives a download, a hand-off on disk and a re-publish, it is visible
  to someone who never calls this API, and it is covered by the module's signature. That last one is
  the asymmetry that decides it: a `reviews` row cannot be signed by the reviewer's key. It costs a
  version, since the manifest is written at publish.

Publishing a version that changes no data in order to record a review is legal — the duplicate gate
carves out the same `(namespace, name)` deliberately — and since 0.16 the pre-flight agrees with it
rather than predicting a refusal (S10).

The registry does **not** project `authorship` onto a card, and this is a policy rather than an
omission: this server compiles what it publishes, which is what makes a card's claims ours to stand
behind, while `authorship` is the author's own statement about who reviewed their work. Rendering it
beside a moderated review count would present the two as the same kind of fact. Read it from
`…/manifest` or `ModuleDetail.latest_manifest`, where it is plainly the manifest's word.

### 24. `GET /api/v1/namespaces/{ns}/members`  *(bearer)*
List a namespace's members. Any member may read. `200 → {"namespace": "…", "members": [{"account":
"alice", "role": "owner"}, {"account": "bob", "role": "member"}]}`. Errors: `401`,
`403 insufficient_capability`.

### 25. `POST /api/v1/namespaces/{ns}/members`  *(bearer — admin+)*
Add or re-role an account. Body `{"account": "bob", "role": "member"}` (`role` = `owner` | `admin` |
`member`, default `member`; re-posting updates the role). Adding a `member` needs **admin+**
(manage-members); granting `admin`/`owner` needs **owner** (manage-roles). `201 →
{"namespace","members":[…]}`. Errors: `401`, `403 insufficient_capability`, `404 account_not_found`,
`422 invalid_role`.

### 26. `DELETE /api/v1/namespaces/{ns}/members/{account}`  *(bearer — admin+)*
Revoke an account's namespace membership. **Admin+**; removing an **owner** needs **owner**. This is
**namespace-scoped**, not a global API-key revocation: the account keeps its key and any other
namespaces. `200 → {"namespace","members":[…]}`. Errors: `401`, `403 insufficient_capability`,
`404 account_not_found` / `404 not_a_member`, `409 last_owner` (cannot remove a namespace's only
owner). Global key/account revocation stays an ops-CLI action (`registry revoke-key` /
`revoke-account`).

### 30–35. Orgs  *(bearer)*
An **org** is a `type='org'` account that owns namespaces and has members whose role cascades to
every namespace the org owns. Roles are `owner|admin|member` (same capabilities as namespace roles).
- `POST /api/v1/orgs` — `{"name": "acme"}` creates the org and seeds the caller as `owner`.
  `201 → {"org","owner"}`. Errors `422 invalid_org_name`, `409 name_taken`.
- `GET /api/v1/orgs/{org}/members` — any org member. `200 → {"org","members":[{account,role}]}`.
- `POST /api/v1/orgs/{org}/members` — add/re-role (admin+; granting admin/owner needs owner).
  `{"account","role"}`. `201 → OrgMemberList`.
- `PUT /api/v1/orgs/{org}/members/{member}/role` — `{"role"}` (owner-only; won't demote the last
  owner → `409 last_owner`).
- `DELETE /api/v1/orgs/{org}/members/{member}` — admin+ (removing an owner needs owner; last-owner
  guarded).
- `PATCH /api/v1/orgs/{org}/settings` — owner-only; body `{"funding_url"?, "display_name"?,
  "avatar_url"?, "email"?}` (edits the org account's profile).
- `POST /api/v1/orgs/{org}/namespaces` — `{"namespace"}` claims a namespace **owned by the org**
  (admin+; access flows via the cascade, no personal member row). `201 → {"namespace","org"}`.
All org gate failures return `403 insufficient_capability`; unknown org → `404 org_not_found`.

### 13. `GET` / `PATCH /api/v1/auth/whoami`  *(bearer)*
`GET 200 → {"account": "antonkulaga", "namespaces": [...], "type": "user", "display_name": null,
"avatar_url": null, "funding_url": null, "email": null}` — `namespaces` is every namespace the caller
is a member of; `type` is the `user`|`org` discriminator; `avatar_url`/`funding_url` are public
(userpic + donation link); `email` is **private** (only ever returned here). `401` on invalid token.

`PATCH` edits the caller's own profile — body `{"email"?, "display_name"?, "avatar_url"?,
"funding_url"?}` (omitted fields unchanged, `""` clears a field). Returns the updated identity.
`type` is **not** self-editable. Errors: `401`, `422` (bad email / non-http(s) url), `409
email_taken`.

### 18. `POST /api/v1/auth/tokens`
Optional JWT session. Body `{"api_key": "mk_live_…"}`. `200 → {"token": "<jwt>", "token_type":
"Bearer", "expires_in": 86400}`. Errors: `501 jwt_disabled` (no `jwt_secret` configured),
`401 invalid_token` (unknown API key). The returned JWT is accepted anywhere a bearer is.

### 14. `POST /api/v1/auth/register`
Self-service onboarding (community-first). Body `{"install_id": "jdi1_…", "account": "alice"}`.
The `install_id` is a proof-of-work token minted by the just-dna-lite app at first run (SHA-256 has
≥ `install_id_difficulty` leading zero bits). One account per install-id — re-registering an
install-id just issues a fresh key for its existing account.

`201 → {"token": "mk_live_…", "account": "alice", "namespaces": []}`. Errors:
`403 self_register_disabled` (when `allow_self_register=false`), `422 invalid_install_id` (bad PoW),
`422 invalid_account` (handle isn't a valid slug), `409 account_taken`.

### 15. `GET /api/v1/namespaces/{ns}`
`200 → {"namespace", "valid", "available", "requires_allow_test_data", "warnings"}`. Public. `valid`
reflects the slug rule (`^[a-z0-9][a-z0-9-]*$`); `available` is false once claimed.

**`requires_allow_test_data` + `warnings` (0.14)** carry the rule the *claim* will apply, because
this pre-flight used to contradict it: a `test-`prefixed name on production reported
`valid: true, available: true` and then met `422 test_data_on_prod` — a read-only check for an
irreversible act reporting the opposite of what the act would do (S6). It is a warning rather than
`valid: false` because since 0.14 the name genuinely *is* claimable there, with `allow_test_data`.

### 16. `POST /api/v1/namespaces`  *(bearer)*
Claim an available namespace for the caller's account. Body
`{"namespace": "alice-mods", "allow_test_data": false}`.
`201 → {"namespace": "alice-mods", "owner": "alice", "already_owned": false, "warnings": []}`
(idempotent if you already own it → `already_owned: true`). Errors: `401`, `422 invalid_namespace`,
`409 namespace_taken` (owned by someone else), `403 namespace_limit_reached` (account at
`namespaces_per_account`, default 5).

### 17. `POST /api/v1/modules/lookup`
Batch of endpoint 3. Body `{"digests": ["sha256:…", …]}` (capped at `lookup_batch_max`, default
256). `200 → {"results": [{"digest": "sha256:…", "matches": [{namespace,name,version,yanked}]}]}`.
Lets a consumer classify many local modules (provenance / "already published?") in one request —
digests are already in each module's `manifest.json`, so no client-side hashing.

---

## Schemas

### ModuleCard
`namespace, name, title, description, icon, icon_set, color, logo_url, latest_version, genome_build,
license, owner, stats: CardStats, downloads, stars, views, created_at, updated_at, starred_by_me,
featured, review_count, avg_rating, curated, author_funding_url, org_funding_url`. `stars`/`views`
are counters; `starred_by_me` is true only when the request carried a bearer for an account that
starred the module; `created_at` is the first-publish time, `updated_at` advances on every republish.
`review_count`/`avg_rating` (null when unreviewed) aggregate reviews across versions; `curated` is
true when someone with curate rights highlighted a review. `author_funding_url` is the latest
version's author's donation link; `org_funding_url` is the owning org's (both null when unset).

### Review
`reviewer, version, rating (1-5), verdict (verified|concerns|rejected | null), notes, highlighted,
created_at, updated_at`. Version-scoped; `highlighted` is set by the namespace owner.

### CardStats
`variant_count, study_count, gene_count, genes: string[], categories: string[]`. In cards `genes`
is truncated to 3; in detail/manifest it's the full list.

### VersionSummary
`version, artifact_digest, compile_success, yanked, signed, needs_upgrade, downloads, created_at,
changelog, manifest_url`. `downloads` is the per-version download count.

### ModuleDetail
`ModuleCard` fields + `readme: string`, `versions: VersionSummary[]`, `latest_manifest: ModuleManifest`.

### WhoAmI
`account: string` (handle), `namespaces: string[]` (every namespace the account is a member of),
`type: "user"|"org"`, `display_name: string|null`, `avatar_url: string|null` (public userpic),
`funding_url: string|null` (public donation link), `email: string|null` (private — only returned to
the account itself).

### MemberList / OrgMemberList
`{namespace|org: string, members: [{account: string, role: "owner"|"admin"|"member"}]}`. Roles are
hierarchical (owner ⊃ admin ⊃ member).

### Roles & capabilities
Effective role on a namespace = the highest of the caller's explicit `namespace_members` grant and —
when the namespace is org-owned — their `org_members` role (cascade). Capabilities: **member** =
publish + amend/yank *own* versions; **admin** = + amend/yank *any* + manage namespaces/members +
curate reviews; **owner** = + assign roles + edit settings (incl. funding). `*_own` vs `*_any` is
resolved by `versions.published_by`; a 403 carries `detail: "insufficient_capability"`.

### StarStatus
`namespace: string, name: string, stars: int, starred_by_me: bool`.

### ModuleManifest  {#modulemanifest}
The source-of-truth contract (from `just-dna-format`; the DB is a projection of it):

```json
{
  "manifest_version": "1.0", "schema_version": "1.0",
  "identity": {"namespace": "just-dna-seq", "name": "coronary", "version": "1.0.0",
               "canonical_id": "just-dna-seq/coronary@1.0.0"},
  "display": {"title": "Coronary", "description": "…", "report_title": "…",
              "icon": "heart", "color": "#db2828"},
  "genome_build": "GRCh38", "curator": "…", "method": "…", "license": null,
  "owner": "just-dna-seq", "authors": [], "created_at": "…", "published_at": "…",
  "stats": {"variant_count": 16, "weights_rows": 48, "study_count": 5, "gene_count": 8,
            "genes": ["…"], "categories": ["…"]},
  "compilation": {"compile_success": true, "compiled_by": "marketplace-server",
                  "compiler_version": "just-dna-compiler 0.1.0",
                  "ensembl_reference": "just-dna-seq/ensembl_variations",
                  "compiled_at": "…", "warnings": []},
  "inputs":  [{"name": "variants.csv", "sha256": "sha256:…", "size": 4350}],
  "artifact": {"digest": "sha256:…",
               "files": [{"name": "weights.parquet", "sha256": "sha256:…", "size": 40190}]},
  "logs":    [{"name": "v2.log", "sha256": "sha256:…", "size": 1059987}]
}
```

`artifact.digest` is a Merkle root over `artifact.files` (the version's immutable **byte** identity —
the *content* identity is `content_signature`, see endpoints 29–30);
`inputs` and `logs` are hashed the same way but **not** part of that digest. All hashes are SHA-256,
lowercase hex, `sha256:`-prefixed. A downloader verifies with `just_dna_format.verify_manifest`
(see [CLIENT.md](CLIENT.md) / SPEC §5).

---

## Deployment modes, and the two routes only a test instance serves (0.12)

`REGISTRY_MODE` selects `prod` (default) or `test`. Production is
`module-registry.just-dna.life`; the **polygon** is `module-polygon.just-dna.life` (default port
8100 against production's 8000). An unrecognised mode refuses to boot.

Three behaviours differ, and nothing else does:

| | production | polygon (`test`) |
|---|---|---|
| `test-`prefixed namespace / `test_`prefixed module | `422 test_data_on_prod` on publish **and** on `POST /namespaces` — **unless `allow_test_data=true`**, which accepts it with a warning (0.14) | accepted, no flag needed |
| `409 duplicate_content` | considers every version, any account | scoped to the **publishing account** |
| `DELETE` on a module / version | `405` (not mounted) | served |

**Why the delete verb exists.** A published `(namespace, name, version)` is immutable, and its authored
data is claimed by a name-independent `content_hash` that **`yank` does not release**. So on a single
instance every rehearsal permanently burns a version number *and* the right to publish that data under
any other name. On production that is correct — an installed module must keep verifying. On a test box
it makes rehearsal single-use, which is what these routes fix.

**On the dedup difference.** Within-account scoping keeps the gate exercised (your own rename is still
refused) while stopping one tester's rehearsal from blocking another's. The cost is explicit: a polygon
run cannot prove a *cross-account* duplicate would be refused in production.

### 35. `DELETE /api/v1/modules/{ns}/{name}/versions/{version}`  *(bearer — test instance only)*

Hard-delete one version: catalog rows, artifacts, and its content claim. `204` on success,
`404 version_not_found` if it was not there, `405` on a production instance, `403` without namespace
membership — authenticated and namespace-scoped exactly like publish, because the polygon answers on a
public DNS name and "open" means the verb is available, not that it is unauthenticated.

Not a substitute for `yank`, and production has no equivalent by design.

### 36. `DELETE /api/v1/modules/{ns}/{name}`  *(bearer — test instance only)*

The same, for every version of a module at once — a rehearsal usually leaves several behind, and
deleting them one at a time is how a cleanup job half-finishes. `204`, or `404 module_not_found`.

**SDK**: `RegistryClient.delete_version()` / `.delete_module()`. Always present, with no mode logic — a
client cannot know a host's mode before asking, so the limitation is in the docstring rather than in the
method's existence.
