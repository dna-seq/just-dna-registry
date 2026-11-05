# Upstream ledger: the compiler's three packages

`just-dna-format`, `just-dna-compiler` and `just-dna-enricher`, released together from
`dna-seq/just-dna-compiler` with tags `vX.Y.Z` (the tag names the cut; each package carries its own version).
Kept by the liaison seat (`docs/seats/LIAISON.md`); another seat that meets a symptom in these packages sends it
there rather than writing here.

Watched on this machine from a clone outside the repository, `/data/sources/just-dna-compiler` (its line in the
liaison state file): `[seat.liaison.watch.compiler]` says each new tag, `[seat.liaison.watch.compiler-next]` each
commit to `docs/CHANGELOG.md` on the coming minor's branch (`0.8` today).

## Read mark

**`v0.7.3`**: format 0.7.1, compiler 0.7.2, enricher 0.7.3, the trio `uv.lock` installs (registry 0.27.0, floors
in `pyproject.toml` with their reasons). Upstream has cut nothing since.

## Backlog

- **The 0.7.0 cut, read for levers.** 0.7 was adopted for what broke us (CLAUDE.md records each), not read for
  what it fixed of ours. C1 to C3, C5 and C6 come from the entries answering the registry's own filings; the
  rest gave C7 to C15 (second slice, 2026-11-04); 0.7.1 to 0.7.3 gave C16 to C19 (2026-11-05). Everything up
  to the read mark is read.
- **`main` past `v0.7.3`** (168 commits on 2026-11-04): patch entries marked "patch, on `main`" (RM339, RM340,
  RM338, RM347, RM353, RM355, RM354 at the top). A `v0.7.4` would carry them. Read when it is tagged, or earlier
  if one touches a symbol below.
- **The `0.8` branch** (197 commits past `main`, head `0a5293b`): the coming minor. First-pass adoption map
  below; read again at each `docs/CHANGELOG.md` commit the `compiler-next` watcher reports, and whole at the cut.

## What the registry uses

From the module-level and lazy imports under `src/` (an AST walk, 2026-11-04). A release is read against this
list; a symbol that moves here is a change to read whole.

### just-dna-format

- `manifest`: `ModuleManifest`, `Contribution`, `FileEntry`, `GenePanelSpec`, `LOGO_EXTENSIONS`,
  `MARKETPLACE_COMPILED_BY`, `read_manifest`, `write_manifest`. Fifteen files: the catalog, publish, ingest,
  rebuild, revalidate, upgrade, facets, the client.
- `identity`: `canonical_id`, `is_valid_namespace`, `is_valid_version`, `latest`, `parse_version`.
- `integrity`: `sha256_bytes`, `verify_manifest` (client, publish).
- `signing`: `sign_digest`, `public_key_b64_from_pem`.
- `layout`: `DERIVED_SUBDIR`, `LICENSING_CSV`, `SOURCES_CSV`, `VERIFICATION_JSON`, `SIDECAR_SPELLINGS`,
  `is_deprecated_spelling`, `preferred_spelling`, `sidecar_spellings` (`specfiles.py`, `services/upgrade.py`).
- `normalize`: `IDENTITY_AUTHORITY_KEYS`, `PRESENTATION_AUTHORITY_KEYS`.
- `release_records`: `DeclaredChange`, `RECOMPILE_DRIVING_AXES`, `needs_recompile`, `parse_version`
  (`services/rebuild.py`, `services/enrich.py`).
- `vocab`: `TEMPLATE_PLACEHOLDER`, `VALID_DECLARED_USE`.
- `spec`: `Defaults`, `ModuleInfo`, `ModuleSpecConfig`, `StudyRow`, `VariantRow`, `extract_pmids`.
- Row models, all in `services/upgrade.py`: `assertions.ClinicalAssertionRow`, `binning.{ActivityPhenotypeRow,
  CopyNumberRow, HeteroplasmyRow, RepeatAlleleRow}`, `frequency.FrequencyRow`, `gene_metrics.GeneMetricsRow`,
  `gene_validity.GeneValidityRow`, `gwas.GwasEffectRow`, `literature.LiteratureRow`, `pgs.PgsRow`,
  `pgx.{AlleleFunctionRow, DiplotypeRow, HaplotypeRow, PharmVariantRow}`, `sources.SourceRow`.

### just-dna-compiler

- `compiler`: `compile_module`, `validate_spec`, `content_signature`, `module_stats`, `spec_tables`,
  `reverse_module`, `UNJOINABLE_PHRASE` (publish, revalidate, rebuild, signatures, facets, enrich, the client).

### just-dna-enricher

Imported lazily inside functions (CONSTITUTION Principle 2; a test holds the boundary).

- `enrich`: `enrich`, `EnrichmentError`; `ensembl.EnsemblResolver`, `grch37.Grch37Client`.
- The check passes and their errors, each caught subclass-first (CLAUDE.md, "Catch the unavailability subclass
  above its parent"): `acmg.{verify_acmg_sf, AcmgReport, AcmgSfError, AcmgListUnavailable}`,
  `clingen.{enrich_dosage_sensitivity, ClinGenError, ClinGenUnavailable}`, `clinpgx.{enrich_clinpgx,
  ClinPgxEnrichmentError}`, `cpic.CpicError`, `frequencies.{enrich_frequencies, FrequencyEnrichmentError,
  FrequencyUnavailable}`, `identifiers.{check_identifiers, IdentifierCheckError, IdentifierUnavailable,
  OntologyClient}`, `literature.{enrich_literature, LiteratureEnrichmentError, LiteratureUnavailable,
  CrossrefClient, EuropePmcClient, PmcIdConverterClient}`, `pgx.{enrich_pgx, PgxEnrichmentError}`,
  `pharmvar.PharmVarError`, `licensing.{check_declared_use, LicenseRefusal}`.
- Clients: `gnomad.GnomadClient`, `eutils.EutilsClient`; `lookup.{LookupClients, lookup_variant, lookup_gene,
  lookup_trait, lookup_citation, lookup_old_assembly}` (`services/enrich.py`, `services/hints.py`).
- Drafters (`services/drafting.py`): `clinvar_draft.{draft_gene_panel, DEFAULT_CLIN_SIG}`,
  `civic_draft.draft_panel_from_civic`, `clinpgx_draft.draft_pharm_variants`, `mitomap_draft.
  draft_panel_from_mitomap_miss`, `pgx_draft.draft_gene`, `pubmind_draft.draft_gene_panel_from_pubmind`,
  `strchive_draft.draft_repeat_loci`.
- Caches: `caches.{CACHE_LANES, prepare_caches, rebuild_lane, RebuildRequest}`, `locations.{read_release,
  RELEASE_FILENAME}`; `transaction.STAGING_SUFFIX` (publish).

## Verdicts

Each open item is the lead's to build; its state is said beside it.

- **C1 — S90 / RM201 shipped in 0.7.0 and we do not read it. *Fixed what we worked around.*** `DeclaredChange`
  gained `requires` (the manifest paths a module must carry for a change to reach it; `()` every module, `None`
  unknown). `services/rebuild.py:224,322` read `target`, `item` and `axis` and never `requires`, so a declared
  correction still reaches every module and a sweep over-reaches, bounded at one PATCH per module (CLAUDE.md,
  "a declared change says what a release did, never which artifacts"). That paragraph and CLAUDE.md:132 still
  say "filed upstream as S90", which upstream answered on 2026-09-11. Fix: filter `declared_movement` by
  `requires` against the manifest, `None` keeping today's behaviour; correct both texts. About an hour with
  tests. Sent to the lead 2026-11-04.
- **C2 — S92 / RM206 shipped in 0.7.0. *A piece of ours the upstream now does.*** `LookupClients.ensure(name,
  factory)` makes every leg's lazy build one path under a lock; `close()` walks `CLIENT_FIELDS`.
  `services/enrich.py:226` `shared_lookup_clients()` still constructs all eight eagerly, and CLAUDE.md
  ("It said 'six' until 0.25 ... Filed upstream as the real fix") describes an upstream that no longer exists.
  Ours is not wrong, only redundant: eager costs eight connections on the first online run. Fix: hand over an
  empty shared bundle and let `ensure` fill it, keep one test that a leg's client is reused across two calls;
  rewrite the CLAUDE.md paragraph. About an hour. Low priority. Sent to the lead 2026-11-04.
- **C3 — S81 / RM146 shipped in 0.7.0. *A lever to weigh.*** Every authored field carries `since(...)`, read back
  by `base.field_first_seen(model)`. `version.schema_gap_advisory` (`version.py:121`) still cannot say which
  release introduced a refused column, and CLAUDE.md says that "needs an input-side roster from upstream (S81)".
  The catch: the server runs the *older* format, so it cannot look up a column it does not know; only the newer
  side can. The lever is in `registry-client` (it holds the newer models) or in the advice text. Weigh before
  building; no estimate yet. Sent to the lead 2026-11-04 as a question, not a task.
- **C4 — `services/upgrade.py:188` `_ROW_MODELS` is already stale on 0.7. *Breaks us, quietly.*** It lists
  the table kinds and six fact sidecars, and lacks four tables 0.7.3 reads with `extra="forbid"` models:
  `overrides.csv` (in `_INPUT_FILES`), `expression_effects.csv`, `clin_sig_concordance.csv` and
  `clin_sig_authority_calls.csv` (in `_FACT_TABLES`). An unknown column in one of them is neither trimmed nor
  reported blocked by `registry upgrade`, and fails the recompile instead, which is the 0.10 failure the
  roster's own comment describes. 0.8 adds six more (M2 below). Fix: derive the roster from upstream's
  (`_TABLE_KINDS` and `_FACT_TABLES` carry the model beside each CSV; 0.8 adds the public
  `AUTHORED_NON_KIND_TABLES`) with a denominator floor, as `tests/test_specfiles.py` already ties back the
  file lists. About an hour. Sent to the lead 2026-11-04.

- **C5 — S91 / RM204 shipped in 0.7.0. *A piece of ours the upstream now does.*** `caches.lane_status(lanes)`
  returns one `LaneStatus` per lane (`state`, `looked_in`, `path`, `release`, `release_unreadable`,
  `size_bytes`), with `occupied` for what we call `partial`. `services/enrich.py` `lane_status(settings)` (read by
  `api/routers/caches.py:65`) still runs its own loop over `lane_presence`. Ours adds what upstream's cannot: the
  `declared_use` licence skip and no path in the response. Fix: compose upstream's and keep those two; one
  vocabulary for the third state. About two hours. Low priority. Sent to the lead 2026-11-04.
- **C6 — S95 / RM203 shipped in 0.7.0. *Fixed what we worked around, partly.*** `PacingGate.spent` counts the
  upstream attempts a gate admitted. `pacing.py:291-296` still says "nothing downstream reports what it actually
  spent (filed upstream as S92)", which is no longer true and names the wrong filing (S95). The design under it,
  charging before the call so the meter can refuse, stands on its own reasons. Fix: correct the docstring; whether
  to reconcile the meter from `spent` is the lead's call. Minutes for the text. Sent to the lead 2026-11-04.

The second slice (2026-11-04): the 57 entries of 0.7.0 read by a helper against the use list; each item below
re-checked against the code and the installed packages before it was written.

- **C7 — RM134 §B, RM170: `enrich()` takes `pubmind_cache=` and `civic_cache=`, and we pass neither. *Breaks
  us.*** Both `enrich()` calls (`services/enrich.py:893`, `:1334`) pass `ensembl_cache` and `clinvar_cache` only,
  though `configured_caches` holds both lanes (`:350`, `:354`). The server never runs `export_lane_locations`
  (only `cli.py:1128`, inside `warm-caches`), so `None` licenses ambient discovery, which CLAUDE.md's "always pass
  the configured cache path" forbids, and what it finds feeds `published_refutation` and the
  `evidence_status_currency` check into `verification.json`. Fix: pass both, one test. Half an hour.
- **C8 — RM155, RM156, RM163: `check_identifiers` reads every table that carries the columns, and checks PGS
  accessions. *Breaks us.*** `services/enrich.py:1627` returns "no variants.csv … nothing to check" before
  calling it, so a PGx-only module gets that answer from `/check`. `IdentifierReport` gained
  `trait_tables_not_read`, `gene_tables_not_read`, `pgs`, `pgs_not_checked` (and their `*_read` siblings), which
  the adapter does not carry ("a pass that could not run reports why"). The PGS leg (`check_pgs=True` by default)
  builds its own `PgsCatalogClient`, outside the shared bundle and `pacing.UPSTREAMS`; and `write=True` by
  default merges licence rows into the scratch spec. Fix: drop the early return, carry the fields, decide
  `check_pgs` (off, or a paced client) and `write=False`. Two to three hours with the models and renderers.
- **C9 — RM85: `verify_datasets=True` is `enrich()`'s default, and we never set it.** It probes ClinVar's live
  VCF header and the PGS Catalog's `/rest/info` at the end of every run, through clients outside the shared bundle
  and the pace ledger; offline it records the check unchecked. `config.py` has `enrich_verify_clinsig` (`:124`)
  and nothing for this. Fix: a setting, passed through (and `release_probes=`). About an hour.
- **C10 — RM154: `EnrichmentResult.allele_mismatches` (the source answered, the allele did not match, typically
  a strand flip). *A lever.*** Nothing here reads it, and `unresolved_hint` (`services/enrich.py:954`) offers
  three remedies that are all wrong for that case; CLAUDE.md says to check that hint before adding a fourth
  remedy. One to two hours with the models and the console.
- **C11 — RM218 (with RM141, RM143): a premise in our comments no longer holds.** `services/enrich.py:1253`
  and `:1292` (and CLAUDE.md, "the dry run grades where the publish grades") say strictness changes severity
  only; upstream's strict validate adds an aggregate finding of its own. The verdict holds, because
  `_would_publish` also requires `validation.valid`. Open for the lead: whether a strict refusal over a recorded
  wrong-build finding should leave `would_publish_module_level` true, as it does. Twenty minutes for the text.
  The lead decided 2026-11-04: it should flip it, once a code says which finding it is; filed upstream as S129.
- **C12 — RM132: `PharmVariantRow.pmid`, and `compiler.load_citing_rows` / `table_citations` walk every citing
  table. *A piece of ours the upstream now does.*** `services/revalidate.py:133` `gather_pmids` reads
  `studies.csv` only, so `revalidate --check-pmids` misses PMIDs in `pharm_variants.csv` and the binning
  kinds. About an hour.
- **C13 — RM158: `enrich.collect_subjects` is public.** `services/enrich.py:720` mirrors its table list "rather
  than imported because it is private there". The three tables still match. An hour; low.
- **C14 — RM138: upstream recommends serving manifests compressed** (`carried` makes them 1.84× raw, 1.06×
  gzipped). `api/app.py` adds no GZip middleware; the deployment's proxy may compress already, which this repo
  cannot show. Fifteen minutes once that is known; low confidence.
- **C15 — RM229: `CacheLane.approx_mb` and `provisioning_closure(lane)` say what a pull costs.** `GET /caches`
  names a lane's parents, not its cost (`services/enrich.py:653`). An hour; folds into C5.

Read, nothing for us, or already adopted (CLAUDE.md records it): the other 46 entries, listed by RM number in
the helper's report of 2026-11-04 (RM70 to RM235).

The third slice (2026-11-05): 0.7.1 to 0.7.3, 38 entries, read by a helper; each item re-checked.

- **C16 — RM268 (v0.7.3): an online REST indel whose reference base could not be read gets no position, and the
  enricher names it only in a log line. *Breaks us, quietly.*** Installed `enrich.py:1080` keeps
  `unanchored_rsids` local; they land in `unresolved` (`:1493`) and a log warning ending "Re-run with the
  sequence service reachable" (`:2082`), never on `EnrichmentResult` (RM272 puts them there in 0.8, M4). Our
  `unresolved_hint` (`services/enrich.py:979`) checks only `unreachable_rsids`, so this case falls through to
  "provision a fuller snapshot … or author chrom/start", sending a publisher after an outage; the server keeps
  no enricher log. `pyproject.toml:300` says 0.7.3 reaches us "through routes that already pass results through",
  false for this case. Fix now: the third branch's text says a withheld indel is possible and to re-run first
  (twenty minutes); the structural fix waits for RM272.
- **C17 — RM252 / S105 (0.7.1): with no `declared_use`, the PGx legs read the module's own recorded declaration,
  and `PgxResult.recorded_use` says where each came from. *A lever.*** `/check` inherits the behaviour
  (`config.py:208` defaults to `"unstated"`) but reports none of it: `client_cli.py:1226` prints
  `declared_use=unstated` beside a CPIC leg that ran, upstream's own S105 symptom in our renderer, and
  `recorded_use` is never read. Fix: the field in `models/api.py` and `console/src/types.ts`, both renderers. An
  hour.
- **C18 — RM268/RM271's remedy is `enrich --rederive`; an uploaded pre-0.7.3 `resolution.csv` keeps its old rows.
  *A lever to weigh.*** Neither `enrich()` call passes `rederive`, and `EnrichmentResult.rederived` is never read,
  so `/check` cannot show that drift. Rederiving re-asks every subject, which spends egress on an unprovisioned
  box. Two hours; weigh first.
- **C19 — RM299 (unreleased, on their `main`): the `stats` ClinVar counts gain descriptions.** Our
  `models/api.py:21` `pathogenic_count` (and `clinvar_count`, `benign_count`) carry none in the OpenAPI schema,
  S123's misreading. Fifteen minutes once the patch is tagged. RM274 also makes C10 (`allele_mismatches`) fire
  more often.

The 0.7.0 cut read for levers, first slice (2026-11-04): the two entries answering the registry's own filings
(S88/S89 on 2026-09-03, both adopted: `lane.env_var` at `services/enrich.py:683`, `needs_recompile` with an
unstamped compiler; S91-S95 on 2026-09-11, giving C5 and C6). The rest of 0.7.0 is unread for this purpose.

State of C5 to C15, 2026-11-04 (lead, b7cc45b): all filed; C7, C4, C9 (setting, default off) and C8's patch half
lead the 0.27.x patches; C8's fields wait for 0.28; C6 no reconcile from `spent`, the text only; C14 canceled,
both boxes already gzip at the proxy.

State, 2026-11-04: the lead filed C4, C1 and C2 on `docs/ROADMAP.md` (fcd2589, cd4c511; "Next registry version",
unattended patches in that order), with the 0.8 map's M2 folded into C4's derivation. C3 was folded into the
roadmap's older column-release entry, now unattended too (f96eca4).

## The coming minor: format 0.8 (adoption map, first pass, 2026-11-04)

For the lead and the pm, for `format-0.8-adoption`. Read from the `0.8` branch at `0a5293b`, rows M8 to M11 at `503730c`: upstream's
`docs/INTEGRATION_0_8.md` (its consumer guide, which names this repository), the source diff `v0.7.3..0.8` of
what the registry imports, and the changelog's 49 entries marked "0.8, uncut". **Everything here is moving**:
every entry is dated 2026-11-04, the longevitymap v2 group (RM322 to RM336) is still being built, and nothing is
installable. A probe of the registry's tests against the 0.8 packages was not run (the client's auto mode
refused to install unpublished upstream code); every finding below is from reading.

What did not move: all 117 names `src/` imports from the three packages still exist on `0.8` (an AST check,
anchored on all 117 resolving on `v0.7.3`). `compiler.py` became a package (RM260) and re-exports every name,
the private `_FACT_TABLES`, `_INPUT_FILES`, `_TABLE_KIND_CSVS`, `_PROVENANCE_FILE` the tests tie back to
included. No test here monkeypatches the compiler module, so RM260's "patch the submodule" note reaches nothing.

Hardest first.

| # | What changes | Where it lands here | Fix and cost | Still moving |
|---|---|---|---|---|
| M1 | **The lockstep cut.** A 0.7 `just-dna-format` refuses 0.8 output in five places: every `verification.json` and manifest `verification` block a 0.8 enricher writes (RM292 adds four fields to `extra="forbid"` `VerificationRecord`), a 0.8-enriched `resolution.csv` (RM267's two columns), new `warnings_summary` codes (closed `VALID_WARNING_CODES`), `pmid=NONE` and the new `doi` columns (RM336), and a serialized `DeclaredChange` with `kind: toolchain` (RM352). Server, `registry-client` and the console move together; `version.contract_compatible` already refuses a mixed pair. | Floors `pyproject.toml:72` (format), `:119`, `:308-309` (compiler, enricher); `uv.lock`; `docs/UPGRADE.md`; CLAUDE.md's floor reasons. | A coordinated cut, as 0.7's was. About half a day with the 25-minute suite and the operator procedure. | The floors cannot be written yet: on the branch the format says 0.8.0 but the compiler is still 0.7.2 and the enricher 0.7.3. The compiler's lead, 2026-11-04 ~20:40 UTC: the cut sets all three to 0.8.0 with `>=0.8.0` floors, writes the 0.8.0 release record and finishes `INTEGRATION_0_8.md`, after the round-1 audit fixes, audit round 2, a release-gate sweep and a docs pass; "5-8 hours from now" (withdrawn 2026-11-05: the cut waits on named items, no time promised). |
| M2 | **Six new tables.** Authored and inside `content_signature`: `meta.csv` (RM28, RM323, RM324) and `model_organisms.csv` (RM335), registered in the new public `compiler.AUTHORED_NON_KIND_TABLES` beside `overrides.csv`. Derived fact tables, outside the signature: `locus_to_gene.csv`, `colocalisations.csv` (RM333), `consequences.csv` (RM236), `ld_pairs.csv` (RM331). Disjointness holds: none of the four derived ones is in `_INPUT_FILES`. | `specfiles.py` `FACT_CSVS` (hand-kept) and what derives from it (`SIGNATURE_INPUTS`, `RECOGNIZED_SPEC_FILES`, `DERIVED_FILES`); `services/upgrade.py:188` `_ROW_MODELS` (C4). The tie-back tests in `tests/test_specfiles.py` will fail until then, which is what they are for. A file left unrecognized is dropped by the `revalidate`/`upgrade` rebuild, which for `meta.csv` moves the signature. | Add the names, or better derive them (upstream's guide, item 9: `ARTIFACT_PARQUETS` and `table_bindings()`); fold C4 in. About two hours. | RM323/RM324's homes for per-locus facts were the order's first items; `meta.csv`'s columns may still grow. |
| M3 | **The sweep at 0.8.** Every module with `variants.csv` gets a new `artifact.digest` on a 0.8 recompile (RM270's `vrs_id` on every variant parquet and left-aligned coordinates, RM325/RM332's study columns); `content_signature` moves for none. `parquet_bytes` is a recompile-driving axis (`RECOMPILE_DRIVING_AXES`), so once the 0.8.0 record measures it moved, which RM270 makes near certain, `declared_movement`'s "the record withholds" rule does not fire over 0.7→0.8 and the contract gap recompiles the whole catalog under plain `--apply`. RM352 adds `kind: toolchain`; `services/rebuild.py:252-253` sorts by `kind == "correction"`/`"addition"`, so a toolchain move is acted on by neither, as upstream's guide says it should be. | `services/rebuild.py`, `services/upgrade.py`, `docs/UPGRADE.md`. | Code: none needed for the kind (read `RecompileAnswer.toolchain_moves` if the report should name it). Operator: one PATCH per version, catalog-wide, with `upgrade --dry-run` first (RM336 refuses a DOI in `pmid`; upstream scanned all 47 prod versions and found none). | The 0.8.0 release record is not written; upstream expects it to declare the polars 1→2 byte move as `toolchain`. The compiler's liaison, 2026-11-04: polars 2.x enters their lock with RM342, uncapped, and since a consumer held below polars 2 by `polars-bio` keeps writing with 1.x, a toolchain difference is the standing case, not a one-time move: `compilation.toolchain` is what tells it from corruption; the registry's own lock decides the polars our server writes with (1.44.2 today, no `polars-bio` here to cap it). |
| M4 | **Enrichment the `/check` report has to show.** RM267 withholds a placement two authorities give as two events (the rsID turns unresolved, `strict` refuses, `EnrichmentResult.placement` says what ran); RM272 names three answered-but-withheld states on `EnrichmentResult`; RM305 adds the `clinvar_gkm` lane and `enrich(clinvar_gkm_cache=)`. | `services/enrich.py` (the configured-cache argument, CLAUDE.md "always pass the configured cache path"); `models/api.py` and `console/src/types.ts`; the `registry-client check` and console renderers ("a pass that could not run reports why"; a placement disagreement is not a transient, so `unresolved_hint` must not say re-run). | Two to four hours. | RM267 against today's witnesses withholds less than its motivating case suggests (upstream's own probe). |
| M5 | **Verification records name their witness** (RM292): `checked_source`, `witness_source`, `independence` (closed vocabulary), `undecided`. Upstream: a `self_consistent` check's agreement is not evidence for the value. | `models/api.py:195` `VerificationInfo` and its mirror in `console/src/types.ts`. | A lever: carry `independence`, and say beside each check whether its agreement counts. About two hours. | — |
| M6 | **Under `strict`, an escalated finding is in `errors` only** (RM359). | The strict compiles at `services/publish.py:660,716` and `services/revalidate.py:117`. | Checked 2026-11-04, nothing to change. `services/revalidate.py:79-81` returns on `not result.valid` before it reads `warnings`, so an escalated finding never reached `strict_notes`; `services/publish.py:715,728` passes both lists through and counts neither. A strict refusal now carries every accumulated error rather than the first ladder's, so a `422` can list more. | — |
| M7 | **New manifest fields, no break**: `stats.clin_sig_counts` and `clin_sig_variant_counts` (RM300; empty means not counted), `compilation.toolchain` (RM342), `compilation.vrs_version` (RM304), `tier_scale`, `meta_selectors`, and the four derived tables' blocks. | `db/facets.py`, the module card. | Levers only: a ClinVar-tier facet; the toolchain as the explanation for a digest that moved with the content unchanged. The pm's to size. | — |

| M8 | **The Ensembl snapshot moved repositories** (RM372): the lane now pulls `just-dna-seq/ensembl_variations_split` (dbSNP 157 / VEP 116); a cache whose pull record names the old repo is re-pulled, and a cache mixing releases resolves to nothing, with a warning. Re-derived resolutions move as data (left-aligned indels, one row per ALT). | `config.py:80` `ensembl_reference = "just-dna-seq/ensembl_variations"` (the old repo), passed to the compile at `services/publish.py:707` and `services/revalidate.py:120`; `registry warm-caches`; `docs/UPGRADE.md`. | Default moves to the new repo; operator step on both boxes, a 14.5 GB pull, before the 0.8 deploy. About an hour plus the pull. | Added 2026-11-04 (guide § 1.29). |
| M9 | **`validate` and `compile` reach one verdict** (RM367): `validate_spec(strict=True)` refuses wherever the strict compile does, carries every warning code the compile would, and takes the compile's switches (`resolve_with_ensembl`, new `ba1_threshold`). A refused compile now writes nothing. | The three `validate_spec` calls: `services/publish.py:595` (the modeless gate), `services/enrich.py:1028` (`/validate`, `/check`), `services/revalidate.py:78`. CLAUDE.md's parity rule ("the dry run grades where the publish grades") becomes easier to keep, not harder. | Pass the same switches the compile gets; drop any cleanup of a partial output directory. Under an hour. | Added 2026-11-04 (guide § 1.23). |
| M10 | **A retired source is `retired`, never `unreachable`** (RM361): `VALID_VERIFICATION_SKIPS` and `VALID_FULLTEXT_STATUS` gain it (HTTP 410), whose remedy is upgrading the enricher, not re-running. Several "could not ask" results gain fields (`FrequencyResult.unanswered`, `OpenTargetsResult.not_read`, …); OLS4/HGNC and eutils now raise their unavailability types on an empty body. `coordinate_key` no longer spells an absent cell `None`. | `services/enrich.py:1759` (ACMG: only `unreachable` reaches the `unreachable` list); the `registry-client check` and console renderers (`console/src/reports.ts:63-95`), "a pass that could not run reports why"; `unresolved_hint` must not say re-run for a retired source. | Two hours, with M4. | Added 2026-11-04 (guide § 1.26). |
| M11 | **A pass that answered nothing writes no table** (RM370): the header-only sidecars and their licence rows are gone, so `artifact.files` loses empty parquets and the digest moves on a recompile. | `specfiles.plan_layout` and the split download (a `derived/` with fewer files, which "the folder is a consequence of the manifest's contents" already allows); any test fixture that expects an empty sidecar. | Check, likely nothing. Under an hour. | Added 2026-11-04 (guide § 1.24). |

Read at `1007a26` (2026-11-05), guide §§ 1.30-1.33, no new row: each folds into one above. RM373 (`source_release`),
RM375 (`authored_event`, `judged_coordinate`) add `resolution.csv` columns a 0.7 reader refuses, and RM379 adds a
`clin_sig_authority_call` licence layer (`VALID_SOURCE_LAYERS`, closed, now 14): all M1, the lockstep. RM374's
`rsid_placements_disagree` is a new warning code and a strict refusal (M1, M9), RM375's struct fields move the
digest again (M3), and RM373's `rsid_coordinate_agreement.release` reading null for a mixed table is one more
"unchecked is not clean" sibling for the renderers (M4). Nothing here keeps its own list of source layers
(grep, 2026-11-05), so the new layer reaches us only through the floor.

**The finished guide (`5b1b73b8`, 2026-11-05) and what it changes here.** Upstream's § 3 now carries a
registry block matched against this map at `cef569c`, with four differences, all taken: M1's "5-8 hours" is
withdrawn (the cut waits on RM381, RM382/RM383, two examples and audit round 2, and the guide promises no time);
M3's moved `parquet_bytes` is certain, not near certain (every 0.8 `weights.parquet` gains `vrs_id`, `vrs_spec`,
`resolution_loci`); a probe against the branch is possible by git dependency on a branch, never in a published
lock, which is how the lead now builds 0.28; S129 is RM378 in 0.9, as here. Two items the block adds: pass the
configured `clinvar_gkm_cache=` (M4), and a reversed module's `resolution.csv` has six more columns and keeps an
`ambiguous` row ambiguous (RM380, § 1.34). The maintainer, 2026-11-05: "0.8 is delayed, lets wait on their 0.8
integration and pre-build on top of that"; the lead builds M1's code, M2, M4, M8-M11 on its 0.28 branch against
upstream's `0.8`, unmerged until the floors are on PyPI.

- **M12.** **The sweep re-enriches across the snapshot switch.** Upstream's upgrade order says re-derive after the Ensembl switch: an ordinary run is merge-not-clobber, and "a module enriched once before the switch and again after it without `--rederive` holds two placement sets for one rsID and may stop compiling under `--strict` (`rsid_placements_disagree`, § 1.30)". `registry upgrade` is that case: `services/upgrade.py:598-604` carries the stored `resolution.csv` into `publish_version`, which enriches again (offline, against whatever snapshot the box holds, the split one after M8) and compiles strict.
  *Where:* `services/upgrade.py:598` (the comment's premise, "carrying them makes the re-publish cheap and deterministic", is what § 1.30 makes unsafe); the publish path's `enrich()` calls, which pass no `rederive`; `docs/UPGRADE.md`.
  *Fix and cost:* A decision for the lead before M3 runs: drop the carried `resolution.csv` (re-resolves from the snapshot, egress-free on a provisioned box, but moves resolutions as data, § 1.29) or rederive (online re-asks every source; offline makes every indel verdict `undecided`). `upgrade --dry-run` must surface the refusal per module either way. Half a day with the choice.
  *Still moving:* Added 2026-11-05 from guide § 2 step 5 and § 1.30.
  *Upstream's recommendation* (the compiler's lead, 2026-11-05): **rederive**, not a plain re-enrich and not a
  drop. `enrich --rederive` yields a table byte-identical to delete-and-re-enrich, so the choice above is not
  between two tables: rederive keeps the per-subject drift report (respelled / moved / undecided, RM375) and
  stamps `source_release`, which the drop loses. Run it **online** for any module with indels, since offline
  cannot left-align (RM376), which collides with the registry's offline-by-default publish
  (`config.py:110` `enrich_offline = True`): the sweep needs an online enrich setting for its run, and its
  egress budget. Measured upstream on their 14 examples: `content_signature` held on all, `artifact.digest`
  moved on all. And **sweep after RM381** (per-ALT trim of multi-ALT indels, still landing), or rederive again.

Also new, levers only: RM362's `compiler.subjects.module_subjects` is upstream's one answer to "which genes and loci is this module about" (for the variant catalog after 0.28); RM363's `just_dna_format.spelling` is one comparison rule per kind of value (gene, drug, DOI, contig), worth reading before the registry compares any of those itself.

Nothing for us, read: RM303 moved `release.json`'s model into `just_dna_format.snapshot` and `read_release` now
returns a model, but the registry reads the raw JSON for keys that were not renamed (`builder_version` at
`services/enrich.py:492`, `sf_version`/`gene_count` at `cli.py:1295`) and only tests `read_release(...) is None`
(`services/enrich.py:615`); RM342's `ToolchainDiffersError` is the enricher's HuggingFace publisher, which the
registry does not use; RM337/RM338/RM348's `logs/` rules apply inside the compile and `normalize_spec` already
never moves `logs/`; RM253/RM356 change the CPIC drafter's output, which `POST /drafts` passes through; the
polars, duckdb and `ga4gh.vrs` floors on the branch (`>=1.42.0`, `>=1.1.0`, `>=2.3.3,<2.4`) are met by this
lock (1.44.2, 1.5.5, 2.3.3).

## Our pieces the upstream may come to do

| ours | what upstream lacks | retires when | checked |
|---|---|---|---|
| `warm-caches` rebuilds a stale derived lane (`services/enrich.LaneAge`) | `prepare_lane` reads no `builder_version` | `uv run python -c "import inspect,just_dna_enricher.caches as c; print('builder_version' in inspect.getsource(c.prepare_lane))"` prints `True` | 2026-11-04: `False` on installed 0.7.3; `builder_version` absent from `caches.py` on `main` and `0.8` |
| `served_from` withholds a path-shaped entry | the S93 split has no version of its own | never by a floor (CLAUDE.md) | — |
| `shared_lookup_clients()` eager construction | nothing (C2) | C2 built | 2026-11-04 |

## Outbound

- **S129** (filed 2026-11-04, appended to the compiler checkout's inbox, uncommitted; its triage told): a strict
  refusal's errors carry no code, so `build_disagreement_error` (module-level) cannot be told from the
  unresolved aggregate (per-row) without reading wording; asks for coded errors / an `errors_summary`, or a
  narrower field. From C11, on the lead's decision. **Answered 2026-11-04** (their 549321a6, on their `main`,
  unpushed): (a) filed as RM378, placed in 0.9 by their pm (0.8 is near its cut, and a code vocabulary is permanent); (b) not taken. Meanwhile RM377 publishes the two
  strict-only refusals' phrases in their `docs/COMPILER.md` ("The refusals only strict adds"), pinned by a test
  there: both open with `strict compile: `; `genome_build_disagreement` = "whose coordinates the enricher
  diagnosed as another assembly's", `unresolved_positions` = "have unresolved genomic positions after
  resolution". A frozen fragment, like `UNJOINABLE_PHRASE`, so matching it is the documented interim. Both
  phrases are already in the installed 0.7.2 compiler. Closes when RM378 ships and our pin reaches it.
  Last checked: 2026-11-04.

- **S130** (filed 2026-11-05, appended to the compiler checkout's inbox, uncommitted; its triage told): the
  Ensembl lane's repository (`just-dna-seq/ensembl_variations_split`) has no public name on `0.8`: the lane's
  `publish_repo` is `None` and the string is private (`download._ENSEMBL_HF_PREFIX`); the public
  `SNAPSHOT_REPO_PREFIXES["ensembl"]` holds it as an fsspec prefix, not a repo id. Asks for a public
  `DEFAULT_ENSEMBL_REPO_ID` or a lane → repo id map, or upstream's view that a pin should be the release
  (`locations.ensembl_release_label`). From the lead's M8 pre-build (59ddcd9 on branch 0.28), which spells
  the repo in `config.py` with a test reading the private prefix. **Answered 2026-11-05**: accepted as (b),
  filed as RM384 (a minor their pm places): one public lane → repo-id map with every prefix derived from it,
  `DEFAULT_*_REPO_ID` kept as aliases (every pulled lane spelled its repo twice, untied). On the release label:
  not as the pin alone, since `ensembl_reference` documents `org/repo@<rev>`, which names bytes, and the label
  names data. Keep the spelled repo until RM384 ships; then read the map. RM384 is placed in their 0.8
  (their triage, 2026-11-05), so at the cut M8's drift test moves to it. Last checked: 2026-11-05.

Before S129, upstream's inbox held nothing from the registry open. The
registry's filings named in CLAUDE.md (S38, S81, S90, S92, S93) are answered in its history; S81, S90, S92 and S93
shipped in 0.7.0. The rest of the registry's past filings are not yet audited here.
