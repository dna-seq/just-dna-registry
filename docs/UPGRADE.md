# Contract upgrades & the stale-module procedure

## 0.11.3 trust re-projection (operator note — automatic)

Nothing to run. Starting the server applies `_migrate_0_11_3_trust`, which re-projects the `trusted`
column for versions whose stored value was computed under the pre-0.11.3 rule. It reads
`manifest_json` only — no storage, no network — which is why it is a migration rather than an ops
command, and it is idempotent.

**What visibly changes**: PGx and other table-only modules that previously showed as trusted now show
`false` (the compiler reported a table no VCF can join by position) or `null` (nothing was ever
resolved, so we have no verdict to offer). Nothing is republished and no `artifact.digest` moves —
the manifests were always right, and only our reading of them was wrong. Expect the log line
`0.11.3: re-projected `trusted` for N version(s).` once, then never again.

If a module drops to `false` and you disagree, the fix is authored coordinates in the positional
table (or upstream RM43, which would let the compiler apply `resolution.csv` to those tables) — not a
registry setting. rsid-only identity stays legal and still publishes; the facet is a statement about
joinability, not a gate.

## 0.11 reference caches + content-hash re-signing (operator note)

0.11 adopts format/compiler/enricher **0.5**, and two of its changes need a deliberate act before the
server is correct. Do both in the same maintenance window.

**0. Bump clients to 0.5 first.** The version guard treats a `0.x` minor as a breaking contract
change, so a 0.4 client talking to a 0.5 server is refused. Skipping this makes the first symptom a
blanket publish rejection with no obvious cause.

**1. `registry warm-caches --apply`.** Publish now enriches before it compiles, and with
`REGISTRY_COMPILE_STRICT` on (the default) a server holding no reference snapshot **cannot publish an
rsID-authored module at all** — it refuses rather than emitting a partial artifact. `/check` still
answers `200`, with the shortfall as a note: a snapshot is what makes *offline* resolution possible,
and an online run reaches live Ensembl without one. The dry run (`--dry-run`, the default) reports what the running
server would find, so it doubles as a health check. Already running just-dna-lite on the same host?
Point `JUST_DNA_PIPELINES_CACHE_DIR` at its cache and reuse it.

**2. `registry rederive-signatures --apply`.** 0.11 replaced the registry's own manifest-inputs
Merkle root with the compiler's canonical row-level `content_signature`. The new value cannot be
computed from a manifest — it reads the authored CSVs out of storage — so it is an ops command rather
than a schema migration. Until it runs, versions predating 0.5 carry an empty signature and drop out
of the dedup gate: publishing stays *safe* (nothing false-positives) but is *incomplete* (a genuine
re-list of old data under a new name would not be caught).

Read its report before applying. **Splits** are benign and expected — two modules differing only in
`defaults.curator` used to hash equal, so anything previously refused as `duplicate_content` against
one of them is now publishable. **Merges** are not: they mean two already-published modules will now
be considered duplicates of each other, so the next version of one gets a 409. The command refuses to
apply a merge without `--allow-merges`.

**3. Measure before you tighten.** `registry revalidate --recompile-check` enriches and
strict-compiles every published version exactly as a publish would, and reports `strict_blocked` for
the ones a strict flip would stop accepting. Run it, fix or notify, *then* leave
`REGISTRY_COMPILE_STRICT=true`. Running a migration off `REGISTRY_COMPILE_STRICT=false` is the
supported path in the meantime.

**On the digest re-baseline.** 0.5 moved `variant_key` onto the VRS allele identity, so every module
recompiled under it gets a different `artifact.digest`. This is a one-time, catalog-wide event and it
is not a corruption. `registry upgrade` re-publishes as a new PATCH and never mutates the
predecessor, so old versions stay published and verifiable and a client pinned to one is unaffected;
only a client tracking `latest` sees new bytes, which is what a new PATCH means. Use
`registry upgrade --apply --limit N` to batch it — with enrichment in the loop it is the
longest-running operation the registry has.

## 0.9 default DB path moved (operator note)

The 0.9 `marketplace → registry` rebrand changed the **default** `db_path` from `data/marketplace.db`
to `data/registry.db` (local backend). If you deployed on the default, adopt the existing DB before
starting 0.9:

```bash
mv data/marketplace.db data/registry.db     # or set REGISTRY_DB_PATH=data/marketplace.db (.env.template)
```

The schema itself is migrated **additively in place** the first time `init_db` runs — i.e. on
`registry serve` startup, or `registry init-db` (adds `funding_url`, account `type`, `org_members`,
`versions.published_by`; renames role `contributor→member`). Read-only CLI ops (`export-keys`) now
also run that migration and **refuse a missing/empty DB** (showing the resolved path + the
legacy-`marketplace.db` hint) instead of creating a stray empty file. The server **refuses to boot**
if `registry.db` is absent while a non-empty `marketplace.db` sits beside it (`validate_db_path`).

## 0.9.0 RBAC migration (operator note)

0.9.0 renamed the namespace role `contributor` → `member` (migrated in place by `init_db`) and made
authorization capability-based. **This tightens permissions:** an old `contributor` could
amend/yank *any* version in the namespace; a `member` can only amend/yank versions **it published**
(`versions.published_by`). To restore broad rights for someone, grant them `admin`
(`registry add-member <ns> <account> --role admin`). Also: versions published **before** 0.9.0 have
no recorded author, so only `admin`+ can amend/yank them (fail-closed). Orgs (`type='org'`) now have
members whose role cascades to org-owned namespaces — see the org endpoints/CLI. No artifact or
manifest is affected; this is a DB-projection + authorization change only.

---

`just-dna-registry` pins a `just-dna-format` / `just-dna-compiler` contract version. Bumping it
can tighten a validator (the archetype: `StudyRow.pmid` gaining a `PMID_PATTERN` rule in 0.2.0).
This doc is the agreed procedure for such events, so a contract bump can never silently strand
published modules.

## What is and isn't at risk

A contract bump does **not** break anything already deployed:

- **Published manifests are immutable and stay valid.** They were compiled under the contract in
  force at publish time; `artifact.digest` is unchanged; existing installs keep verifying by digest.
- **Every version self-declares its contract** — `compilation.compiler_version` (e.g.
  `"just-dna-compiler 0.2.0"`) and `schema_version` are in each manifest.
- **Spec inputs are retained** — `module_spec.yaml` / `variants.csv` / `studies.csv` are stored as
  `inputs[]`, so any version can be re-validated on demand.

What *is* at risk: a **re-compile / re-publish** of an old spec under the new server, and **catalog
truth** — knowing which published modules would fail *today's* contract.

## The mechanism

1. **Prefer additive, verbatim-preserving changes.** 0.2.0's PMID rule keeps the original string and
   only rejects references with no PMID token at all (e.g. a bare dbSNP URL, which grounds zero
   studies anyway). Audited against the Gen-I corpus → nothing published was invalidated.
2. **Audit with `registry revalidate`.** It re-runs the *current* `validate_spec` over every
   published version's stored spec inputs and reports `ok` / `upgradable` / `needs_upgrade` /
   `skipped` (spec inputs not retrievable). Published artifacts are never touched.
   - `needs_upgrade` — the spec no longer **validates** (a tightened rule, e.g. the 0.2 PMID pattern).
   - `upgradable` — the spec still validates, but one or more variant rows can be **losslessly
     back-populated** to an *additive* contract (the 0.3 `direction`/`stat_significance`/`clin_sig`
     axes, derived from the legacy `state`/booleans). Optional-but-recommended.
   - `--set-flag` persists a non-destructive `needs_upgrade` flag on both (surfaced in the versions
     API as `needs_upgrade: true`). The version stays fetchable and keeps verifying.
   - `--check-pmids` additionally verifies each study PMID resolves at NCBI E-utilities (the online
     "curl validator"). This is a **registry ops** call — the contract libs stay strictly offline;
     `just-dna-format` only does the cheap regex (`extract_pmids`).
3. **Upgrade a flagged version** by re-publishing, never mutating old bytes:
   - **Additive-column upgrades (0.3) are automated: `registry upgrade`.** It applies the format's
     own `VariantRow.upgraded()` derivation to the stored `variants.csv` (back-populate
     `direction`/`stat_significance`/`clin_sig`, trim `state` to its derived legacy mirror), then
     re-publishes as the next PATCH through the normal server-side compile path. Dry-run by default;
     `--apply` publishes. Scope with `-n`/`-m`. **Only a module's latest non-yanked version is
     upgraded** — the original is immutable and stays drifted, so an older version already superseded
     by a newer one is skipped (and `revalidate` reports it `superseded`, not `upgradable`).
     Idempotent: once the latest is on-contract, re-running does nothing (no endless patch chain).
   - **Schema-only migration is `registry upgrade --force` (aka `--recompile`).** After a contract
     minor that only moves the parquet shape (e.g. 0.3→0.4), an already-on-contract module has no
     back-population to do, so plain `upgrade` skips it. `--force` re-emits the latest in the current
     schema anyway — non-lossy (the authored data is unchanged; only the compiled `artifact.digest`
     moves). Use it to bring a whole catalog onto the new parquet shape for 0.4 consumers.
   - **Columns/keys the new contract rejects need `--trim` (LOSSY, so `--force`-gated).** 0.4 made
     the row models *and* the `module_spec.yaml` blocks (`module:`/`defaults:`/`panel:`/`authorship:`
     + top level) `extra="forbid"`; older lax schemas only *warned* on an unknown column/key, so a
     pre-0.4 `variants.csv`/`studies.csv`/`module_spec.yaml` can carry one a 0.4 compile now rejects.
     Without `--trim` such a version is reported **blocked** (never crashes the planner);
     `registry upgrade --trim --force` drops the offending columns/keys so the spec compiles. It
     discards data, hence opt-in and manual. (The registry-owned `module.version` etc. are not
     trimmed — the always-on strip handles them non-lossily.)
   - **Validator-failure upgrades** stay a manual transform + publish: apply the fix to the spec
     inputs (for PMID: `extract_pmids` → digit-only; drop or fix references that don't resolve
     online), then `registry-client publish … <new PATCH version>` under the new contract.
   - Either way the predecessor stays fetchable (existing installs keep working); yank it once the
     successor is live if you want it out of `latest`/listings.
4. **Out-of-digest assets never trigger this.** `logs`, `provenance`, and `logo` are hashed but
   excluded from `artifact.digest`; a logo change is a PATCH via `amend-logo`, not a re-publish.
5. **Registry-owned keys are normalized, not a drift class (0.4).** 0.4 made the `module:` block
   `extra="forbid"`, which would otherwise reject the `module.version` (and `namespace`/`owner`/
   `canonical_id`) that every pre-0.4 spec archive carried — keys the registry fills itself. The
   server strips that registry-owned set from the authored `module_spec.yaml` before validate/compile
   on every path (publish, import, upgrade) and before the `revalidate` check
   (`strip_registry_owned_keys`), so a legacy `module.version` alone reads as `ok`, not
   `needs_upgrade`, and the pre-0.4 corpus imports/upgrades cleanly. This is a permanent, contract-
   independent normalization (the registry is the identity authority), not a per-bump migration step.

## Boundary: where the network lives

The contract libraries (`just-dna-format`, `just-dna-compiler`) are a stated no-network zone. So:

- **Regex validation** (does the string carry a PMID token?) → `just-dna-format` (`PMID_PATTERN` /
  `extract_pmids`).
- **Existence verification** (does the PMID resolve at NCBI?) → registry ops
  (`services/pmid_check.verify_pmids`, reached via `revalidate --check-pmids`) or the authoring tier.
