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
  what it fixed of ours. Three items below (C1 to C3) come from a first pass over the filings the registry made
  upstream; the rest of the 0.7.0 changelog is unread for this purpose. Next slice starts at the 0.7.0 cut's
  entries in `docs/CHANGELOG.md` on `main`.
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

State, 2026-11-04: the lead filed C4, C1 and C2 on `docs/ROADMAP.md` (fcd2589, cd4c511; "Next registry version",
unattended patches in that order), with the 0.8 map's M2 folded into C4's derivation; C3 waits on the person's yes.

## The coming minor: format 0.8 (adoption map, first pass, 2026-11-04)

For the lead and the pm, for `format-0.8-adoption`. Read from the `0.8` branch at `0a5293b`: upstream's
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
| M1 | **The lockstep cut.** A 0.7 `just-dna-format` refuses 0.8 output in five places: every `verification.json` and manifest `verification` block a 0.8 enricher writes (RM292 adds four fields to `extra="forbid"` `VerificationRecord`), a 0.8-enriched `resolution.csv` (RM267's two columns), new `warnings_summary` codes (closed `VALID_WARNING_CODES`), `pmid=NONE` and the new `doi` columns (RM336), and a serialized `DeclaredChange` with `kind: toolchain` (RM352). Server, `registry-client` and the console move together; `version.contract_compatible` already refuses a mixed pair. | Floors `pyproject.toml:72` (format), `:119`, `:308-309` (compiler, enricher); `uv.lock`; `docs/UPGRADE.md`; CLAUDE.md's floor reasons. | A coordinated cut, as 0.7's was. About half a day with the 25-minute suite and the operator procedure. | The floors cannot be written yet: on the branch the format says 0.8.0 but the compiler is still 0.7.2 and the enricher 0.7.3. The compiler's lead, 2026-11-04 ~20:40 UTC: the cut sets all three to 0.8.0 with `>=0.8.0` floors, writes the 0.8.0 release record and finishes `INTEGRATION_0_8.md`, after the round-1 audit fixes, audit round 2, a release-gate sweep and a docs pass; "5-8 hours from now". |
| M2 | **Six new tables.** Authored and inside `content_signature`: `meta.csv` (RM28, RM323, RM324) and `model_organisms.csv` (RM335), registered in the new public `compiler.AUTHORED_NON_KIND_TABLES` beside `overrides.csv`. Derived fact tables, outside the signature: `locus_to_gene.csv`, `colocalisations.csv` (RM333), `consequences.csv` (RM236), `ld_pairs.csv` (RM331). Disjointness holds: none of the four derived ones is in `_INPUT_FILES`. | `specfiles.py` `FACT_CSVS` (hand-kept) and what derives from it (`SIGNATURE_INPUTS`, `RECOGNIZED_SPEC_FILES`, `DERIVED_FILES`); `services/upgrade.py:188` `_ROW_MODELS` (C4). The tie-back tests in `tests/test_specfiles.py` will fail until then, which is what they are for. A file left unrecognized is dropped by the `revalidate`/`upgrade` rebuild, which for `meta.csv` moves the signature. | Add the names, or better derive them (upstream's guide, item 9: `ARTIFACT_PARQUETS` and `table_bindings()`); fold C4 in. About two hours. | RM323/RM324's homes for per-locus facts were the order's first items; `meta.csv`'s columns may still grow. |
| M3 | **The sweep at 0.8.** Every module with `variants.csv` gets a new `artifact.digest` on a 0.8 recompile (RM270's `vrs_id` on every variant parquet and left-aligned coordinates, RM325/RM332's study columns); `content_signature` moves for none. `parquet_bytes` is a recompile-driving axis (`RECOMPILE_DRIVING_AXES`), so once the 0.8.0 record measures it moved, which RM270 makes near certain, `declared_movement`'s "the record withholds" rule does not fire over 0.7→0.8 and the contract gap recompiles the whole catalog under plain `--apply`. RM352 adds `kind: toolchain`; `services/rebuild.py:252-253` sorts by `kind == "correction"`/`"addition"`, so a toolchain move is acted on by neither, as upstream's guide says it should be. | `services/rebuild.py`, `services/upgrade.py`, `docs/UPGRADE.md`. | Code: none needed for the kind (read `RecompileAnswer.toolchain_moves` if the report should name it). Operator: one PATCH per version, catalog-wide, with `upgrade --dry-run` first (RM336 refuses a DOI in `pmid`; upstream scanned all 47 prod versions and found none). | The 0.8.0 release record is not written; upstream expects it to declare the polars 1→2 byte move as `toolchain`. |
| M4 | **Enrichment the `/check` report has to show.** RM267 withholds a placement two authorities give as two events (the rsID turns unresolved, `strict` refuses, `EnrichmentResult.placement` says what ran); RM272 names three answered-but-withheld states on `EnrichmentResult`; RM305 adds the `clinvar_gkm` lane and `enrich(clinvar_gkm_cache=)`. | `services/enrich.py` (the configured-cache argument, CLAUDE.md "always pass the configured cache path"); `models/api.py` and `console/src/types.ts`; the `registry-client check` and console renderers ("a pass that could not run reports why"; a placement disagreement is not a transient, so `unresolved_hint` must not say re-run). | Two to four hours. | RM267 against today's witnesses withholds less than its motivating case suggests (upstream's own probe). |
| M5 | **Verification records name their witness** (RM292): `checked_source`, `witness_source`, `independence` (closed vocabulary), `undecided`. Upstream: a `self_consistent` check's agreement is not evidence for the value. | `models/api.py:195` `VerificationInfo` and its mirror in `console/src/types.ts`. | A lever: carry `independence`, and say beside each check whether its agreement counts. About two hours. | — |
| M6 | **Under `strict`, an escalated finding is in `errors` only** (RM359). | The strict compiles at `services/publish.py:660,716` and `services/revalidate.py:117`. | Checked 2026-11-04, nothing to change. `services/revalidate.py:79-81` returns on `not result.valid` before it reads `warnings`, so an escalated finding never reached `strict_notes`; `services/publish.py:715,728` passes both lists through and counts neither. A strict refusal now carries every accumulated error rather than the first ladder's, so a `422` can list more. | — |
| M7 | **New manifest fields, no break**: `stats.clin_sig_counts` and `clin_sig_variant_counts` (RM300; empty means not counted), `compilation.toolchain` (RM342), `compilation.vrs_version` (RM304), `tier_scale`, `meta_selectors`, and the four derived tables' blocks. | `db/facets.py`, the module card. | Levers only: a ClinVar-tier facet; the toolchain as the explanation for a digest that moved with the content unchanged. The pm's to size. | — |

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

Upstream's inbox (`docs/CONSUMER_SUGGESTIONS.md` on `main`) holds nothing open; its next id is S128. The
registry's filings named in CLAUDE.md (S38, S81, S90, S92, S93) are answered in its history; S81, S90, S92 and S93
shipped in 0.7.0. The rest of the registry's past filings are not yet audited here.
