# Upstream ledger: the compiler's three packages

`just-dna-format`, `just-dna-compiler` and `just-dna-enricher`, released together from
`dna-seq/just-dna-compiler` with tags `vX.Y.Z` (the tag names the cut; each package carries its own version).
Kept by the liaison seat (`docs/seats/LIAISON.md`); another seat that meets a symptom in these packages sends it
there rather than writing here.

Watched on this machine from a clone outside the repository, `/data/sources/just-dna-compiler` (its line in the
liaison state file): `[seat.liaison.watch.compiler]` says each new tag, `[seat.liaison.watch.compiler-next]` each
commit to `docs/CHANGELOG.md` on the coming minor's branch (`main` between the 0.8.0 cut and the opening of `0.9`).

## Read mark

**`v0.8.2`** read (2026-11-08: all three packages at 0.8.2 on PyPI, tag `b98f7e9`, read commit by commit in the
backlog below). **`v0.8.1`** read (2026-11-07: enricher 0.8.1 on PyPI 16:47 UTC, tag `6330f90`, read at its recut below; format and compiler stay 0.8.0). **`v0.8.0`** read (2026-11-05): all three packages at 0.8.0, on PyPI since 19:56 UTC; the tag is `e97339a3` on
`main`, whose package sources are byte-identical to `edf2661c` on `0.8` (only `docs/` differs), so the map below,
read at the cut, is the read of the tag. Installed on `main`: all three at 0.8.0 since registry 0.28.0 (`c5a7840`,
2026-11-06; `>=0.8.0` floors, resolved from PyPI); 0.28.0 to 0.28.2 published (`v0.28.2`, 2026-11-07). Past the tag, `main` holds RM397
(`3f2dac4`, the enricher wheel drops its Atlas `.proto` sources; packaging only, nothing we import) and docs.

## Backlog

- **The 0.7.0 cut, read for levers.** 0.7 was adopted for what broke us (CLAUDE.md records each), not read for
  what it fixed of ours. C1 to C3, C5 and C6 come from the entries answering the registry's own filings; the
  rest gave C7 to C15 (second slice, 2026-11-04); 0.7.1 to 0.7.3 gave C16 to C19 (2026-11-05). Everything up
  to the read mark is read.
- ~~**`main` past `v0.7.3`** and **the `0.8` branch**~~: both reached `v0.8.0` (the main patches were merged into
  the cut; no `v0.7.4` was made). Read through the map below.
- **The next patch on their `main` (0.8.1)** carries RM400, RM401 and RM403 (S132, S133 below). At its tag: check
  each shipped, then tell the lead, who holds four modules for RM400 and re-measures the sweep on RM401. Whether
  the floor must rise to it is read then: four modules are held for RM400, so a floor below it would let them
  be re-derived without the fix.
  **Cut as `v0.8.1`** (`f38d677` on their `main`, 2026-11-07): enricher 0.8.1 only; format and compiler stay 0.8.0
  and carry no release record (nothing to recompile). Not yet on PyPI or tagged. Read from its changelog: RM400
  (live REST drops GRCh38 patch/alt-contig loci; `--rederive` leaves recorded ones out, counted in one warning),
  RM401 (20 rsIDs per POST), RM403 (a WARNING per retry on `just_dna_enricher.net`, and the give-up names attempts and
  seconds), RM397 (packaging). **No public name is added** (`b6ea746`): the batch size (20) and the POST's read
  timeout (120 s) are private constants until 0.9's RM404, so there is nothing for us to pass, and our
  `enrich_http_timeout_seconds` (`services/enrich.py:325`, `EnsemblSettings(timeout=...)`) does not bound a batch
  read in 0.8.x. At the publish: the enricher floor rises to `>=0.8.1`, a hard floor (the four modules held for
  RM400 must not be re-derived below it); format and compiler stay `>=0.8.0`. It ships in registry 0.28.3 (the lead's, held by the person meanwhile).
- **0.8.1 recut** (`6330f90`, 2026-11-07, before any publish): **RM407** (an indel's VRS mint reads one reference
  window per locus, not one read per normalize step: 2,472 reads, ~354 s, in the lead's replay; no id moves) and
  **RM398** (the third placement witness is dbSNP's record from the merge check's `esummary`, no new request; our
  S132's (a)(b)(d)) join it. Read against us: new `resolution.csv` rows name `dbsnp` as `placement_witness` and
  `sources.csv` gains a `dbsnp` resolution row; we carry witness names verbatim (`models/api.py:207`, no copy of the
  vocabulary) and charge `/hint` for a live Ensembl *answer* only (`services/hints.reconcile_ensembl`), so nothing
  here moves. A run with the merge check off counts those indels as not asked. RM406 filed and parked.
- **Their `main` past `v0.8.1`, unreleased** (read 2026-11-07): **RM408** (`7c075b7`) gives the Open Targets lane
  `publish_repo` (`just-dna-seq/opentargets`) and a pull route, a patch with no new public name. Nothing here
  moves in code: `warm-caches` takes the route off the lane, and `drop-caches` asks `--force` only for a lane
  whose route is not `pull` (`services/cache_drop.py:170`), so a pulled Open Targets lane drops without it once
  shipped. At its publish, one sentence goes stale: `services/cache_drop.py:19` ("OpenTargets a long build"); the
  lead's to change with the floor, if the floor moves.
  **RM411** (`01600ee`): `cache rebuild --dry-run` fetches and builds nothing; `rebuild_lane` is split, its behaviour
  unchanged, and we call neither (`prepare_caches` only). **RM413** (`e7befd8`): their cut gate, no lane with a
  repository left unpublished; tests and docs only. Nothing here moves for either. 
  **RM414/RM415** (`89610c3`, module-creator's S136/S137): two repeat-bin warnings reworded; codes, firing and the
  published fragments unchanged, and a compiler patch is no recompile gap here.
  **RM410/RM416** (`21f5976`): the `constraint` lane builds gnomAD 4.1.2 by default and `enrich_gene_metrics` takes
  a row from any snapshot release, so a 4.1 pull here stays good; a `--pin` on a lane whose adapter ignores it is now
  refused. We pass no pin (`warm-caches` goes through `prepare_caches`), and `constraint` is only in
  `METRICS_REFERENCES` (`services/enrich.py:81`). Nothing moves.
  **RM417** (`19b3634`): rows from the live gnomAD constraint API are labelled `gnomad_api_constraint`, no longer
  `gnomad_v2.1.1_constraint`; old rows are not rewritten. Nothing here reads either label.
- **Cut as `v0.8.2`** (`b98f7e9` on their `main`, 2026-11-07; tagged and on PyPI 2026-11-08): all three packages to
  0.8.2, their inter-package floors `>=0.8.2`. Carries RM408, RM410, RM411, RM413-RM417, each read above: no public
  name, field, table, flag or warning code. Release record `0.8.2` (from 0.8.0, 22 reference modules): only
  `compilation.warnings` moved, in 2, **declared as an addition**, so `declared_movement` does not act and no sweep
  follows. **Not a hard floor here**: our floors may stay (`>=0.8.0`, enricher `>=0.8.1`); a lock that takes enricher
  0.8.2 takes format and compiler 0.8.2 with it. It rides the weekly bump once on PyPI (a patch, the liaison's under
  its grant), with the `services/cache_drop.py:19` sentence (RM408) fixed in the same patch.
- **Their `main` past `v0.8.2`, unreleased** (read 2026-11-08): **RM418** (`d28c74b`, RM404's patch half): an
  `EutilsClient` built without a gate takes one process-wide gate per (service, interval), so `check_rsids`' own
  client and the literature pass, or two `enrich()` runs on two threads, pace against one NCBI budget; all new names
  private. Against us: `_UNSHARED_EGRESS` (`services/enrich.py:263`, taken at `:1095` when `enrich_verify_rsids` or
  `enrich_verify_datasets` is on) exists for exactly the first. Once our enricher floor reaches the release carrying
  RM418, the `verify_rsids` half of that condition is upstream's; the `verify_datasets` half stays until **RM419**
  (filed: the same class beyond NCBI, Ensembl REST first) ships. The lock is narrowed when the floor moves, not on a
  release we merely lock to. Check: `uv run python -c "import inspect,just_dna_enricher.net as n; print('_service_gate' in inspect.getsource(n))"`
  (run 2026-11-08 on the installed enricher: `False`; a `True` is a prompt to read `net`, not proof).
  **RM420** (`dd900ff`, unreleased): `prepare_lane` and `cache pull` hand each lane's `ensure` a private
  `_follow_hub`, so a **present** cache pulled from the lane's own repo is re-pulled when the hub publishes another
  `release_label` (gnomAD constraint 4.1 → 4.1.2, STRchive v2.26.0 → v2.28.0); a cache built here is left alone with
  both labels, an unreadable hub serves it as it is, and `enrich`'s own `ensure` still never reads the hub. No
  public name moves; `pulled_from_elsewhere` and `pull_record_repo`, which we call, are unchanged. **Against us
  the fix does not arrive by itself**: `warm-caches` hands `prepare_caches` only the absent lanes plus
  `lanes_to_repull` (`services/enrich.py:574`: a record naming another repo, or none), so a present lane whose record
  names its current repo never reaches the new comparison, the 0.28.1 shape again. Once our enricher floor carries
  RM420, every present pullable lane (selected, or all: the lead's call; the cost is one small hub read per lane)
  goes to `prepare_caches`, and `lanes_to_repull`'s docstring and CLAUDE.md's "a present pulled lane whose record
  names another repo (or none)" move with it. The derived-lane bandaid (`LaneAge`) stays: a built lane is still
  left alone. Check: `uv run python -c "import inspect,just_dna_enricher.download as d; print('_follow_hub' in inspect.signature(d.ensure_constraint_snapshot).parameters)"`
  (run 2026-11-08 on the installed enricher: `False`).
  **RM409** (`e0ceaa2`, unreleased): `net.stream_to_file` takes a private `_stop` event, so Ctrl-C or a first
  failure stops the Open Targets mirror and the AlphaGenome AVI build within a chunk instead of joining every
  in-flight part. We call neither build nor `stream_to_file` (a build would reach us only through `prepare_caches`);
  nothing moves here.
  **RM421** (`83182f8`, unreleased): `stream_to_file`'s timeout defaults to a private 120 s where it was `None` (no
  timeout), so a source that accepts and goes silent fails a build instead of hanging it. Reaches us only through
  `warm-caches` → `prepare_caches` (the CIViC, ClinVar GKM, MANE builds among others): a hang there becomes a lane
  reported failed, which `warm-caches` already prints and counts. No code or doc here moves.
  **RM422** (`61a2056`, unreleased; module-creator's S138): `validate_spec` adds one more `derived_row_orphan` arm, a
  `resolution.csv` row whose `variant_key`/`rsid` no authored locus table names, a warning in both modes, no new code
  or name. Nothing here keys on that code (`sweep_report` types it by its code like any other). Expect it on `/check`
  and in `registry upgrade` sweeps over a stored table that kept rows for variants an author later removed, since the
  enricher merges rather than clobbers; a warning, never a hold. Nothing moves.
  **RM423** (`b74d4f0`, unreleased; module-creator's S139): `merge_records(existing_still_binds=False)` keeps only
  this run's records, so a run over edited authored bytes no longer re-signs an earlier check's record under the new
  `module_hash`; `record_verification` logs each check it drops. Defaults and unchanged bytes behave as before; no
  public name moves. Against us: our publish and `/check` call `enrich()` over the uploaded spec, which writes
  `verification.json` through that path, so from the next patch an upload whose `verification.json` predates an edit
  loses those records on the server (a log warning, no field of ours). **Not repaired**: a document 0.8.2 already
  wrote that way binds to its bytes and is carried on, so published manifests may hold such records; only the author
  can re-run. Upstream calls it a corrected derivation: at the cut, read the release record for a declared
  `correction` and its `requires` before deciding whether `registry upgrade` acts (`declared_movement`). No code here
  moves now.
- **Cut as `v0.8.3`** (`725eb2b` on their `main`, 2026-11-09; untagged and not on PyPI when read, 07:4x CET): all
  three packages to 0.8.3, inter-package floors `>=0.8.3`. Carries RM418, RM420, RM409, RM421, RM422, RM423, each
  read above, plus `7a4ac41` (RM409's stop signals subclass `BaseException`, private) and `4fef32f` (RM421's test
  walk); no public name, field, table, flag or warning code. Release record `0.8.3` (from 0.8.2, 22 reference
  modules): **every axis measured `False`, `declared=[]`**, so RM423's corrected derivation is not a declared
  `correction` and `registry upgrade` acts on nothing. **Not a hard floor**, but two of our items wait on a floor of
  0.8.3, both the lead's: the `verify_rsids` half of `_UNSHARED_EGRESS` (RM418) and `warm-caches` handing present
  pulled lanes upstream (RM420). The weekly bump takes 0.8.3 instead of 0.8.2 once it is on PyPI.
- **Their `main` past the 0.8.3 cut**: **RM425** (`290acb5`, module-creator's S140): `ExpressionEffectRow.effect_size`'s
  field description says it is the single strongest track, not an aggregate; wording only. Nothing here reads that
  model or repeats the sentence. Nothing moves.
  **RM426** (`249c18d`, module-creator's S141): `GeneLocusConflict`'s closing sentence no longer says "a real symbol
  beside an invented rsID"; it names both readings (a made-up rsID, or a real one beside the wrong gene) and the lookup
  that tells them apart. The fact sentence is unchanged byte for byte. **We repeat the retracted guess**: the
  `gene_loci` field description (`models/api.py:1181`, served in the OpenAPI schema) and `docs/CLIENT.md:555` call
  the finding the signature of an invented rsID beside a real symbol; `services/enrich.py:1981` already says which
  half is wrong is unknowable. A wording fix, the lead's (handed 2026-11-09); no floor needed, nothing reads the
  sentence.
  **RM427** (`e7fa81d`, module-creator's S142): the ClinVar clinical-assertion pass's no-snapshot skip, a log
  warning in `assertions.py` and a CLI line, named `clinvar pull`, which no app registers. It now names `cache pull
  --only clinvar` or `clinvar build`. Nothing in this repo names either command or reads the sentence (a grep of
  `src`, `docs`, `console`), and we import no symbol from `assertions`. Nothing moves.
- **RM404** (`enrich()` takes the eutils client, from S133): the lead asked their triage (2026-11-07) for it in a
  0.8.x patch; their pm keeps it in 0.9, since no new public parameter lands on their `main`, even an additive one.
  `_UNSHARED_EGRESS` stays the answer until 0.9.

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
  Ours is not wrong, only redundant: eager costs eight connections on the first online run. ~~Fix: hand over an
  empty shared bundle and let `ensure` fill it~~ **Wrong, corrected by the lead (2026-11-05):** `services/enrich.py`
  hands the passes single clients (`resolver=clients.ensembl`, `client=clients.ontology`), not the bundle, so an
  empty bundle passes `None` and each pass builds its own unpaced client; only the `/hint` routes pass the bundle
  whole, where `ensure` fills it. So the bundle stays filled. **Done, narrowed** (e64801f, registry 0.27.1): the
  docs and a test over `CLIENT_FIELDS`. The lesson for this seat: a fit that removes a piece of ours is read
  against every call site first, not against the call site the upstream entry describes.
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
  *2026-11-05, no filing:* the lead asked whether `LookupClients` should gain a PGS field. Not needed:
  `PgsCatalogClient(gate=...)` takes a `PacingGate` and calls its gate and cache per-run state, so one gate per
  process and a fresh client per check shares the pace without sharing a cache. On 0.28 the leg is off,
  reported by `pgs_not_checked`, until the lead spends the egress.
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

The 0.7.0 cut read for levers, first slice (2026-11-04): two entries answering filings about the registry
(S88/S89 on 2026-09-03, filed by just-module-creator, not by us, both adopted: `lane.env_var` at `services/enrich.py:683`, `needs_recompile` with an
unstamped compiler; S91-S95 on 2026-09-11, giving C5 and C6). The rest of 0.7.0 is unread for this purpose.

**Done in registry 0.27.1 (the lead, 2026-11-05):** C1, C2 (narrowed), C4, C6, C8's patch half, C9, C11, C12,
C16.

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
| M3 | **The sweep at 0.8.** Every module with `variants.csv` gets a new `artifact.digest` on a 0.8 recompile (RM270's `vrs_id` on every variant parquet and left-aligned coordinates, RM325/RM332's study columns); `content_signature` moves ~~for none~~ for a module with `chr`-prefixed contigs on four tables (RM363, corrected at the cut, below). `parquet_bytes` is a recompile-driving axis (`RECOMPILE_DRIVING_AXES`), so once the 0.8.0 record measures it moved, which RM270 makes near certain, `declared_movement`'s "the record withholds" rule does not fire over 0.7→0.8 and the contract gap recompiles the whole catalog under plain `--apply`. RM352 adds `kind: toolchain`; `services/rebuild.py:252-253` sorts by `kind == "correction"`/`"addition"`, so a toolchain move is acted on by neither, as upstream's guide says it should be. | `services/rebuild.py`, `services/upgrade.py`, `docs/UPGRADE.md`. | Code: none needed for the kind (read `RecompileAnswer.toolchain_moves` if the report should name it). Operator: one PATCH per version, catalog-wide, with `upgrade --dry-run` first (RM336 refuses a DOI in `pmid`; upstream scanned all 47 prod versions and found none). | The 0.8.0 release record is not written; upstream expects it to declare the polars 1→2 byte move as `toolchain`. The compiler's liaison, 2026-11-04: polars 2.x enters their lock with RM342, uncapped, and since a consumer held below polars 2 by `polars-bio` keeps writing with 1.x, a toolchain difference is the standing case, not a one-time move: `compilation.toolchain` is what tells it from corruption; the registry's own lock decides the polars our server writes with (1.44.2 today, no `polars-bio` here to cap it). |
| M4 | **Enrichment the `/check` report has to show.** RM267 withholds a placement two authorities give as two events (the rsID turns unresolved, `strict` refuses, `EnrichmentResult.placement` says what ran); RM272 names three answered-but-withheld states on `EnrichmentResult`; RM305 adds the `clinvar_gkm` lane and `enrich(clinvar_gkm_cache=)`. | `services/enrich.py` (the configured-cache argument, CLAUDE.md "always pass the configured cache path"); `models/api.py` and `console/src/types.ts`; the `registry-client check` and console renderers ("a pass that could not run reports why"; a placement disagreement is not a transient, so `unresolved_hint` must not say re-run). | Two to four hours. | RM267 against today's witnesses withholds less than its motivating case suggests (upstream's own probe). |
| M5 | **Verification records name their witness** (RM292): `checked_source`, `witness_source`, `independence` (closed vocabulary), `undecided`. Upstream: a `self_consistent` check's agreement is not evidence for the value. | `models/api.py:195` `VerificationInfo` and its mirror in `console/src/types.ts`. | A lever: carry `independence`, and say beside each check whether its agreement counts. About two hours. | — |
| M6 | **Under `strict`, an escalated finding is in `errors` only** (RM359). | The strict compiles at `services/publish.py:660,716` and `services/revalidate.py:117`. | Checked 2026-11-04, nothing to change. `services/revalidate.py:79-81` returns on `not result.valid` before it reads `warnings`, so an escalated finding never reached `strict_notes`; `services/publish.py:715,728` passes both lists through and counts neither. A strict refusal now carries every accumulated error rather than the first ladder's, so a `422` can list more. | — |
| M7 | **New manifest fields, no break**: `stats.clin_sig_counts` and `clin_sig_variant_counts` (RM300; empty means not counted), `compilation.toolchain` (RM342), `compilation.vrs_version` (RM304), `tier_scale`, `meta_selectors`, and the four derived tables' blocks. | `db/facets.py`, the module card. | Levers only: a ClinVar-tier facet; the toolchain as the explanation for a digest that moved with the content unchanged. The pm's to size. | — |

| M8 | **The Ensembl snapshot moved repositories** (RM372): the lane now pulls `just-dna-seq/ensembl_variations_split` (dbSNP 157 / VEP 116); a cache whose pull record names the old repo is re-pulled, and a cache mixing releases resolves to nothing, with a warning. Re-derived resolutions move as data (left-aligned indels, one row per ALT). | `config.py:80` `ensembl_reference = "just-dna-seq/ensembl_variations"` (the old repo), passed to the compile at `services/publish.py:707` and `services/revalidate.py:120`; `registry warm-caches`; `docs/UPGRADE.md`. | Default moves to the new repo; operator step on both boxes, a 14.5 GB pull, before the 0.8 deploy. About an hour plus the pull. | Added 2026-11-04 (guide § 1.29). |
| M9 | **`validate` and `compile` reach one verdict** (RM367): `validate_spec(strict=True)` refuses wherever the strict compile does, carries every warning code the compile would, and takes the compile's switches (`resolve_with_ensembl`, new `ba1_threshold`). A refused compile now writes nothing. | The three `validate_spec` calls: `services/publish.py:595` (the modeless gate), `services/enrich.py:1028` (`/validate`, `/check`), `services/revalidate.py:78`. CLAUDE.md's parity rule ("the dry run grades where the publish grades") becomes easier to keep, not harder. | Pass the same switches the compile gets; drop any cleanup of a partial output directory. Under an hour. | Added 2026-11-04 (guide § 1.23). |
| M10 | **A retired source is `retired`, never `unreachable`** (RM361): `VALID_VERIFICATION_SKIPS` and `VALID_FULLTEXT_STATUS` gain it (HTTP 410), whose remedy is upgrading the enricher, not re-running. Several "could not ask" results gain fields (`FrequencyResult.unanswered`, `OpenTargetsResult.not_read`, …); OLS4/HGNC and eutils now raise their unavailability types on an empty body. `coordinate_key` no longer spells an absent cell `None`. | `services/enrich.py:1759` (ACMG: only `unreachable` reaches the `unreachable` list); the `registry-client check` and console renderers (`console/src/reports.ts:63-95`), "a pass that could not run reports why"; `unresolved_hint` must not say re-run for a retired source. | Two hours, with M4. | Added 2026-11-04 (guide § 1.26). |
| M11 | **A pass that answered nothing writes no table** (RM370): the header-only sidecars and their licence rows are gone, so `artifact.files` loses empty parquets and the digest moves on a recompile. | `specfiles.plan_layout` and the split download (a `derived/` with fewer files, which "the folder is a consequence of the manifest's contents" already allows); any test fixture that expects an empty sidecar. | Check, likely nothing. Under an hour. | Added 2026-11-04 (guide § 1.24). |
| M13 | ~~**A retired ClinGen list is reported `unreachable`**~~ *Already held on branch `0.28`: M10 (`84d4a6c`) routes every outage arm, ClinGen's included, through `net.could_not_ask_reason`, which reads `EndpointRetired`; I read `main`, not the branch. The lead tests it after the rev move. Upstream's § 1.26 row now says such a host catches `EndpointRetired` first.* (RM361's audit round 2, guide § 1.26): a 410 now raises the lane's `*Retired`, a subclass of its `*Unavailable` and of `net.EndpointRetired`. Upstream says a handler catching the `*Unavailable` needs nothing, which holds for its own CLI and not here: our ClinGen arm appends `clingen` to `unreachable` for any `ClinGenUnavailable`, so a retired list reads as an outage and sends the operator to a network that is fine (M10's rule, one leg over). ACMG is safe (`AcmgRetired.skip` is `retired`, and the arm reads `skip`); ClinPgx is safe (snapshot only, `download=False`, caught as a skip). | `services/enrich.py:2011`: a `ClinGenRetired` arm above it (subclass first, as the AST guard already wants), reported as a skip naming the upgrade; the guard's subclass table gains the pair. | Thirty minutes, with M10. | Added 2026-11-05 (guide at `a4a401e7`). |
| M14 | **An answered-but-rejected rsID is now `unresolved` with no row, and our hint gives it three wrong remedies** (RM382, reversing S85, guide § 1.36 and § 2 step 23). Since 0.7 such an rsID had a `not_found` row; on 0.8 a later link may place it (`superseded_answers`), and if none can host the genotype it has no row, sits in `unresolved`, and strict refuses with a third sentence. `unresolved_hint` then says provision a snapshot, allow egress or author coordinates, when the fault is the authored genotype (a strand flip, a wrong allele). This turns C10 from a lever into a defect on 0.8. | `services/enrich.py:959` `unresolved_hint` and `EnrichOutcome` (`:193`): carry `allele_mismatches` keys (with `links`), and name them first, apart from `unreachable_rsids`; the `/check` renderers (CLI and console) show them. Never match the strict sentence. | Two hours (C10's estimate). | Added 2026-11-05 (guide at `a4a401e7`). |

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
  moved on all. And **sweep after RM381** (per-ALT trim of multi-ALT indels, landed by `a4a401e7`), or rederive again.
  *Since `a4a401e7`*, three more things a rederive sweep does: RM381 can give an authored positional row
  its `rsid` from the split repo's padded row, so a module that also authors that rsID's same allele by rsID
  stops compiling (`Duplicate (variant, genotype)`; the dry run must show it per module); RM383 retires a
  `resolution`-layer licence row no `resolution.csv` row names, so `manifest.sources`, `sources.signature`
  and our licensing facets can move on the successor; RM387 adds `source_loci` to `resolution.csv` and to the
  `resolution_loci` struct (the digest moves anyway, M3). Guide § 4 ships RM385 unfixed (offline cannot
  left-align), so the online setting for the sweep is not optional.

**The guide at `a4a401e7` (2026-11-05)**, read §§ 1.35-1.40, § 2 steps 23-25 and the new § 4: M13 and M14 above, and M12's rederive gains three effects. RM384 landed as `locations.SNAPSHOT_REPO_IDS` (not `download`), which the lead takes for M8's pin; RM386's publish pinning is the enricher's HuggingFace publisher, which the registry does not use. Still before the cut: two regenerated examples and audit round 3.

**The cut, 0.8.0 (`edf2661c` on `0.8`, `e97339a3` on `main`, 2026-11-05)**: no behaviour change since `c90e6d98`. Not on PyPI and not tagged yet (both the maintainer's; the tag follows the publish), so the 0.28 branch keeps its git source until then. **Published and tagged the same evening** (PyPI 19:56 UTC, `v0.8.0` = `e97339a3`, package sources identical to `edf2661c`): the git source can give way to the PyPI floors, told to the lead. Three things the final guide and `RELEASE_RECORDS["0.8.0"]` change in this map:

- **M3 is wrong on one point: `content_signature` does move, for some modules.** The record's `content_signature` axis is `True`, from RM363's correction: `studies`, `haplotypes`, `pharm_variants` and `heteroplasmy` now store a primary-assembly contig bare (`chr12` → `12`, `chrM` → `MT`), so a module that wrote `chr`-prefixed contigs on those tables gets a new `content_signature` on the sweep's recompile (no upstream example does). The successor is a PATCH of the same module, so `409 duplicate_content` does not fire, but the predecessor's claim stays (only a purge frees it), and until such a module is swept, a same-data upload under another name signs differently and is not caught as a duplicate. Both corrections (RM363, RM361's `:None` key) state `requires=None`, so `declared_movement` keeps them for every module: the sweep reaches the whole catalog, as M3 already expects. To size it, a catalog query for published versions whose four tables carry `chr`-prefixed contigs, for the lead.
- **`toolchain_differs` is the normal case, not a one-off.** The compiler's own lock is now polars 2.1.0 while just-dna-lite stays on polars 1.x (polars-bio caps `<2`), so one spec under one `compiler_version` has two digests. Content is compared by `content_signature`; the registry compares no digest against a recompile, and our client's `verify_manifest` is unchanged at 0.8 (a hash check, no toolchain), so nothing here breaks. Polars 2 goes in with 0.28 (the lead, 2026-11-05).
- **The pm's three cut items, checked:** RM342's `toolchain_differs` lives in the recompiling `verify`, not in `integrity.verify_manifest`, whose signature and checks are unchanged; nothing to do. RM304 adds `compilation.vrs_version` to the manifest through upstream's model, and our lock (ga4gh-vrs 2.3.3) meets the `>=2.3.3,<2.4` floor; nothing to do. RM347/RM353 are the enricher's HuggingFace publisher, which the registry does not call (no `upload_module` or `publish_reference_snapshot` in `src/`); nothing to do.

**The release candidate `c90e6d98` (2026-11-05)**, read §§ 1.41-1.43 and § 2's changes: nothing new to build. RM395's `draft_repeat_loci(catalogue=None)` now resolves the STRchive lane ambiently, but `services/drafting.py:318` refuses a draft before calling it when the lane is not present, so `None` never reaches it. RM393 helps M12: a rederive that did not read the back-filling snapshot keeps the recorded rsID. RM394 is a lever for M12's dry run: `SubjectDrift.case` names seven arms, three of which (`moved`, `lost_allele`, `renamed`) want an operator's reading; the registry matches none of the reworded warnings. A reversed `resolution.csv` now has eleven new columns (step 21), read through upstream's models here.

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
  **RM378 parked** after the 0.8.0 cut (their `6934fd3e`, 2026-11-05), no longer in 0.9: RM377's phrases stay our
  way to tell the refusals apart, and their triage unparks RM378 if we need to tell apart a refusal those two do not
  cover (RM382's third strict arm does not need it: M14 reads `allele_mismatches`, not the sentence).
  Last checked: 2026-11-05.

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
- **S131** (filed 2026-11-05, appended to the compiler checkout's inbox, uncommitted): the PGS Catalog
  client's pace has no public name (`pgs._REQUEST_INTERVAL`, `self._gate`, both private), so the lead's C8 leg
  on 0.28 (`ffe263d`: one `PacingGate` per process, a fresh `PgsCatalogClient(gate=...)` per check) reads the
  private interval. Asks for (a) a public interval or (b) a public `gate`. **Answered 2026-11-05**: filed as
  RM396, a public gate and interval on six clients, the private names kept as aliases. **Parked** by their pm
  (`a617b4f3`): our read of `pgs._REQUEST_INTERVAL` stays the answer, and no patch renames it. Tell their triage
  to unpark it when we need a second client's pace (or `clingen_allele`'s), or a private name we read is about
  to be renamed.

- **S132** (filed by the lead, 2026-11-06, from the 0.28 rederive sweep). **Answered** (their `819553ea`, unpushed):
  the six moved insertions are RM267's class, fixed by 0.8's snapshot (dbSNP's SPDI matches the 0.8 spelling for all
  six), so accepting them is ours; the 23 undecided are RM385 (0.9); the 11 `lost_allele` are their defect, **RM400**,
  the next patch on `main`, both halves together, so the four refused modules should clear on a re-derivation under
  it; (a)(b)(d) are **RM398**, parked (unparks when a release plans a snapshot move, or on a second report); (e) is
  **RM399**, a release declaring a moved snapshot, in 0.9. The lead took it into desk #218: the six and the 23 for
  `--accept-drift` now, the four held for RM400.
- **S133** (filed by the lead, 2026-11-06, the sweep's live-lookup cost). **Answered** (their `ec7752a8`, unpushed):
  **RM401** (batch the live link and the REST witness) and **RM403** (log every retry and give-up) in the next patch;
  **RM402** (no live Ensembl ask for an rsID the snapshot answered and RM382 rejected) waits on RM401 and a
  re-measure, likely superseded; **RM404** (`enrich()` takes the eutils client and the sequence proxy) in 0.9;
  **RM405** (the offline floor) parked. Lowering the retry floor is declined until RM401 ships and is re-measured;
  the lead re-measures then. On `multimorbidity_aging_v3`, enrich already warns that 38 rejected genotypes fit the
  other strand; the lead passes that to its author.

Before S129, upstream's inbox held nothing from the registry open. The
registry's filings named in CLAUDE.md (S38, S81, S90, S92, S93) are answered in its history; S81, S90, S92 and S93
shipped in 0.7.0.

**Audit of the rest** (2026-11-07, read-only, over upstream's three history files): the registry filed 27 items (S1
to S134; S9 sits under our 0.5.2 heading but was filed from just-dna-lite). 14 are tracked already (S129-S133 above;
S7, S26, S37, S38, S62, S81, S90, S92, S93 in CLAUDE.md). Of the other 13: **adopted** S1 (RM17), S2, S8 (RM45),
S13 (RM44), S14, S25 (`manifest.readme`), S65 (`dropped_rows`), S124 (RM301), S126 (RM339); **levers** S91 (RM204,
`caches.lane_status()`, unused; ours at `services/enrich.py:693` still says `partial` where upstream says
`occupied`) = C5, and S95 (RM203, `PacingGate.spent`) left unread by C6's decision; **parked** S94 (the
peer-registry resolver rung, upstream's 0.7 idea-book, no RM: waits on serving answers from gated snapshots,
unparks if a thin client asks); **noted** S134 (the admin runs routes). Nothing waiting, nothing unanswered.
CLAUDE.md's S1, S2, S6, S17, S18 and S23 are our own inbox's ids, not upstream's.
