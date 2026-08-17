# just-dna-registry — Client Reference

The reference client is the **default install** of `just-dna-registry` — import it instead of
re-implementing REST calls + integrity verification. It ships as a Python library
(`RegistryClient`) and an equivalent CLI (`registry-client`). Wire protocol:
[API-REFERENCE.md](API-REFERENCE.md).

**Normative for:** client **0.14.x–0.17.x** against a server speaking API `v1`. Every method signature and
payload shape here is exact for that range. The client surface is additive within `v1`: methods gain
optional keyword arguments and responses gain fields, so code written against an earlier 0.x client
keeps working — [CHANGELOG.md](CHANGELOG.md) carries a **client surface** line per release naming
any method whose signature moved, so a consumer can answer "did this release touch anything I call?"
without reading the release (S2).

## Install

```bash
pip install just-dna-registry            # client only (httpx + just-dna-format)
pip install just-dna-registry[server]    # + the server (FastAPI app, compiler, admin CLI)
```

## Configuration

Both the Python client and the CLI take the base URL and (for writes) an API key. The CLI reads
them from flags, then environment, then a local `.env`:

| Setting | Env var | CLI flag | Default |
|---|---|---|---|
| Base URL | `REGISTRY_URL` | `--url` | `http://127.0.0.1:8000` |
| API key | `REGISTRY_TOKEN` | `--token` | — (required for publish/import/update) |

```bash
export REGISTRY_URL=https://module-registry.just-dna.life
export REGISTRY_TOKEN=mk_live_…
```

## Python ↔ CLI at a glance

| Capability | `RegistryClient` method | `registry-client` command | Auth |
|---|---|---|---|
| List / search | `list_modules(q=, gene=, category=, …)` | `list` | — |
| Module detail | `get_module(ns, name)` | *(use the API / `download`)* | — |
| Version list | `versions(ns, name)` | *(via detail)* | — |
| Full manifest | `manifest(ns, name, v)` | *(written by `download`)* | — |
| List logs | `logs(ns, name, v)` | *(via `download`, which fetches them)* | — |
| Find by digest | `lookup_by_digest(digest)` | `find-by-hash` | — |
| Batch find by digest | `lookup_by_digests(digests)` | *(programmatic)* | — |
| Content signature (local) | `content_signature(spec_dir)` | `signature` | — |
| Find by content signature | `lookup_by_signature(sig)` | `signature --lookup` | — |
| Already published? | `is_published(spec_dir, namespace=, name=)` | `signature --lookup` | — |
| Validate a spec | `validate(ns, name, spec_dir)` | `validate` | bearer |
| Full publish dry run | `check(ns, name, spec_dir)` | `check` | bearer |
| Server liveness | `health()` | *(programmatic)* | — |
| Exchange key for a JWT | `issue_jwt_token(api_key)` | *(programmatic)* | api key |
| Self-register | `register(install_id, account)` | `register` | install-id |
| Namespace availability | `namespace_available(ns)` | `namespace-available` | — |
| Claim namespace | `claim_namespace(ns)` | `claim-namespace` | bearer |
| Download + verify | `download(ns, name, v, dest)` | `download` | — |
| Download tarball | `get_tarball(ns, name, v, dest)` | `download … --tarball` | — |
| Publish (spec dir) | `publish(ns, name, v, spec_dir)` | `publish` | bearer |
| Publish (archive) | `import_module(ns, name, v, archive)` | `import-module` | bearer |
| Bump a version | *(`get_module` + `publish`)* | `update-module-version` | bearer |
| Amend changelog | `amend_changelog(ns, name, v, text, append=)` | `amend-changelog` | bearer |
| Amend logo | `amend_logo(ns, name, v, logo_path)` | `amend-logo` | bearer |
| Amend readme (card prose) | `amend_readme(ns, name, v, path_or_text)` | `amend-readme` | bearer |

---

## Python: `RegistryClient`

```python
from just_dna_registry import RegistryClient, RegistryError

with RegistryClient("https://module-registry.just-dna.life", token="mk_live_…") as mkt:
    ...
```

**`RegistryClient(base_url, token=None, timeout=120.0, transport=None)`** — a context manager
(closes the underlying `httpx.Client`). `transport` is for tests (e.g. an ASGI transport).
Non-2xx responses raise **`RegistryError(status_code, detail)`**.

### Reads (no token)

- **`list_modules(*, q=None, category=None, gene=None, genome_build=None, owner=None, license=None,
  namespace=None, featured=None, include_blacklisted=False, has_gene_validity=None,
  has_clinical_assertions=None, has_gwas_effects=None, has_frequencies=None,
  weighting_declared=None, group=None, sort="name", page=1, per_page=20) -> dict`** — a `Page` of
  cards; `None` filters are dropped. Keyword-only and fully named on purpose: the server ignores a
  query param it does not know, so a misspelled facet would otherwise come back as a *wider* result
  set that looks like a working search.
  - The five fact-table filters (0.17) select on what a module's **current** version carries and are
    tri-state — omitted means "do not filter", which is not `False`. `weighting_declared=False` is
    the useful negative: it finds the modules that have not stated what their `weight` column means,
    i.e. the ones you must not aggregate across.
- **`get_module(namespace, name) -> dict`** — module detail (readme, versions, `latest_manifest`,
  full `stats.genes`), plus the format-0.6 blocks `weighting`, `gwas_effects` and `verification`,
  each `null` when the latest version carries none. Two reading rules that the API reference spells
  out and are worth repeating where they will be met: a `null` `weighting` means *the module has not
  said what its weights mean* (not that they are comparable), and an absent `verification` means
  *nothing was said* (not that anything passed). If you render `gwas_effects`, render `units` and
  `without_effect_allele` — a bare `row_count` reads as confidence the data may not support.
- **`versions(namespace, name, *, page=1, per_page=20) -> dict`** — a `Page` of `VersionSummary`.
  The listing is paged server-side (`per_page` max 100), so a long history needs the second page.
- **`manifest(namespace, name, version) -> ModuleManifest`** — the parsed `just_dna_format`
  manifest.
- **`logs(namespace, name, version) -> list[dict]`** — `[{name, sha256, size, url}]`.
- **`lookup_by_digest(digest) -> list[dict]`** — matches `[{namespace, name, version, yanked}]`
  (empty if none).
- **`lookup_by_digests(digests) -> dict[str, list[dict]]`** — batch: `{digest: matches}` in one
  request (classify many local modules; digests come from their `manifest.json`).

### Onboarding (community self-service)

- **`register(install_id, account) -> dict`** — `{token, account, namespaces}` from a proof-of-work
  install-id (no auth; mints the key). Grind an id with `generate_install_id()` (also exported at
  top level: `from just_dna_registry import generate_install_id`).
- **`namespace_available(namespace) -> dict`** — `{namespace, valid, available}`.
- **`claim_namespace(namespace) -> dict`** *(token)* — claims it for your account
  (`{namespace, owner, already_owned}`); raises `RegistryError` `409`/`403` if taken/over-limit.
- **`download(namespace, name, version, dest, *, include_logs=True, include_inputs=False,
  layout="flat") -> ModuleManifest`** — fetches the artifact files (and logs), writes
  `manifest.json`, and **verifies integrity** with `verify_manifest` (raises `IntegrityError` on
  mismatch). Returns the manifest.
  - `include_inputs=True` also fetches the **authored** spec — `module_spec.yaml`, `variants.csv`
    and the table CSVs — and hash-checks each against `manifest.inputs`. Off by default because the
    download listing is the compiled parquets and an installer wants nothing else; on, it is the
    difference between downloading an artifact and downloading a module.
  - `layout="split"` (0.14) moves the machine-written tables — `resolution.csv` and the fact
    sidecars — into `derived/`, so a reader can tell the enricher's files from the author's, and
    drops a `WHERE-THIS-CAME-FROM.md` beside them. Applied **after** verification, never before: the
    manifest attests flat names, so a tree split first is a tree that fails to verify. Re-uploading
    either layout publishes the same module — the server flattens it back and none of these files is
    in the content signature. `split_derived(module_dir)` is the same move as a standalone function.
  - **It separates properly since 0.17, and that is upstream's doing.** Through 0.16 the manifest
    had fields for `logs` and `logo` and none for the derived CSVs, so a downloader could not
    receive them at all and `derived/` was created only if something happened to land in it — filed
    as S26 and answered by format 0.6's `manifest.derived`. `include_inputs=True` now fetches the
    machine-written sidecars alongside the authored spec and hash-checks them
    (`verify_manifest(check_derived=True)`), which is what makes a downloaded module recompile where
    it lands: the compiler never fetches, so `resolution.csv` has to arrive with it.
  - The readme travels too, verified like everything else (`manifest.readme`, S5). Before 0.6 it was
    prose the server rendered on a card and no client could check.
- **`get_tarball(namespace, name, version, dest) -> Path`** — saves the streamable `.tar.gz`.

### Writes (token required)

- **`publish(namespace, name, version, spec_dir, changelog="") -> ModuleManifest`** — uploads the
  spec directory (`gather_spec_files` collects yaml/csv/md/logo/logs, skipping parquets +
  `manifest.json`) and returns the compiled manifest. A `derived/` subfolder, a legacy `MODULE.md`
  and a format-0.6 `licensing.csv` are all normalised server-side — see *Spec layout* in
  [API-REFERENCE.md](API-REFERENCE.md). Nothing to do on your side: send the spec as your tooling
  wrote it.
- **`import_module(namespace, name, version, archive_path, *, changelog="", display=None) -> ModuleManifest`**
  — uploads a zip/tar.gz. `display` (`title/description/report_title/icon/color`) is used only for
  legacy parquet-only archives. `display["genome_build"]` rides along the same channel but is *not*
  display metadata: the build decides the identity key, so a GRCh37 archive with no `manifest.json`
  must declare it or it is reversed as the format's GRCh38 default, minting `variant_key`s for a
  base the module never carried. See API-REFERENCE §import.

**The three amends** are the only way to repair a *published* version, and all three are
out-of-digest: the artifact, its `artifact.digest` and any signature over it stay untouched, so
neither the version number nor the `content_hash` claim moves. Each needs amend rights (own version
for a member, any for admin+).

- **`amend_changelog(namespace, name, version, changelog, *, append=False) -> dict`** — replace (or
  append to) a version's changelog.
- **`amend_logo(namespace, name, version, logo_path) -> dict`** — replace the version's logo image.
- **`amend_readme(namespace, name, version, readme) -> dict`** — replace the module card's prose.
  Takes a `Path` **or** the markdown text: a tool usually has the file, a human fixing one sentence
  has the string. `""` blanks the card. This is the amend that matters most — the readme is where a
  module says what it is *not*, and `description` is one sentence that cannot carry a caveat.

### Identity & profile (token)

- **`whoami() -> dict`** — `{account, namespaces, type, display_name, avatar_url, email}` (`email`
  only ever returned to the account itself).
- **`update_profile(*, email=None, display_name=None, avatar_url=None, funding_url=None) -> dict`** — edit your own
  profile; only the fields passed are sent, `""` clears one. `type` is not self-editable.

### Social & moderation (token)

- **`star(ns, name)` / `unstar(ns, name) -> dict`** — toggle a favourite (idempotent).
- **`reviews(ns, name, version=None) -> list[dict]`** — a module's (or one version's) reviews,
  highlighted first (anonymous).
- **`review(ns, name, version, *, rating, verdict=None, notes=None) -> list[dict]`** — post/update
  your review of a version (one per account per version); returns the version's review list.
- **`delete_review(ns, name, version) -> list[dict]`** — remove your own review.
- **`highlight_review(ns, name, version, reviewer, *, highlighted=True) -> list[dict]`** — owner
  highlights (or un-highlights) a review — the `curated` signal.
- **`yank(ns, name, version)` / `unyank(...) -> dict`** — owner: drop from listings/`latest` (kept
  fetchable) or reverse it.
- **`members(ns) -> list[dict]`**, **`add_member(ns, account, role="member")`**,
  **`remove_member(ns, account) -> dict`** — namespace membership (`owner|admin|member`; adding a
  member needs admin+, granting admin/owner needs owner).

### Orgs & funding (token)

- **`create_org(name) -> dict`** — create an org account (caller becomes owner).
- **`org_members(org)`**, **`add_org_member(org, account, role="member")`**,
  **`set_org_role(org, member, role)`**, **`remove_org_member(org, member) -> dict`** — org
  membership (roles cascade to org-owned namespaces).
- **`update_org_settings(org, funding_url=…, display_name=…, avatar_url=…, email=…) -> dict`** — edit
  the org profile (owner-only).
- **`create_org_namespace(org, namespace) -> dict`** — claim a namespace owned by the org (admin+).
- Funding: set your own via `update_profile(funding_url=…)`; a module card carries both
  `author_funding_url` and `org_funding_url`.

### Discovery & stats

- **`groups() -> list[dict]`** — the listing tabs `[{key, label, description}]`.
- **`catalog_stats(namespace=None, *, group=None) -> dict`** — aggregate totals (modules,
  namespaces, downloads, stars, views, reviews, curated, variants, studies, genes) by paging the
  listing; there is no dedicated stats endpoint, so this rolls up the card fields.

### Helper

- **`gather_spec_files(spec_dir) -> list[tuple[str, bytes]]`** — the uploadable (relative-name,
  bytes) pairs for a spec dir; excludes compiled `*.parquet` and `manifest.json`.

### Example

```python
from just_dna_registry import RegistryClient, RegistryError

with RegistryClient(url, token) as mkt:
    m = mkt.import_module("just-dna-seq", "coronary", "1.0.0", "coronary_v1.zip")
    print(m.artifact.digest)

    if mkt.lookup_by_digest(m.artifact.digest):
        print("already published")

    mkt.download("just-dna-seq", "coronary", "1.0.0", "./coronary")  # verifies or raises

    try:
        mkt.publish("just-dna-seq", "coronary", "1.0.0", "./spec")   # same version again
    except RegistryError as e:
        assert e.status_code == 409  # version_exists
```

---

## CLI: `registry-client`

All commands accept `--url` (or `$REGISTRY_URL`); write commands accept `--token`
(or `$REGISTRY_TOKEN`).

### `list`
```bash
registry-client list [--q TEXT] [--gene GENE] [--category CAT] [--sort name|downloads|recent]
```
Prints one line per module (`ns/name@latest [N variants, M genes] ↓downloads — title`).

### `download`
```bash
registry-client download NS NAME VERSION DEST          # extract + integrity-verify into DEST/
registry-client download NS NAME VERSION DEST --with-inputs --layout split   # a readable module
registry-client download NS NAME VERSION FILE.tar.gz --tarball   # save a single tar.gz
```
`--with-inputs` adds the authored spec, which a bare download leaves behind; `--layout split` then
sorts the enricher's tables into `derived/`. Both are off by default.

### `register`
```bash
registry-client register ACCOUNT [--install-id jdi1_…] [--difficulty 20]
```
Grinds an install-id (unless `--install-id` given), self-registers, and prints the account,
install-id, and API key. Save both; put the key in `REGISTRY_TOKEN`.

### `namespace-available` / `claim-namespace`
```bash
registry-client namespace-available alice-mods
registry-client claim-namespace alice-mods        # (token)
```

### `find-by-hash`
```bash
registry-client find-by-hash sha256:…                  # by digest
registry-client find-by-hash --manifest ./mod/manifest.json    # read digest from a local manifest
```
Exit code `1` (and "not published") if there are no matches.

### `publish`  *(token)*
```bash
registry-client publish NS NAME VERSION SPEC_DIR [--changelog "…"]
```
Uploads a spec directory (must contain `module_spec.yaml` + `variants.csv` + `studies.csv`). On
success it **stamps** the returned manifest into `SPEC_DIR/manifest.json`, so the local module is
afterwards discernible as published-by-you (identity + `published_at`).

### `import-module`  *(token)*
```bash
registry-client import-module NS NAME VERSION ARCHIVE.zip \
    [--changelog "…"] [--title …] [--description …] [--report-title …] [--icon …] [--color …] \
    [--genome-build GRCh37]
```
Publishes from a zip/tar.gz. Display flags apply only to legacy parquet-only archives.
`--genome-build` is not one of them: it decides the identity key, and a bare parquet archive that
carries no `manifest.json` and is not GRCh38 needs it declared.

### `amend-changelog` / `amend-logo` / `amend-readme`  *(token)*
```bash
registry-client amend-changelog NS NAME VERSION "text" [--append]
registry-client amend-logo      NS NAME VERSION ./logo.png
registry-client amend-readme    NS NAME VERSION ./README.md
registry-client amend-readme    NS NAME VERSION -            # read the markdown from stdin
registry-client amend-readme    NS NAME VERSION --clear       # blank the card, said out loud
```
Post-publish repair, all out-of-digest: no version bump, no new `content_hash`. `amend-readme`
landed in 0.15.0 (S9) — the client method had shipped a release earlier, which left a CLI-only
author with a blank card and nothing to run. It takes a file, or `-` for stdin, which is how a shell
spells the method's path-*or*-text argument; an empty file is refused, because that is
indistinguishable from a typo'd path and a blank card is the thing being repaired.

### `update-module-version`  *(token)*
```bash
registry-client update-module-version NS NAME VERSION SPEC_DIR [--changelog "…"]
```
Fetches the module's current latest, checks `VERSION` supersedes it (SemVer), and publishes. Errors
if the module doesn't exist yet (use `publish`) or `VERSION` isn't greater than latest.

---

## Server admin CLI (`registry`, needs `[server]`)

Not part of the client surface, but for completeness — run **on the server**, against its DB/storage:

```bash
registry serve --host 0.0.0.0 --port 8000
registry init-db
registry issue-key <account> -n <namespace>          # mint an API key
registry revoke-key <key>                            # invalidate a leaked key
registry revoke-account <account> [--yes]            # invalidate all of an account's keys
registry feature <ns> / unfeature <ns>               # curate: float a namespace to the top
registry blacklist <ns> / unblacklist <ns>           # moderate: hide from default listings
registry remove-version <ns> <name> <v> [--yes]      # hard-delete ONE version (not yank)
registry remove-module <ns> <name> [--yes]           # hard-delete a whole module (all versions)
registry remove-namespace <ns> [--yes]               # purge + free the namespace
registry add-member <ns> <acct> --role owner|admin|member    # namespace membership
registry create-org <name>                           # create an org account
registry add-org-member <org> <acct> --role owner|admin|member
registry remove-org-member <org> <acct> / list-org-members <org>
registry set-funding <acct-or-org> <url>             # set/clear a donation link ('' clears)
registry issue-key <acct> --email … --display-name … --avatar-url … --type user|org
registry export-keys [-o auth.json]                  # dump accounts + API keys + namespaces (SECRET)
registry import-keys auth.json                       # restore the auth graph (idempotent)
registry reset-db [--keep-keys|--wipe-keys]          # wipe catalog; keeps keys by default; types RESET
```

`export-keys`/`import-keys` move the **auth graph** (accounts, API keys, namespaces, memberships)
between DBs/environments; the export contains live tokens, so protect it. `reset-db` clears the
catalog projection for a fresh start while keeping your keys (so you don't lock yourself out); it
requires typing `RESET` and does not touch artifact storage. The **signing key** is a PEM file
(`REGISTRY_SIGNING_KEY`), never in the DB — copy it directly to reuse across environments.


---

## Pre-flight: predict a publish before spending one

Three commands, cheapest first.

```bash
registry-client signature spec/ --lookup       # local hash; is this data already published?
registry-client validate  my-ns my-module spec/   # server-side validation, no network
registry-client check     my-ns my-module spec/ --offline   # + the enricher's cross-checks
```

**`signature`** computes the spec's content identity *locally* — no upload, no recompile — using the
same algorithm the registry gates `409 duplicate_content` on. Needs the compiler tier
(`pip install just-dna-registry[compiler]`).

> **The exit code with `--lookup` is the inverse of `find-by-hash`'s.** That command asks "is this
> artifact published?" and fails when it is not. This one is a *pre-publish dedup gate*, so a match
> is the failure: exit 1 means the registry already has this data under some name.

> **A hit under your own module is not a refusal.** `signature --lookup` and
> `is_published(spec_dir)` are name-independent by design — they answer "does this data exist here",
> which is the right question for classifying a corpus. Publishing a *new version of the same module*
> with unchanged data is legal (a review pass: one `authorship` entry, no data touched), so pass
> `is_published(spec_dir, namespace=…, name=…)` when what you want is a verdict; then an empty list
> means free to publish. `validate`/`check` report both lists — see `published_elsewhere` below.

**`validate`** runs the real compiler server-side and returns findings, stats, the content signature,
and any versions already built from identical data. It writes nothing and the module need not exist —
`name` is the name you intend to publish under. It defaults to `--strict`, matching what publish
compiles with; a dry run whose default disagrees with the publish it predicts is a trap.

Its `would_publish_module_level` (0.13) is the branchable field for callers that cannot pay for the
network tier: the publish gates that do not scale with the variant count — validity, the name↔path
match, the dedup claim — composed server-side from the same expression `check` builds `would_publish`
on, so the two cannot drift. **It is not `would_publish`.** `true` means nothing module-level blocks
a publish; a reference mismatch or a withdrawn rsID can still refuse one, and only `check` looks. Its
value is that it has no ceiling and costs no egress, so it answers for panels far too large to check
online, which is the case that motivated it.

Its dedup half reads **`published_elsewhere`** (0.16) — the versions built from identical data under
a *different* `(namespace, name)`, which is what publish refuses. `published_as` still lists every
match including your own earlier versions, and the CLI prints the two differently: `✗` for a
refusal, `·` for "identical data already in this module". Before 0.16 a republish of your own
unchanged data was predicted as a refusal it then was not (S10).

**`check`** adds what only the network tier can see: an authored reference allele against the actual
genome, `clin_sig` against ClinVar, rsIDs dbSNP has merged away, GA4GH allele-identity coverage, and
optionally gnomAD frequencies (`--frequencies`), citations (`--literature`), ACMG SF membership
(`--acmg`) and the PGx nomenclature cross-check (`--pgx`). It exits 0 only when the server says it
`would_publish`.

Two of its answers are about what could *not* be established, and both print as their own line since
0.13. `unreachable_rsids` names rsIDs live Ensembl never answered about — they appear in `unresolved`
too, but an unanswered request is a re-run rather than an authoring fix, so do not go writing
coordinates for a variant on the strength of an unresolved list alone. And `--identifiers` now also
compares each row's `gene` against the chromosome its own variant sits on: a real symbol beside an
invented rsID satisfies every other check, because both halves are true and only the relationship is
false. When that comparison could not run, the report says so instead of coming back empty.

The server's variant ceiling bounds outbound pacing, so it applies to **online** runs only: `--offline`
has no ceiling and answers everything the deployment's snapshots can. Above it an online run is
refused, and the refusal prints the module-level verdict the server computed before stopping rather
than a bare `HTTP 422`.

`--pgx` needs `--use`. Every PGx upstream (PharmVar, CPIC, ClinPGx, ClinGen) is CC BY-SA *plus* a
no-sale clause, so without a declaration each is skipped rather than queried — the registry will not
assert a purpose on your behalf:

```bash
registry-client check my-ns my-module spec/ --pgx --use non-commercial
```

`--use commercial` against those sources is a contradiction and comes back refused, having fetched
nothing. PharmVar is consulted only when the *server* holds a key (it is personal to an account under
their terms §2); otherwise CPIC carries the check and the report says so.

This is the expensive one, and the cost lands on the whole deployment rather than on you: gnomAD is
unauthenticated and rate-limits by IP, with no key available to raise the ceiling, so an overspend
throttles the server for everyone. Pacing is roughly six seconds per twenty variants, so
`--frequencies` on a large module takes minutes. It is the tightest rate
bucket in the service and is additionally capped process-wide. Start with `--offline`, which clamps
to the server's local snapshots and guarantees zero egress, and add passes as you need them.

If the server has no reference snapshot provisioned you get a clear message naming
`registry warm-caches --apply` rather than an opaque 503.

### Admin: 0.11 operator commands

```bash
registry warm-caches --dry-run          # what the running server can read (health check)
registry warm-caches --apply            # provision the snapshots from HuggingFace (slow, large)
registry rederive-signatures --dry-run  # the one-time 0.11 content-hash migration; read the report
registry revalidate --recompile-check   # which modules would a strict publish refuse?
registry upgrade --apply --limit 20     # batch the catalog migration
```

See [UPGRADE.md](UPGRADE.md) for the order these must run in and why.
