# just-dna-registry — REST API Reference

Exhaustive reference for the registry HTTP API (v1). For the design rationale see
[SPEC.md](SPEC.md); for the reference client see [CLIENT.md](CLIENT.md).

- **Normative for:** registry **0.14.x–0.25.x**, API `v1` (0.15 added no route; it wrapped an
  existing one in the CLI. 0.16 added no route either: one response field on the dry runs, and a
  verdict that stopped disagreeing with the publish gate. **0.17 adds no route** — it adopts format
  0.6, which adds five query parameters to `GET /modules`, three blocks to the module detail, and
  five counters to every `resolution` object; see *Format 0.6 fields* below. **0.18 adds no route
  either**: 0.18.0 changed what `registry upgrade` acts on, which is an admin CLI behaviour with no
  HTTP surface, 0.18.1 is an enricher floor bump, 0.18.2 is another one plus a lint sweep that
  moved no signature, and 0.18.3 corrects a client docstring and the test coverage behind it.
  **0.20 adds no route either** — it adopts `just-dna-format`/`-compiler`/`-enricher` **0.6.6** and
  adds one field, `enrichment.literature.titles_as_quotes` on `/check`. Two behaviours move underneath
  it without any route changing: `stats.genes` is now a union over every authored gene-bearing table
  rather than `variants.csv` alone (so `?gene=` can find a PGx or copy-number module, for versions
  compiled from 0.6.6 on), and a duplicate `(source, layer)` row in `licensing.csv`/`sources.csv` is
  now a compile **error**, so a spec that published before can come back `422`.
  **0.25 adds two routes**: `GET /api/v1/caches` — anonymous, read-only, and the first endpoint that
  answers *what can this deployment do for a client that holds no snapshots* (§ 1a) — and
  `POST /modules/{ns}/{name}/derived`, which answers it with bytes (§ 29a) — plus
  `POST /drafts` (§ 29b), the only route here that is not namespace-scoped, because a draft is not
  about a published module — and the six `/hint/*` routes (§ 29c–g), which are the first endpoints
  here an **anonymous** caller can spend server resources on, under a per-upstream pace ledger.
  **0.24 adds one route**, `PATCH /modules/{ns}/{name}/short-description` — the first module-level
  amend, where the readme and the logo are per version. It adopts `just-dna-format` 0.7 and adds five
  response fields: `short_description` on `ModuleCard`,
  `carried` and `warnings_summary` on `ValidationReport` (`/validate`, `/check`), and
  `clin_sig_concordance` and `authority_precedence` on the module detail. Two behaviours move
  underneath it. `/check?strict=true` now grades the spec **after** enrichment rather than before, so
  an rsID-authored module gets an enrichment report where it used to get `invalid_spec` with nothing
  in it; and `/validate?strict=true` on a spec shipping no `resolution.csv` can newly report an
  unresolved-position error, because that endpoint does not enrich and upstream's RM141 made the
  strict pre-flight predict the strict compile. `artifact.digest` no longer reproduces across two
  compiles of one spec wherever a concordance record is produced — `content_signature` is unmoved and
  is what dedup keys on.
  **0.19 adds no route either** — it adds two fields to `VersionSummary`/`ResolutionInfo`, which a
  `v1` client that ignores them keeps working against. **0.21 adds no route either**: 0.21.0 is an
  admin-CLI behaviour with no HTTP surface, and 0.21.1 changes *what the listing returns on a
  `mode=test` deployment* without moving any shape — the test/sandbox exclusion is now production's
  policy alone. A response that was `total: 0` there can now be non-empty; nothing that was returned
  stops being returned, and production is unchanged. **0.22 adds no route either** — it adds
  `format_version` and `format_advisory` to the dry-run reports and `format_advisory` to the
  `422 invalid_spec` body, and starts *reading* the `X-Format-Version` request header the client
  has always sent. **0.23 adds no route either** — it adds a browser console *outside* the API:
  `/ui/` and a redirect from `/`, neither in `/openapi.json`, both off with
  `REGISTRY_UI_ENABLED=false`; see [UI.md](UI.md)).
  Written against the server at that version; a
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
- **Console:** `/ui/` (0.23) — a browser page over this API, not part of it; `/` redirects there.
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
| 1a | GET | `/api/v1/caches` | — | Snapshot lanes this deployment holds, and why not for the rest |
| 29a | POST | `/api/v1/modules/{ns}/{name}/derived` | bearer | Enrich a spec, return its `derived/` tables |
| 29b | POST | `/api/v1/drafts?source=` | bearer | Draft spec rows from a snapshot this box holds |
| 29c | GET | `/api/v1/hint/variant` | — / bearer | One variant: coordinates, alleles, clinical calls |
| 29d | POST | `/api/v1/hint/variants` | — / bearer | Many variants: snapshot first, live for misses |
| 29e | GET | `/api/v1/hint/citation` | bearer | Does this citation exist, and is it the right paper |
| 29f | GET | `/api/v1/hint/gene` · `/trait` | bearer | HGNC symbol / OLS4 CURIE currency |
| 29g | GET | `/api/v1/hint/old-assembly` | bearer | An hg19 coordinate to an rs-number |
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
  "format_version": "0.6.6",
  "format_advisory": null,
  "content_signature": "sha256:…",
  "name_matches_path": true,
  "published_as": [],
  "published_elsewhere": [],
  "would_publish_module_level": true
}
```

**`format_version` and `format_advisory` (0.22)** say which `just-dna-format` these findings were
graded against, and whether your side is newer. `format_version` is unconditional, because a
refusal an author cannot date is one they cannot act on. `format_advisory` is a sentence, present
only when the caller advertised a *newer* format than the instance holds **within the same minor** —
send `X-Format-Version` to get it; every `RegistryClient` already does.

**Why a patch gap needs saying at all (S18).** Every spec row model is `extra="forbid"`, and a
format patch may add a column: `StudyRow.curator` arrived in 0.6.5. An instance that predates it
rejects the column as `Extra inputs are not permitted` — pydantic's sentence for a **typo**, and
byte-identical to the one a misspelling gets. The version handshake passes the pair, correctly:
`contract_compatible` certifies that compiled artifacts and their digests interoperate, which within
a minor they do. It has never certified the authored row schema, which tightens at patch grain. So
the advisory carries that residue, and it is derived from the two version strings alone — never from
the findings beside it, which cannot tell the two causes apart. It rides on the `422 invalid_spec`
body from publish and import as well, where the refusal actually costs something.

Do not respond by stripping the column: that changes your authored bytes and moves the module's
`content_signature`, so the same module aimed at two instances would fork its content identity and
its `409 duplicate_content` claim. Align the client, or ask the operator to upgrade the instance.

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

**`unreachable` (0.17) is the same rule for a source that answers nothing.** A missing prerequisite is
one story; a 5xx, a timeout or a refused connection is another, and both end with a pass that reported
no findings. Each check object carries `unreachable` — the sources it asked and got no answer from — so
`covered: 0` beside `missing: []` can be told from gnomAD genuinely holding none of those alleles. Read
it before believing any empty list on a pass, exactly as you read `clin_sig_not_checked` before
believing `clin_sig_conflicts: []`. Two notes:

* **This is a `200`.** Until 0.17 it was a `500`: each pass adapter caught the pass's own error type
  while the pass let its *client's* type through, so an outage upstream failed the endpoint whose whole
  job is to report. An outage never moves `would_publish` either — it is a degradation of the report,
  not a finding about the module.
* **An empty `unreachable` does not mean the pass ran cleanly** — it means no source was *asked and
  unanswered*. A pass can also decline for a reason that is nobody's outage: offline with no snapshot,
  a licence gate, a module with no table to check. Those are `skipped` and `warnings`, and on `?acmg=`
  the distinction is upstream's own: `no_reference` (nothing to compare against — build a snapshot with
  `just-dna-enricher acmg build`) is reported as a warning naming it, not as `unreachable`, because the
  remedy is a file rather than a network.
* **On `?pgx=` it is per leg.** The three passes behind it run independently, so one source's outage no
  longer costs the others their findings, and `routes` still lists only what answered. ClinPGx never appears in
  `unreachable`: the API was retired, so it has no live route to be unreachable on, and its failures are
  skips with a reason.

**`?literature=true` carries `titles_as_quotes` (0.20), and it is the field to read before believing
`quotes_found`.** A `provenance_quote` that is the cited article's own title appears in that article's
fulltext by construction, so the grounding check *cannot* fail on it: the pass returns
`quotes_authored == quotes_found` with `quotes_unchecked: 0` while nothing about the claim has been
evidenced. `titles_as_quotes` lists the PMIDs where that happened. Same contract as
`clin_sig_not_checked` and `unreachable` — a number produced by two opposite histories gets a sibling
saying which — and, like every other finding on this pass, it never moves `would_publish`: it is a
defect in the module's evidence for an author to fix, not grounds for this server to refuse a publish.
The discriminator upstream uses is the article's **metadata**, not the shape of the string, because
length cannot separate a 17-word title from a 17-word sentence.

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
  file and a live API can differ by a release. It records what *answered*, so a leg that fell over gains
  no entry — that is `unreachable`.
* **PharmVar needs no key when a snapshot is present**, which is the configuration a public
  deployment wants: that key is personal and non-transferable under PharmVar's terms §2, so serving
  third parties on it is the thing to avoid. It is also the one cache the registry cannot pull for
  you — nothing is published, because the bulk data comes down under that same key. Build it once
  with `just-dna-enricher pharmvar build`.

Prefer the **ACMG snapshot** to the scrape even online: NCBI's page still serves SF v3.2 while ACMG
published v3.3 in June 2025, so a disagreement against the page is as likely to mean the list is old
as that the module is wrong. Those are reported apart, under `unverifiable` rather than `mismatches`,
and never count against `would_publish`. **`acmg.clean` is a plain bool, so it is `true` when
nothing was checked** — read `checked` and `unreachable` beside it. It stays a bool deliberately:
narrowing a published field to the tri-state `identifiers.clean` carries would break every client
branching on it.

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

### 29a. `POST /api/v1/modules/{ns}/{name}/derived`  *(bearer)*
Run the network tier over an uploaded spec and return its derived tables as a `.tar.gz`.

Multipart, both wire forms: loose `files=` parts or one `archive=`. `PUBLISH` on `{ns}`, the `enrich`
bucket, and the same gate lane as `/check` — `503 enrichment_busy` on a full gate,
`504 enrichment_timeout` past `enrich_timeout_seconds` — because the cost to the deployment is the
same.

**Why the route exists.** The compiler never fetches, so `resolution.csv` is what places
rsID-authored rows onto coordinates, and producing it needs the Ensembl and ClinVar snapshots. Those
run to tens of gigabytes across fourteen lanes; this box has them and an author's laptop does not. So
the tables have to *travel with* a spec for that spec to compile anywhere else, and until now the
only way to get them was to become a provisioned box. `GET /caches` says which lanes this deployment
actually holds before you ask.

```
derived/resolution.csv              # what places rsID-authored rows onto coordinates
derived/clin_sig_concordance.csv    # and the other fact sidecars the run produced
derived/verification.json
check.json                          # the validation report + {name, sha256, size} per member
WHERE-THIS-CAME-FROM.md             # the one caveat that bites; see below
```

- **It runs what a publish runs, not what `/check` runs.** `normalize_spec` then `enrich_spec`, and
  deliberately none of the opt-in check passes (frequencies, literature, identifiers, ACMG, PGx):
  those are egress spent producing a *verdict*, and a caller asking for the tree did not ask for one.
  Use `/check` for the verdict. Sharing the normalize-then-enrich order is what keeps the two from
  describing different specs.
- **The folder is a consequence of the contents, never a promise ahead of them** — the same rule
  `download(layout="split")` follows. A module that authors its own coordinates and needs no sidecars
  gets a report and a note and no `derived/` at all, which is the honest answer.
- **`check.json`'s digests let a caller verify what arrived; they are not an attestation.** There is
  no manifest before a compile. Attestation is the publish's — to hold this service to *"these are
  the bytes it would have compiled"*, publish and compare `artifact.digest`.
- **A spec too broken to enrich is a `422` carrying the `ValidationResult` errors**, not a `200` with
  an empty archive. That is deliberately the opposite of `/validate` and `/check` and not a
  contradiction of them: their contract is to *report* a finding, so a finding is a `200`. This
  route's contract is to *produce*, and a spec that cannot be enriched produces nothing.
- **The caveat in the note file, because it is the likeliest support ticket.**
  `derived/licensing.csv` is genuinely both provenances — your authored rows with the enricher's
  merged in. If your spec directory still carries its own `sources.csv` you now hold two spellings of
  one fact table, and `layout.resolve_sidecar` **raises** rather than preferring one, so the next
  upload is a `422` rather than a publish. Keep the file from here and drop the old spelling.

`registry-client derived <ns> <name> <spec_dir>` unpacks it over the spec directory, which is the
point: the module then compiles where it sits. `--out` writes the archive instead.

### 29b. `POST /api/v1/drafts?source=…`  *(bearer)*
Append drafted rows to an uploaded spec, from a source this deployment holds a snapshot for.

`source` is one of `clinvar`, `pubmind`, `civic`, `mitomap-miss`, `clinpgx`, `cpic`, `strchive` —
the enricher's own `draft-panel --source` vocabulary with its three standalone drafting commands
folded in. Multipart, both wire forms. Returns `application/gzip` of the drafted tree with
`draft-report.json` at its root.

**Not namespace-scoped**, and the only route here that is not: a draft is not about a published
module, so there is no namespace for a capability to be about. `require_account` — any authenticated
caller — in the `draft` bucket (10/h). Anonymous is refused for a stated reason: drafting reads
licence-gated snapshots this deployment acquired under **its own** declared use, and an anonymous
drafter would make the box a free panel generator whose licence acceptance belongs to somebody else.

- **What comes back will not validate yet, and that is the design.** Drafted rows carry
  `<<REPLACE>>` wherever only a curator can decide the value. `validates: false` is stated in the
  report rather than left to be inferred, and `needs_curation` names the tables that actually hold a
  placeholder — read off the bytes, because not every drafted table has one. A ClinVar draft writes
  `variants.csv` (genotype and conclusion: a curator's) *and* `studies.csv` (rsid and pmid: nobody's
  judgement), so naming both would send an author to fill cells that are already complete.
- **Stateless, which is the safety argument.** A re-draft over an existing spec appends corrected
  rows *beside* the ones they supersede. Nothing is held between calls: you upload a tree, the
  drafter appends into that tree, the tree comes back. Draft into a fresh spec directory; if you
  draft into one that already carries drafted rows, the `already_present` and `differs` counts are
  how you see it. `?dry_run=true` reports and writes nothing — and says so in `next_step`, because a
  dry run's empty `needs_curation` means "nothing was written", not "nothing is owed".
- **Snapshot-only by construction.** `download=False` and `offline=True` are forced, so the route
  makes no outbound request, takes no enrichment permit, and cannot be slowed by a running `/check`.
  A lane this deployment lacks is **`503 snapshot_unavailable`** naming the lane, its route and the
  route's recorded reason — deliberately not `enrichment_unavailable`, which means the tier is not
  installed at all. `GET /caches` answers which lanes are here before you ask.
- **A parameter the chosen source does not read is `422 param_not_for_source`**, carrying both what
  was rejected and what that source does accept. A silently dropped `min_evidence_level` produces a
  draft answering a different question from the one asked.
- Gene arity is checked up front: `cpic` drafts exactly one gene per call, `clinvar` and `pubmind`
  need at least one, the rest are optional. `422 gene_count` rather than an error from inside a
  drafter.

`registry-client draft <spec_dir> --source clinvar -g F5` unpacks the result over the spec directory
and prints what was appended, what was already there, and what differs and was left alone.

### 29c–g. `/api/v1/hint/*`
The enricher's authoring lookups, answered from this deployment's snapshots. Named `hint`, not
`lookup`: `/modules/lookup` already means *"is this content published?"*, and `hint` is the
enricher's own word for this surface.

| route | answers |
|---|---|
| `GET /hint/variant` | validity, coordinates, alleles, clinical calls, frequencies |
| `POST /hint/variants` | the same for many keys — snapshot first, live only for misses |
| `GET /hint/citation` | does this citation exist, and *which paper is it* |
| `GET /hint/gene` · `GET /hint/trait` | HGNC symbol / OLS4 CURIE currency |
| `GET /hint/old-assembly` | an hg19 coordinate to an rs-number |

**Nothing is written and nothing is decided.** Every suggestion comes back as an entry in
`alterations` with `applied: false` and a `refusal` saying why the value is the author's to type. That
is not fastidiousness: almost every fact here is cross-examined later by a check that only works
because the author wrote it *independently*, so filling a cell from the same oracle the checker
consults turns that check into a tautology. A one-to-many rsID returns every locus rather than
picking one, and a position matching several rsIDs returns every candidate.

**Three tiers, and the free one is the product:**

| tier | may set | metered by |
|---|---|---|
| anonymous | `offline=true` only | the `hint` request bucket |
| authenticated | `offline=false` | bucket + the per-upstream pace ledger |
| authenticated, and `REGISTRY_HINT_ALLOW_GNOMAD=true` | `frequencies=true` | as above, with gnomAD's own tiny allowance |

A thin client with no Ensembl snapshot getting an rsID placed onto a coordinate, for free, at zero
egress to anyone, is this surface working exactly as designed. Anonymous *online* is refused on both
instances and does not vary by mode: gnomAD rate-limits by IP and sells no key at any price, so one
anonymous caller could throttle every publisher on the box, and the cooldown needs a stable identity
(a shared NAT makes the IP branch worthless as a key).

**`cost` is on every answer, including when it is empty.**

```json
"cost": {"charged": {}, "served_from": ["ensembl"], "limit": null, "waited_seconds": 0.0, "remedy": null}
```

An empty `charged` is the field that teaches a client which of its traffic is free — without it,
*"you are being throttled"* has two opposite histories (spent egress, or the plain request bucket)
with opposite remedies, and `limit` is the sibling that tells them apart. Units are **per upstream and
not exchangeable**: one fungible counter would let a caller spend gnomAD's unbuyable ten-per-minute
allowance at the price of a three-per-second NCBI call.

**Past the daily allowance the pace decays rather than stopping.** The minimum interval between
charged calls is the upstream's *own* spacing doubled once per tier, so *"4× gnomAD's own interval"*
is actionable where a bare number is arbitrary. A wait under `hint_inline_wait_seconds` is absorbed by
the server; a longer one is `429 hint_pace_decayed` with `Retry-After` and a remedy that is honest for
that upstream — gnomAD sells no key, NCBI's key paces whoever holds it, OLS4 and HGNC issue none. The
one remedy true everywhere is to provision the snapshot or run the enricher yourself. A day finished
over the allowance halves the next day's; a clean day restores it in full.

**Use the batch, not a loop.** An online single lookup egresses unconditionally — dbSNP merge status
has no snapshot in this tree, so that leg runs whatever the cache said — while `POST /hint/variants`
runs the offline pass over every key at no cost and goes online only for what missed. On a
provisioned deployment a whole module's worth of keys comes back charging nothing. `frequencies` is
refused in a batch outright: at six seconds per key it cannot finish inside a request.

**No filesystem path appears in any hint**, and since enricher 0.7 that is upstream's design rather
than our audit. `checked` is a set of **labels** — a lane name, or a live source like `ensembl-live` —
and `snapshots` is the label → path map, which this service **never serializes**. One scrub survives
because upstream keeps a third-party error's own first line as evidence, and it may name a file.

**These are registry models, not the enricher's types — a consumer needs a thin translation.** Every
field the enricher reports survives, but two are reshaped and one is replaced:

| enricher | here | why |
|---|---|---|
| `VariantHint.rsid_status` (a `RsidStatus`) | `rsid_state` + `rsid_current` | flattened, so a consumer does not need the dataclass |
| `VariantHint.checked` (labels, since 0.7) | `cost.served_from` | a rename, not a scrub — it belongs with what the answer cost |
| `VariantHint.snapshots` (label → path) | *(dropped)* | the one field carrying paths; upstream built it to be droppable |
| `OldAssemblyHint.recovery` (an `RsidRecovery`) | its fields, inlined | same reason as `rsid_status` |
| — | `cost` | new here: what the answer spent and where it came from |
| — | `ambiguous` | the enricher exposes it as a property, so it does not survive serialization |

`findings` and `alterations` keep their names but are lists of plain objects rather than `Finding` /
`Alteration` dataclasses: `{level, column, message}` and `{column, value, source, applied, refusal,
note}` — the latter is the enricher's own `as_report_rows` shape, scrubbed. `CitationHintReport` is
field-for-field `CitationHint` plus `cost`.

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

### 1a. `GET /api/v1/caches`
No auth. Which snapshot lanes this deployment can read, and for an absent one the route it would
arrive by and the reason it has not.

```json
{
  "enricher_available": true,
  "declared_use": "unstated",
  "lanes": [
    {"name": "clinvar", "serves": "clinical significance and review status", "state": "present",
     "release": "clinvar_2026-06-27", "release_unreadable": false,
     "route": "pullable", "route_reason": null, "build_command": "clinvar build",
     "licence_gated": false, "licence_skip": null,
     "read_here": true, "group": "resolution", "configured": true, "parents": []},
    {"name": "pharmvar", "serves": "star-allele nomenclature", "state": "absent",
     "release": null, "route": "buildable",
     "route_reason": "bulk data comes down under a personal, non-transferable key",
     "build_command": "pharmvar build", "licence_gated": true,
     "licence_skip": "pharmvar forbids sale and no use was declared",
     "read_here": true, "group": "pgx", "configured": false, "parents": []}
  ]
}
```

This is the registry answering *"what can I lean on you for?"* — the question a client without the
multi-gigabyte snapshots has to ask before deciding whether to provision fourteen of its own, and the
question a publisher has after a `/check` reported a source skipped.

- **Three states, not two.** `present` · `absent` · **`partial`**, where the directory holds
  something that is not a readable snapshot. That last one is the case provisioning **refuses** to
  act on rather than overwriting (it never deletes), so reporting it as `absent` would send an
  operator to run a pull that is going to decline. Move the directory aside first.
- **`release` is `null` when the snapshot does not say** — never a placeholder, because a caller has
  to be able to tell a named release from one that cannot name itself. `release_unreadable` sits
  beside `state: present` rather than downgrading it: an unparseable `release.json` is a provenance
  failure, not a data failure, and the snapshot is still usable.
- **`route_reason` is upstream's own sentence**, carried on the lane (`unpublished` / `unbuilt`) — a
  personal key, terms nobody publishes, a permission never established, a snapshot another tier
  cuts. Never a sentence written here, because a red cross an operator cannot act on is worse than
  no field.
- **`licence_skip` is the other half of "not provisioned".** A licence-gated lane under a
  `declared_use` that declines it will never arrive from a pull however many times one is run. That
  is a different instruction from *nobody has pulled it yet*, and it is computed with the enricher's
  own gate so the report agrees with the refusal it predicts.
- **`read_here` and `group`** say whether a pass *in this service* opens the lane. Deliberately
  narrower than the set an operator can provision: the same box often runs authoring commands, and a
  lane nothing here reads is still worth reporting rather than hiding.
- **`configured`** is whether this deployment pins the location or lets the lane's own ladder find
  it. **No filesystem path appears in this response and none may be added.** Lane presence is an
  operational fact of the same class `/health` already publishes unauthenticated; the server's
  directory layout is not. Note the argument that does *not* license this endpoint: a caller cannot
  enumerate lane state through `/check`, which needs the `PUBLISH` capability.
- **Reports only.** Nothing here downloads or builds anything — that is `registry warm-caches`, an
  operator command on the box that holds the caches, deliberately not a request-path concern.
- `enricher_available: false` is one deployment fact rather than fourteen separate failures: the
  `server` extra is what carries `just-dna-enricher`, and a client that cannot tell the two apart
  tells an operator to provision snapshots on a box with nothing to read them with.

### 2. `GET /api/v1/modules`
List/search the catalog (one **card** per module, its latest non-yanked version).

Query params: `q` (title/description substring), `category`, `gene`, `genome_build`, `owner`,
`license` (exact facet matches), `namespace` (restrict to one namespace), `featured` (`true` →
only featured), `include_blacklisted` (`true` → include hidden namespaces), `group` (a tab preset —
see below), `sort` = `name` (default) | `downloads` | `recent` | `stars` | `popular`, plus `page`,
`per_page`. Facet filters match modules with a non-yanked version carrying that gene/category.

**Fact-table filters (0.17, format 0.6)** — `has_gene_validity`, `has_clinical_assertions`,
`has_gwas_effects`, `has_frequencies`, `weighting_declared`. Each is **tri-state**: omitting it does
not filter, which is not the same as `false`. They match against the module's **current** version,
the same scoping `gene` and `category` use — a sidecar dropped two releases ago stops answering.

`weighting_declared=false` is the deliberately useful negative: it finds modules that have **not**
said what their authored `weight` column means, which is the population a consumer must not
aggregate across. An absent declaration means *the module has not said*, never *the weights are
comparable*.

There is no `verification` filter and there will not be one — see *ModuleDetail*.

**`group`** is a server-defined tab preset over the raw filters (a group wins over the equivalent
`sort`/`featured`): `all` (everything), `featured` (`featured=true`), `curated` (has an
owner-highlighted review — see reviews), `popular` (`sort=popular`), `new` (`sort=recent`), `test`. **Test/sandbox namespaces** — those matching the server-config
`REGISTRY_TEST_NAMESPACE_PATTERN` (default `^(sandbox|test)([-_]|$)`) — are surfaced **only** under
`group=test` and hidden from every other tab and the default listing; they stay reachable by an
explicit `namespace=`. Membership is server-owned so all clients agree. Discover the tabs at
`GET /api/v1/modules/groups`.

**That hiding is production's policy only, since 0.21.1.** On a `mode=test` deployment (the polygon)
the exclusion does not apply: the default listing, `group=all` and `?q=` answer for the whole catalog,
because sandbox spaces are all that instance holds and excluding them made every read path report
`total: 0` on a box `/health` counted as non-empty. `group=test` is unchanged and means the same thing
on both — the sandbox spaces, which on the polygon is usually everything. Ask `/health` for `mode` if
you need to know which rule an instance is applying; `GET /api/v1/modules/groups` also describes `all`
differently there.

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

The **keys and their order are the same on both deployment modes**; `all`'s *description* is not. On
a `mode=test` instance it reads `"Everything published on this test instance (nothing is excluded
here)."`, because the exclusion that sentence describes does not apply there (0.21.1). Render the
description you are served rather than one baked into the client — the alternative is a tab labelled
"test/sandbox spaces excluded" above a list that excludes nothing.

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
{"version":"2.0.0","artifact_digest":"sha256:…","content_signature":"sha256:…",
 "compile_success":true,"yanked":false,"resolution":{"signature":"sha256:…","sources":["Ensembl"],"…":"…"},
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

#### Spec layout (0.17) — what may arrive, and from where

The compiler reads one flat directory, so that is the canonical layout and the server normalises an
upload onto it before reading anything. Applied identically by `/versions`, `/versions/import`,
`/validate` and `/check`, and reported on the dry runs' `info[]`:

- **A recognised spec file in a subdirectory is lifted to the root.** `derived/resolution.csv`
  publishes exactly as `resolution.csv` does. `derived/` is the folder this registry emits (see
  `--layout split` in [CLIENT.md](CLIENT.md)), but any folder name is accepted on the way in, because
  producers already ship `metadata/` and `enriched/` trees and refusing them buys nothing.
- **`MODULE.md` is renamed to `README.md`**, unless a `README.md` is also present — then the real
  name wins, the legacy file is carried unchanged, and a warning says so.
- **`sources.csv` is renamed to `licensing.csv`** (0.17; the rename ran the *other* way in 0.16.2,
  when this deployment's compiler could read only the old spelling). They are one table under two
  spellings, and format 0.6 makes `licensing.csv` the name while deprecating `sources.csv` for
  removal at format 1.0 — so an upload under either keeps working, and storing the current one is
  what keeps a spec authored years ago publishable at 1.0 without its author editing anything. It is
  also what stops a deprecation warning being written into every published manifest, which is
  immutable. The rename moves no identity: the ledger is a fact sidecar, outside `content_signature`
  and therefore outside the global `409 duplicate_content` claim.

  **Both spellings present is a `422`**, not a preference — this is the one place where the rule
  differs from `MODULE.md`. The compiler *raises* on two copies of one fact table (they are
  fact-hashed and hand-editable, so two copies are two claims and preferring either discards
  somebody's curation), so carrying the loser through as an extra file would produce a failed compile
  rather than a publish with a warning. An extra stray markdown file, by contrast, makes the compiler
  do nothing at all.

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
`README.md` had before 0.14. **Since 0.17 it is also surfaced**, because format 0.6 lets the manifest
attest it: the compiler reads the file and this API projects the result as `ModuleDetail.verification`
(see *ModuleDetail* under *Schemas*, which is also where the boundary between the publisher's claim
and the registry's word is set out). Nothing in this service parses the file itself, and the
distinction is not pedantry — it is the *author's* record of what their enricher checked against live
sources, which a server that compiles offline cannot reproduce and must never present as its own. It
is served and downloadable as a `derived` entry, never rendered as a registry verdict, and never a
filter.

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
`version, artifact_digest, content_signature, compile_success, yanked, signed, needs_upgrade,
downloads, created_at, changelog, manifest_url, resolution: ResolutionInfo`. `downloads` is the
per-version download count.

`artifact_digest` and `content_signature` are the identity pair and answer different questions.
The digest names the compiled **bytes** and moves whenever a recompile restamps a timestamp, so two
publishes of one spec routinely differ; `content_signature` names the authored **data** and is what
`409 duplicate_content` is keyed on. Comparing two versions of a module, the second is the one to
read. Both are stored values off the manifest, never recomputed on read. `content_signature` is
`null` on a pre-0.5 manifest that carries none. **Added in 0.19** (S14).

### ResolutionInfo
`mode, fully_resolved, trusted, vrs_alleles, vrs_alleles_identified, vrs_complete,
resolution_subjects, positional_rows, positional_rows_placed, expanded_keys, expanded_rows` (the
last five are 0.17), plus `sources[]` and `signature`.

`signature` is `compilation.resolution_signature`, the fact signature over what resolution decided.
It moves when an upstream source revises an answer while `content_signature` stands still, which is
the one situation the identity pair above cannot distinguish from a no-op recompile. **Through 0.18
it and `sources[]` were populated only on the card**, so the version list — the only endpoint that
sees a whole chain — was the one that could not compare it; both are on every copy since 0.19 (S14).
Unlike the five counters, `signature` is not era-gated: it has been nullable since 0.5, so `null`
means the version carries none rather than that it was not read.

`trusted` is tri-state — `false` when the compiler reported a table no VCF can join by position,
`null` when we have no verdict to offer.

**The five counters are `int | null`, and `null` is *not measured* — never `0`.** Each has a
meaningful zero: `resolution_subjects: 0` is a module that resolved nothing, `positional_rows: 0` is
one carrying no PGx/positional table, `expanded_keys: 0` is one where resolution found no one-to-many
expansion. Every version compiled before format 0.6 reports `null` for all five, which is how you
tell the eras apart without probing parquet. Do not coalesce them.

Read `resolution_subjects` **beside** `fully_resolved`: that flag is `all()` over the module's variant
rows, so `fully_resolved: true` with `resolution_subjects: 0` is an empty quantifier rather than a
verdict. "Positionally complete" is `positional_rows_placed == positional_rows` — parts rather than a
ratio, so the size of a shortfall is visible. And `expanded_rows - expanded_keys` is **not** the count
of rows that cannot match; that needs per-row information the manifest does not carry.

### ModuleDetail
`ModuleCard` fields + `readme: string`, `versions: VersionSummary[]`, `latest_manifest: ModuleManifest`,
plus the three format-0.6 blocks below, each projected from the **latest** version's manifest and
each `null` when that version carries none.

`weighting: {scale, method, note} | null` — what the module says its authored `weight` column means
(RM92). All three are **free text and rendered verbatim**; upstream declined to impose a vocabulary,
so neither does this. **`null` is the load-bearing value**: it means the module has not said, which a
consumer must read as *do not combine these weights with another module's*, not as *safe*.

`gwas_effects: {row_count, variant_count, with_effect_allele, without_effect_allele, measures[],
units[], traits[], sources[], datasets[]} | null` — the GWAS Catalog effect-size sidecar (RM90).
**Read `units` and `without_effect_allele` before using any of it.** More than one entry in `units`
means those betas are on different scales and must not be pooled — one real variant in the reference
corpus carries twelve distinct unit spellings across 62 traits. `without_effect_allele` counts
associations the Catalog published without establishing which allele carries the effect; they are
real evidence and **cannot be used as a weight in any direction**, and they are counted rather than
filtered so that neither dropping nor keeping them can happen by accident. A `row_count` on its own
reads as confidence, which is why it is never rendered alone.

`verification: {closed, closed_at, closed_by, producer, produced_at, checks[]} | null` — whether
anything the module asserts was ever *checked* (RM45). Each entry of `checks` is
`{check, subjects, findings, skipped, detail, source, release, checked_at}`, where `skipped: null`
means the check ran; `subjects: 0` beside a reason is *not* the same statement as `subjects: 0`
without one.

**How much of this block is the registry's word, measured rather than asserted.** A check *this
server runs* cannot be forged — publish runs enrichment itself and its record displaces whatever
arrived under the same name. A check *this server does not run* is carried **verbatim from the
upload** and is unverifiable. `closed` is the sturdiest field, because a closure is hash-bound: the
compiler recomputes the binding against the authored bytes and drops the closure when it does not
match, so `closed: true` cannot be claimed by editing a JSON file — though `closed_by` is free text
and proves that someone declared authoring finished, not who.

Consequently: **absent reads as *nothing was said*, never as *passed***, and this block is
deliberately **not** on the card and **not** filterable or sortable. A registry that let you rank by
someone else's unverifiable pass would be lending it our credibility.

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
