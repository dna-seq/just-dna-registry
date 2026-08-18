# Contract upgrades & the stale-module procedure

## 0.17 format 0.6 adoption (operator note — a coordinated cut)

**This is the second contract cut, and it has the same shape as 0.11's.** `just-dna-format` and
`just-dna-compiler` move to **0.6.1** and `just-dna-enricher` to **0.6.2**, `artifact.digest` moves on
every module, and `version.contract_compatible` treats a `0.x` minor as breaking — so a 0.5 client talking
to a 0.6 server is **refused**, and the first symptom of skipping step 0 is a blanket publish
rejection with no obvious cause.

**The enricher runs ahead of the other two, and that is not a typo.** 0.6.2 and 0.6.3 are both
enricher-only cuts (upstream RM101, then S39/S41–S44); format and compiler are unchanged at 0.6.1, so
`uv sync` installs `0.6.1 / 0.6.1 / 0.6.3` as of registry 0.18.1, and that is the correct state. The
enricher floor is a hard one rather than a preference: this server's `/check` adapters catch the
unavailability subclasses 0.6.2 introduces, and on 0.6.1 nothing raises them — those handlers would be
dead code and an upstream outage would go back to being a `500`.

**Nothing in this document changes for 0.6.3, and that is the point of saying so.** It moves no schema,
no signature and no digest, so an operator already on 0.6.1/0.6.1/0.6.2 upgrades by `uv sync` and stops
— there is no revalidate and no re-baseline to run. In particular, upstream's note that ClinVar-drafted
modules published before 0.6.3 need a **re-draft** is not a job for step 2 below: drafting happens where
the spec is authored, this registry has no drafter, and recompiling an already-drafted `variants.csv`
reproduces exactly the rows the drafter dropped. Those modules need a new upload from their publisher.

**Install `0.6.1`, never `0.6.0`.** Upstream cut 0.6.0 on 2026-08-17 and 0.6.1 the next day with eight
defects fixed; this repo's floors name `0.6.1` and `uv sync` will refuse the older one. It changes no
schema surface, so nothing in the sequence below moves — the reason it is a hard floor rather than a
preference is that one of the eight (RM95) let a non-vocabulary `measure_kind` spelling into
`content_signature`, and a signature is the one thing here that cannot be taken back: it claims a
global `409 duplicate_content` slot that only a purge frees. Two others land on this service's own
endpoints; `docs/CHANGELOG.md` § 0.17 names all four.

Do the whole sequence in one maintenance window. It is shorter than 0.11's, and the reason is worth
knowing before you start: **`content_signature` does not move.** Upstream measured 0/11 over the
reference corpus and this repo's suite checks the consequence. So there is **no `rederive-signatures`
step**, no risk of merged dedup claims, and no version loses its `409 duplicate_content` slot.

**Every command below takes `--mode`, and on the polygon you must pass it (0.17.1).** A deployment
sets `REGISTRY_MODE` in its unit file or compose env, which the server process inherits and your shell
does not — so `registry upgrade` run by hand on the polygon applies *production's* rules to the test
box's catalog. Spell it: `registry --mode test upgrade --apply`. The flag goes before the
subcommand, and `revalidate`/`upgrade` echo `mode=… db=…` up front so a wrong one is visible before it
refuses anything. On production the default is already right and the flag is optional.

**0. Bump clients to 0.6 first.** Same rule as 0.11, same failure if skipped.

**1. `registry revalidate --recompile-check` — before anything else, and read the report.**
This is the step that is new in kind rather than a repeat. 0.6 tightens two checks that can refuse a
spec which published perfectly well at 0.5.4:

- **RM50** — a `PMC ` id in a `pmid` cell. `PMC 3110566` used to be accepted as PMID 3110566, which
  is a real id for an unrelated article.
- **RM48** — a wrong-build coordinate: a position past its contig's end, or a contig only the other
  assembly names. It is arithmetic rather than judgement, so it is an error in **both** modes and
  `--strict` is not the switch that turns it off.

Neither fired on the upstream corpus, but neither had to: the point is that your catalog is not that
corpus. A version that fails here cannot be recompiled by step 2, so find them now and notify their
publishers, rather than discovering it a third of the way through a catalog-wide sweep.
`just-dna-enricher hint recover` reports which rs-number GRCh37 dbSNP records at a coordinate, which
is the diagnostic for an RM48 refusal.

**2. `registry upgrade --apply --limit N` — the digest re-baseline.** Every module recompiled
under 0.6 gets a different `artifact.digest`, exactly as 0.5 did to 0.4. This is a one-time,
catalog-wide event and it is not corruption: `upgrade` re-publishes as a new PATCH and never mutates
the predecessor, so old versions stay published and verifiable and a client pinned to one is
unaffected. Only a client tracking `latest` sees new bytes, which is what a new PATCH means. With
enrichment in the loop this is still the longest-running operation the registry has — batch it.

**`--force` is no longer needed here, and the history of this line is worth two minutes (0.18.0).**
It first read `--apply` alone; driving the real `v0.5.4` reference corpus showed **five of eleven**
skipped as no-ops (`apoe_epsilon`, `cyp2c19_star_alleles`, `hfe_compound_het`, `htt_repeat_expansion`,
`slco1b1_simvastatin`) with their digests still on the 0.5 parquet shape, so the line was corrected to
`--apply --force`. That was the wrong repair: the tool could not see a gap it had everything it needed
to compute, and the fix belonged in the tool. `upgrade` now compares each version's
`compilation.compiler_version` stamp against the installed compiler, under the same rule that refuses a
0.5 client on a 0.6 server — so a stale parquet is found the way a stale client is, and those five
upgrade under plain `--apply`.

What `--force` means now is what its name says: recompile where there is **no** detectable gap. Two
cases. A version already on this contract (you are re-emitting for some other reason). And a version
whose compiler cannot be identified — a foreign `compiled_by`, or a stamp the compiler wrote as
`unknown`. Those are **counted and named** in the summary rather than silently skipped, because
"unidentifiable" and "up to date" are the same silence otherwise, and that silence is what made this
step wrong for two releases. Aim `--force -m <module>` at them once you know what they are.

A compiler **patch** difference is deliberately not a gap: it moves no schema, so acting on it would
mint a new PATCH per module to record a dependency bump, and the next upstream patch would start the
sweep over. `--force` is the switch for that too, if you ever want it.

This is the same distinction § "Upgrading a stale module" draws between an additive-column upgrade and
a schema-only migration; 0.6 needs the second for the whole catalog and the first for whatever
`revalidate` also flagged. Both are now detected, so one command does both.

**And back-population *does* move `content_signature`, which is not a contradiction of §0's promise.**
0.6 moves no signature — measured 0/11 upstream, and 0/11 again here through this registry's own
publish path. What moves one is the **0.3** back-population that `upgrade` applies on the way past: it
rewrites authored cells (`direction`/`stat_significance`/`clin_sig` derived from the legacy
`state`/booleans), and rewritten authored data is by definition new content. Six of the eleven are in
that state, carrying 2 to 328 upgradable rows each. Two consequences worth knowing before you start:

- The successor claims a **new** `409 duplicate_content` slot; the predecessor keeps its own. Nothing
  is lost and nothing is merged, but a re-publish of the *original* data under another name is still
  claimed by the version that already holds it.
- A consumer keying on `content_signature` to mean "same authored data" sees the upgraded version as
  different data, correctly — the cells really did change. This is why the migration is a new PATCH
  rather than an in-place fix.

**What you do *not* have to run, and why.**

- **No `rederive-signatures`.** *The contract* moved no `content_signature` — measured 0/11 upstream and
  0/11 again through this registry's publish path. Running it anyway is not harmful, but it is a long
  read of every stored spec to confirm nothing changed. Note this is a different statement from step 2's:
  the **0.3 back-population** does move a signature on the six corpus modules that carry legacy
  `state`/boolean cells, because it rewrites authored data. `rederive-signatures` recomputes a signature
  from unchanged bytes; `upgrade` changes the bytes. Neither is the other's substitute.
- **No trust migration**, unlike 0.11.3. The trust rule *did* change — it reads RM44's counts now
  instead of matching warning prose — but only for manifests that carry the new counters, and no
  version already in your catalog does. The pre-0.6 branch is the 0.5 rule unchanged, asserted
  exhaustively over the 24-shape pre-0.6 space in `tests/test_format_06.py`. Stored verdicts move
  only as step 2 recompiles versions.
- The schema migration (new fact-table columns) runs itself on first `init_db`, i.e. on
  `registry serve` startup. It reads `manifest_json` only and backfills every existing row to "no
  such table", which is honest rather than a downgrade: `gwas_effects.csv` did not exist when those
  modules were compiled.

**What visibly changes after step 2.** Expect these and do not treat them as regressions:

- **Some PGx modules flip from `trusted: false` to `true`.** Compiler RM43 ships a positional fill:
  rsID-keyed rows in `haplotypes.csv`/`pharm_variants.csv`/`heteroplasmy.csv` now take coordinates
  from `resolution.csv`, so tables that joined to no VCF now join. The reference CPIC example goes
  from 0 of 106 rows placed to 106 of 106. Nothing about those modules changed; the compiler learned
  to do what the warning had been complaining about.
- **`resolution_subjects` and the positional counters appear** on `/modules` and version lists. On a
  version compiled before 0.6 they are `null`, which means *not measured* and is **not** `0`.
- **`licensing.csv` becomes the stored spelling** of the licence ledger. An upload under either name
  keeps working; `sources.csv` is renamed on the way in, because 0.6 deprecates it for removal at
  format 1.0 and a published manifest is immutable — left alone, every publish would carry a
  deprecation warning forever. A spec carrying **both** spellings is now refused (`422`) instead of
  preferring one, because the 0.6 compiler raises on the collision rather than picking.
- **The readme and the machine-written sidecars are downloadable**, since format 0.6 attests them
  (`manifest.readme`, `manifest.derived`). `/files/{path}` and the tarball serve what the manifest
  records, so this needed no change to the guard — and `download(include_inputs=True)` now returns a
  module that recompiles where it lands.

**If a publisher asks why their module suddenly warns about a closure**: 0.6 warns when a spec
records none (`just-dna-compiler close`). It is a warning in 0.6 and a gate only at 1.0. It does not
block a publish and there is nothing for an operator to configure.

## 0.12 deployment modes (operator note)

**Existing production deployments need no change.** `REGISTRY_MODE` defaults to `prod`, and that is the
strict side: production refuses `test-`prefixed data and serves no delete verb. An unrecognised value
refuses to boot rather than guessing.

**Standing up the polygon** (`module-polygon.just-dna.life`): same image, `REGISTRY_MODE=test`, its **own**
`REGISTRY_DB_PATH` and artifact storage — never production's. It listens on **8100** by default (prod
8000), a hundred apart so a misdirected client is refused rather than answered by the wrong catalog.
`registry serve` prints the mode and, on a polygon, the three behaviours that differ.

What the polygon does differently, and nothing else does: it accepts test-prefixed data, scopes
`409 duplicate_content` to the publishing account, and serves `DELETE` on modules and versions
(authenticated, namespace-scoped). Note the deliberate consequence — a polygon run cannot prove a
*cross-account* duplicate would be refused on production.

**Cleaning historical test data from production.** The new guard is prospective only: it refuses new
test-prefixed publishes and does nothing about what is already in the catalog. Stop the server and run
`registry purge-test-data` (a dry run) first, read the plan, then `--apply`. A prefix-matching module
sitting in a *production* namespace is reported and skipped — it may be a real published module — and
`--include-prod-namespaces` is the explicit opt-in. A production version authored by a purged account is
kept and only loses its `published_by` pointer.

**Backups now happen on their own.** Every destructive command snapshots the DB first, to
`backups/registry-NNNNN-<utc>-<reason>.db` beside the DB (`REGISTRY_BACKUP_DIR` to move them). The index
only counts up and never overwrites, so snapshots accumulate — put them somewhere with room, and prune
deliberately. `registry list-backups` / `restore-backup`. A snapshot is the **index, not the artifacts**:
restoring past a purge that removed artifact bytes gives rows pointing at storage keys that are gone.

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
  `"just-dna-compiler 0.2.0"`) and `schema_version` are in each manifest. Since 0.18.0 `upgrade` reads
  that first field rather than asking an operator whether a re-baseline is due; this line was already
  true when the detector was a one-era landmark test, which is what makes the old version of it a
  missed opportunity rather than a missing capability.
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
   - **Schema-only migration is plain `registry upgrade` too, since 0.18.0.** After a contract minor
     that only moves the parquet shape (e.g. 0.3→0.4), an already-on-contract module has no
     back-population to do — but it *does* have a stale parquet, and the planner now sees that by
     comparing the version's `compilation.compiler_version` stamp against the installed compiler. So
     one command brings a whole catalog onto the new shape; it is non-lossy (the authored data is
     unchanged, only the compiled `artifact.digest` moves) and it is idempotent, because a version this
     server compiled is not a gap. `--force` (aka `--recompile`) remains for the two cases no
     comparison can settle: a version already on this contract that you want re-emitted anyway, and one
     whose compiler cannot be identified — those are counted and named in the summary rather than
     skipped in silence.
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
