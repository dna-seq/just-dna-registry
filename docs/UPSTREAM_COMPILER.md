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
- **The `0.8` branch** (197 commits past `main`, head `0a5293b`): the coming minor. Its adoption map goes to the
  lead and the pm (`format-0.8-adoption`); progress in `docs/seats/LIAISON_NOTES.md`.

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
