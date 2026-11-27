# Upstream ledger: the compiler's three packages

`just-dna-format`, `just-dna-compiler` and `just-dna-enricher`, released together from
`dna-seq/just-dna-compiler` with tags `vX.Y.Z` (the tag names the cut; each package carries its own version).
Kept by the liaison seat (`docs/seats/LIAISON.md`); another seat that meets a symptom in these packages sends it
there rather than writing here.

Watched on this machine from a clone outside the repository, `/data/sources/just-dna-compiler` (its line in the
liaison state file): `[seat.liaison.watch.compiler]` says each new tag, `[seat.liaison.watch.compiler-next]` each
commit to `docs/CHANGELOG.md` on the coming minor's branch (`main` between the 0.8.0 cut and the opening of `0.9`).

## Read mark

**`v0.9.0`** read (2026-11-26: all three at 0.9.0, cut `93160691` on their `cut/v0.9.0-2`, tagged `v0.9.0` at that commit; all three on PyPI 2026-11-26 21:11Z; read through their `docs/INTEGRATION_0_9.md` and the full suite run against it, see *The coming minor: format 0.9* below). **`v0.8.10`** read (2026-11-19: all three at 0.8.10, cut `65cfa25b`; all three on PyPI 2026-11-26 11:11Z, tagged `v0.8.10` at that commit shortly after; carries RM453, RM455, RM456). **`v0.8.9`** read (2026-11-18: all three at 0.8.9, cut `13b3be36`; all three on PyPI 2026-11-18 22:45Z, still untagged at 22:54Z; carries RM446-RM449, RM451, RM452). **`v0.8.8`** read (2026-11-16: enricher only, cut `655f1ebc`, untagged and not on PyPI when read; tagged at that commit and on PyPI 2026-11-17 02:17Z; carries RM445 alone; format and compiler stay 0.8.6). **`v0.8.7`** read (2026-11-14: enricher only, cut `3b65ab7a`, untagged and not on PyPI when read; tagged at that commit and on PyPI 2026-11-15 16:01Z; format and compiler stay 0.8.6). **`v0.8.6`** read (2026-11-13: tagged `2f03ab4`, the commit read at the cut, all three on PyPI). **`v0.8.5`** read (2026-11-12: tagged `c036c70`, the commit read at the cut, all three on PyPI). **`v0.8.4`** read (2026-11-11: tagged `36cbc20`, the commit read at the cut, all three on PyPI; installed by
registry 0.29.1). **`v0.8.3`** read (2026-11-10: tagged `725eb2b`, the commit read at the cut on 2026-11-09, all three packages at 0.8.3 on PyPI; RM425 to RM427 are past it). **`v0.8.2`** read (2026-11-08: all three packages at 0.8.2 on PyPI, tag `b98f7e9`, read commit by commit in the
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
- **Cut as `v0.8.3`** (`725eb2b` on their `main`, 2026-11-09; read untagged at 07:4x CET, tagged `v0.8.3` at that commit and on PyPI 2026-11-10): all
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
  **RM428** (filed 2026-11-10 from module-creator's S143, sized for 0.8.4, not landed): the GWAS Catalog pass asks
  v2 `/associations` with `size=1000`, which the Catalog answers 400 above 500, and 0.7.3's v1 path now answers 410, so
  `enrich_gwas` returns nothing on every installable release. Only `gwas.py` and the enricher's CLI call it; we import
  neither, and `enrich()` does not reach it. We only read a published `gwas_effects` sidecar (`services/catalog.py:251`).
  Nothing moves here. **Landed** as `f0433de` (2026-11-11): `_PAGE_SIZE` 500, a refused first page asked once more
  with no size, a `size_refusals` count on the pass's own report; nothing we read. Unreleased (0.8.4).
- **Cut as `v0.8.5`** (`c036c70` on their `main`, 2026-11-12; read untagged, tagged `v0.8.5` at that commit and on PyPI the same day): all three to
  0.8.5, floors `>=0.8.5`, the enricher's `tenacity` floor down to `>=9.0.0`. Carries RM432, RM434, RM436 and RM438,
  each read in this file (RM433 is a roadmap note only); no public name, field, table, flag or warning code. Two
  behaviours change for a direct caller: RM432's raises and RM438's withheld rsID; we call neither directly.
  Release record `0.8.5` (from 0.8.4, 22 reference modules): a measured zero on every axis, and it **does not
  measure** RM438's `resolution.csv` correction, so `declared_movement` will not act on it. Measured here: nothing
  published moves (RM438 below). Residuals filed as their RM439 and RM440. **For the lead at PyPI**: a patch (the
  weekly bump's, or the lead's own floor), and the five modules on pre-0.8 tables (`cancer`, `cardio`, `pathogenic`,
  `blood_groups`, `pharmgkb`) are re-derived on it, not before.
- **Their `main` past the 0.8.9 cut**: **RM453** (`0301397e`, merged `19a7cdb0`, 2026-11-18, for 0.8.10, a declared
  corrected derivation): `unplaced` on every spelling of a mirrored ins/del site now keeps both spellings filled (said
  once per rsID under the borrowed `rsid_expanded_to_multiple_loci`), as `undecided` or an empty cell does; a one-sided
  witness still fills only its spelling. This **removes 0.8.9's one new strict refusal**, online and offline alike
  (`unplaced` both ways is a witness that held no counterpart, e.g. ClinVar filing a deletion under a merged rsID). So
  under 0.8.9 our online re-runs can still refuse such a row; 0.8.10 will not.
  **RM455** (`e63a8d8c`, `5799c2c9`, `78b8fb3f`, built `97b1770c`, 2026-11-18, for 0.8.10; synced into 0.9 `4a238152`),
  enricher only, three hardenings: (1) a pull record whose bytes are not UTF-8 reads as *unreadable* in
  `download._pull_record`, `locations.pull_record_repo`/`pulled_from` and `snapshot_record_missing` instead of a
  `UnicodeDecodeError` traceback, which is the path `registry upgrade` and `warm-caches` read through
  `download.pulled_from_elsewhere`; a hardening for us, no code to change; (2) a `batch_size` below 1 is refused on the
  gnomAD, eutils, Europe PMC and PMC-id clients (nothing here sets one: `grep batch_size src/` is empty); (3) a new
  `CacheLane.payload_filename` (strchive, acmg) replaces two `lane.name == "strchive"` checks in their `cache rebuild
  --publish`; nothing here compares a lane by name. No floor reason of its own.
- **Cut as `v0.8.9`** (`13b3be36`, 2026-11-18 05:27, all three packages 0.8.9, floors `>=0.8.9` throughout, no
  third-party floor; on PyPI 2026-11-18 22:45Z, all three; no `v0.8.9` tag at 22:54Z): RM446, RM447, RM448, RM449 (a declared corrected
  derivation), RM451, RM452 (each read below). **Format moves to 0.8.9 for its release record alone** (no vocabulary,
  model or field moves; a 0.8.6 reader reads 0.8.9 output), and that record is what makes RM449 visible to us:
  `declared_movement` reads `release_records` from the *installed format*, so the registry must take all three at
  0.8.9 for `registry upgrade` to act on the correction. The record declares RM449 a correction scoped on
  `compilation.expanded_keys` (measured on their `pathogenic_clinvar`: `expanded_keys` 11 -> 9, two weights rows fewer)
  and RM451 an addition on `parquet_bytes`; `content_signature` moved in 0 of 21. Known issue **RM453** (for 0.8.10): an
  *offline* re-derivation leaves a mirrored site unplaced and strict refuses it; online clears it. **For the lead at
  PyPI**: a patch, floors `>=0.8.9` on all three; then cardio, cancer and pathogenic re-derive online under it, and
  `upgrade` should pick up superhuman@2.4.1 and polygon thrombophilia@2.0.1 by the record.
- **Their `main` past the 0.8.8 cut** (read 2026-11-17; now cut as 0.8.9, above): **RM446** (`6318392d`, enricher only, additive): a run
  reads `retired_mark(client)` before it asks and names a route retired only for a 410 met after that mark, so a reused
  client's earlier 410 stops telling a later run's plain outage to upgrade (RM361's sticky message itself unchanged).
  **For us a patch worth taking**: we are exactly that host, one shared `LookupClients` for the process's life, so on a
  long-running server one Ensembl or Crossref 410 would label every later outage on `/check`, the hint routes and
  publish enrichment as a retirement. It reaches us inside `enrich()` and the literature pass with no code of ours
  moving (our bundle is upstream's, so it has the counter). **RM447** (`86de38e9`, `1bbcd65f`, compiler only): a
  resolved-allele refusal on a row Ensembl REST answered now says REST serves an older dbSNP build (156 at release 116,
  the snapshot's dump 157) and qualifies `--rederive` to a host with the snapshot; pinned phrases stay, no column, code
  or vocabulary moves. Nothing here reads that sentence, so not load-bearing for us. Both sized as patches on their
  `main`; take at the cut. **Then, for the 0.8.9 cut** (their `a5289b86`, 2026-11-18 04:35, pushed, uncut):
  **RM448** (`55ccb701`, enricher): a witness holding one ALT of a multi-allelic indel site no longer withholds the
  site (S158's missing rows). **RM449** (`91eefe36`, `84a256ef`, `12b1bb00`, `43914f21`; a **declared corrected
  derivation**): at a site where an insertion and a deletion share allele strings, an rsID row's genotype fills only
  the spelling a witness placed; witnessed both ways or never asked, both stay and a warning says so
  once per rsID (named `rsid_genotype_reads_as_two_events` on their main, then **borrowed codes for 0.8.9**, below); witnessed neither, neither fills; an authored coordinate
  row wins over an expansion onto its exact key at a mirrored site (a paralog collision still refuses). The ClinVar
  drafter now writes indels by coordinate. **RM451** (`dae4e0c8`): `reverse` stops inventing a `resolution.csv` row
  for a coordinate row the table never filed (`resolution_loci` is `[]` there, not null); one upstream example digest
  moves. **For us**: RM448 + RM449 are what production's cardio, cancer and pathogenic wait on (a re-derive under
  0.8.9, since RM448 is in what the enricher writes); RM449's release record should make `registry upgrade` act on
  superhuman@2.4.1 and polygon thrombophilia@2.0.1 by itself. The new warning code needs nothing here: the sweep reads
  codes through `CARRIED_WARNING_CODES` and shows an unnamed one as `other`. `services/claims.py` reads
  `resolution_loci or []`, so `[]` vs null is the same to it; the prebuilt import's `reverse_module` gets RM451's fix.
  **RM452** (`9a8c7c89`, enricher): a NULL `start` in the Ensembl snapshot places nothing (one warning names the rsID)
  instead of raising `TypeError`; no published snapshot carries one (0 rows), so nothing for us now.
  **RM449's last shape for 0.8.9** (`e1714779`, `90e27c40`, `b9b4f8c7`, 2026-11-18): a recorded `undecided` on both
  spellings now reads as no verdict, so the expansion stays; `unplaced` on both (a witness's answer, online or offline)
  still fills neither, and **strict then refuses that row as unresolved** where 0.8.8 compiled it (measured upstream on
  `rs80356821` in their `pathogenic_clinvar`). The new code does **not** ship in 0.8.9: a format 0.8.6 reader refuses an
  unknown `warnings_summary` key, so the sentences borrow `rsid_no_hosting_locus` (no position written) and
  `rsid_expanded_to_multiple_loci` (one or more filled); format stays 0.8.6, the code arrives in 0.9. **For us**: an
  upgrade sweep under 0.8.9 can count more `rsid_expanded_to_multiple_loci` (a narrowed site counts as an expansion,
  the filled arms sit in `compilation.carried`) and can newly refuse an rsID-only indel row no witness placed either way.
- **Cut as `v0.8.8`** (`655f1ebc`, 2026-11-16, enricher only; tagged at that commit and on PyPI 2026-11-17 02:17Z): RM445 alone (read
  below); enricher floors stay `>=0.8.6`, no third-party floor; no release record. Upstream's INTEGRATION_0_8 now floors
  the enricher at `>=0.8.8`. For us a floor worth taking (the lead adopts it in 0.32.1): it is what makes `warm-caches`
  repair a pre-RM420 lane, a silent wrong answer under a current label.
- **Their `main` past the 0.8.7 cut** (now cut as 0.8.8, above): **RM445** (`1051670b`..`b78c44aa`, 2026-11-16, enricher only, a patch, uncut): a
  pull no longer places the hub's `release.json` over kept files nothing attests (a pre-RM420 pull did, so old bytes
  stated the new release); `cache pull`/`cache prepare` re-pull a pre-RM420 record (no `release_sha256`) even at an
  equal label and compare kept files with the listing (size, LFS sha256 up to 256 MiB), outcome `refreshed`; a pull
  never fetches beside a local build. New refusal: `ensure_*_snapshot` raises when `release.json` cannot be fetched
  and the cache is absent or unfinished (Ensembl now asks for one on every pull). Reaches us through `warm-caches` →
  `prepare_caches` (we read outcomes back, never the route), so it repairs our stale lanes on its own once installed.
  **Operator step before any `warm-caches`/`drop-caches` on either box**: read each pulled lane's `pull-record.json`;
  no `release_sha256` key means modules enriched against that lane since its date may carry old answers under the new
  label (upstream cannot say which). Lead told.
- **Cut as `v0.8.7`** (`3b65ab7a`, 2026-11-14, enricher only; untagged and not on PyPI when read): carries RM442 and
  RM444 (both read below), text only; no public name, field, warning code, outcome or raise moves; enricher floors stay
  `>=0.8.6`, no third-party floor. Nothing for us to change: it is an optional float, taken by the next weekly bump
  (2026-11-19) or the next lock, no floor raise needed (no behaviour we rely on moves). RM443 (S154) is parked for 0.9.
- **Their `main` past the 0.8.6 cut** (now cut as 0.8.7, above): **RM442** (`fd9763e`, enricher only): the AlphaGenome Atlas and AVI rows'
  `license` and `notice` strings corrected to the terms they quote (the Output Terms' own dates, 2025-06-25 and
  2026-10-09; the AVI training bar cited from Output Terms restriction 2, not the Additional Terms' prohibition 4). No
  licence axis moves and no gate reads `notice`. Reaches us as text only: 0.32's lane `terms` (5e55a19) passes the
  registry's fields through, so `/lanes/alphagenome_*` serve the new sentences once an enricher carrying it is
  installed; a module re-enriched after it gets the new `licensing.csv` text, so its `artifact.digest` moves and its
  `content_signature` does not (the sidecar is outside `SIGNATURE_INPUTS`). Nothing here restates either string.
  **RM444** (`35cfabad`, enricher only, from just-module-creator's S155): `grch37.recover_rsid`'s result *text* stops
  over-claiming (a `none` beside overlapping records no longer says dbSNP records nothing; a position-only `recovered`
  says so). No outcome or field changes. Nothing for us: `src/` calls `recover_rsid` nowhere (grep, 2026-11-14).
- **Cut as `v0.8.6`** (`2f03ab4` on their `main`, 2026-11-13; untagged and not on PyPI when read, tagged and on PyPI later that day): all three to
  0.8.6, floors `>=0.8.6`, no third-party floor. Carries RM439 and RM440 (read below) and RM437's doc half; no
  public name, field, table, flag or warning code, no behaviour change for a direct caller. Release record `0.8.6`:
  a measured zero. **Not a hard floor here**; worth taking before the lead's re-derive of the five pre-0.8 modules,
  since RM440's log line says which back-filled rsIDs that re-derive drops. Heard on PyPI by `watch.upstream-index`.
- **Their `main` past the 0.8.5 cut**: **RM439** (`2fe759a`): a variant row's `stat_significance` description says it
  is the module author's verdict across the evidence; a description only, as RM434. **RM440** (`5da19a3`): a
  re-derivation that drops a back-filled rsID on RM438's no-host arm now logs one warning (the count and the first
  five keys); no warning code, table unchanged. Reaches us in `registry upgrade`'s re-derive of the five pre-0.8
  modules: the line lands in the run's log and the sweep counts it under its logger's package, never by its
  sentence. Nothing moves.
- **Their `main` past the 0.8.4 cut**: **RM434** (`5e124df`, from longevity-loci's S147, for 0.8.5): `StudyRow.stat_significance`'s
  description says the level is the authors' verdict at their own test's threshold, and `p_value_num` is the column
  to threshold on a common scale. A description only, no digest moves. We name the column only as one of the 0.3
  columns `upgrade` back-populates and never restate its meaning. Nothing moves.
- **RM436** (`0ccd50f`, 2026-11-12, for 0.8.5, from just-dna-lite's S149): the enricher's `tenacity` floor drops
  from `>=9.2.1` to `>=9.0.0`, so it resolves beside `google-genai` (which caps `<9.2.0`); a private shim picks the
  backoff keyword by the installed constructor. We have no `google-genai` and lock tenacity 9.2.1, which still
  satisfies it. Nothing moves.
- **RM438** (open, a patch, for 0.8.5 if it lands first; from just-dna-lite's S151, S152 folded in): one hosting rule
  for both rsID back-fill paths. `enrich` keeps pick-and-flag but narrows candidates by the row's `alts`, else its
  genotype, so a row moves `ambiguous` → `resolved` only where one rsID hosts it; declared a **corrected
  derivation**. Their triage asked us to size the exposure. **Measured 2026-11-12 on production** (latest version of
  all 24 modules, downloaded read-only): 439,752 `resolution.csv` rows, **0 `ambiguous`**, 0 with
  `rsid_alternates`, so nothing published changes. But only 1,632 rows name a `source_release`: the three ClinVar
  panels `just-dna-seq/cancer` 2.0.0, `cardio` 2.0.0 and `pathogenic` 2.0.0 (141,331 coordinate-keyed rows between
  them) plus `blood_groups` and `pharmgkb` still carry pre-0.8 tables, never re-derived. **Their re-derivation
  is where RM438 bites**, so it is best run with RM438 installed. Polygon not measured (rehearsal data).
  **Landed** as `d71a850` and `9d08278` (2026-11-12, unreleased): `resolver._hosting_rsids`, private; their
  declaration names our 0 and an unmeasured resolved arm (a single back-filled rsID the genotype refutes now gets
  none). **That arm measured the same day**: 7 coordinate-keyed rows carry a snapshot (`cache`) back-filled rsID,
  all in `antonkulaga/smell` 0.1.1, each one's authored genotypes within the row's own ref/alts, so none is refuted.
  51,249 more carry a ClinVar back-fill, all in the three un-re-derived panels; ClinVar is RM438's fall-through,
  not narrowed by it.
- **Cut as `v0.8.4`** (`36cbc20` on their `main`, 2026-11-11 01:15 CET; read untagged; **on PyPI** when checked 2026-11-11, tagged `v0.8.4` at that commit later the same day): all three
  to 0.8.4, inter-package floors `>=0.8.4` (the compiler's source is unchanged; it moves only for the floor). Carries
  RM425 to RM428, each read above, their fence-test fix and their own lock bump; no published requirement moved, no
  field, table, flag or warning code. One public name after all (their CHANGELOG, corrected in `aec2b74`):
  `GwasCatalogClient.size_refusals`, which nothing here reads (we never build that client). Release record `0.8.4` (from 0.8.3, 22 reference modules): a
  measured zero on every axis, so `registry upgrade` acts on nothing. RM428's 0.7.4 was declined (their desk #252).
  **The lead waits on it**: the person's "rebuild once gwas fix drops in" (2026-11-11), floored as registry 0.29.1;
  told in `#just-dna-registry > upstream` 2026-11-11, once on PyPI. RM426's wording fix (`models/api.py:1181`,
  `docs/CLIENT.md:555`) can ride the same patch.
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

## The next minor: format 0.10 (consumers' preview, probed 2026-11-27)

Upstream's lead asked both liaisons to try their branch `0.10` at `992e85b1` before their first review round
(644035415; versions still read 0.9.0). Probed in `.worktrees/probe-upstream-0.10-992e85b1`: main at `b83ce89`
(0.35.0), the three packages pointed at `992e85b1` by a `[tool.uv.sources]` block that is never committed, plus
targeted calls. Filed **S163-S165** (uncommitted in their inbox) and answered in their thread (644037290). The full
suite result goes below once it ends.

| # | Item | What it does to us | State |
|---|---|---|---|
| B1 | **RM468** answer store (our S162): live answers in a per-host SQLite under the cache base, **on by default** | `enrich()` opens a run per call and takes `answer_store=`. Our `/hint` lookups use the shared bundle outside any run, so each client's own run keeps its **first** release label for the life of the process (measured: 116 stays 116 after 117; v0.9.0 asked every time), and nothing but the environment or `.env` tells those clients where the store is | **S163**. Adoption: pass a configured `answer_store=` on every `enrich()` call (a setting of ours, never ambient), and fence the suite as upstream fences theirs (`JUST_DNA_ANSWER_STORE=""` autouse, their `enricher/tests/conftest.py`); on this box the default store is the shared cache base's `live-answers.sqlite3`. `/hint` waits on S163 |
| B2 | **RM399/RM441** `derivation_records.needs_rederive(old, new, table)`, three-valued, offline (our S156, S161) | Answers what our sweep's `declared_correction` arm probes by hand, and more: 0.8.4 to 0.9.0 names RM438 **and RM448**, which our probe never saw | **S164**: no `0.10.0` record on the branch yet (every span ending at 0.10.0 reads `None`), and which version a host should pass as `from_release` (we read `verification.json`'s `producer`; whether a gap-fill moves it is unmeasured). Adoption: replace the RM438 arm with the record, `None` staying *cannot say* |
| B3 | **RM385** `SequenceProxy(uri="fasta+file://...")` reads a local GRCh38 FASTA offline, binding per contig by digest (our S132, S157) | Could lift our indel hold (`needs_online_rederive`) offline. On this box's Ensembl primary assembly 10 of 25 contigs bind (4, 5, 8, 11, 14, 15, 18, 19, 20, MT), as upstream says; the first read digested the file in ~155 s niced and wrote `<fasta>.refget.json` beside it | **S165** asks for a structured per-contig answer and the name of a FASTA that binds all 25. Adoption: a sequence-URI setting passed as `sequences=`, and the hold decided per contig |
| B4 | **RM435** `StudyRow.effect_direction` (increase/decrease of the trait, not clinical direction); a studies parquet column and manifest counts | `services/claims.py` projects direction from the weights table only, so it never reaches the conflict marker, as upstream intends | Nothing beyond the floor, pending the suite and the 0.10.0 record |
| B5 | **RM460** `rsid_genotype_reads_as_two_events` on mirrored-site fills | New warning codes; we read codes by member, and the sweep's type table counts an unnamed code as `other` | Nothing beyond the floor, pending the suite |
| B6 | **Old-reader break**: RM435 and RM460 add warning codes, so a format reader older than 0.10 refuses a manifest naming them | Server, `registry-client` and console move together | A coordinated minor, as 0.8 and 0.9 were |

## The coming minor: format 0.9 (adoption map, 2026-11-27)

For the lead and the pm, for the release that floors 0.9. Read from upstream's `docs/INTEGRATION_0_9.md` at the cut
`93160691` (its § 3 has a registry list, which this map checks) and from our full suite run against the published
0.9.0 (`.worktrees/probe-upstream-0.9.0`, floors raised to `>=0.9.0`, `uv lock` moved only the three workspace
packages): **975 passed, 6 failed, 10 skipped**, niced, 1 h 59 min. No upstream break. **0.9 moves no compiled
output** (`RELEASE_RECORDS["0.9.0"]` measures every axis unmoved on 22 reference modules, `content_signature` equal in
44 of 44 pairs; no vocabulary, manifest field, parquet column or warning code), so `registry upgrade` recompiles
nothing for 0.9's sake and `enrich` with no new argument writes 0.8.10's bytes (their RM466 goldens).

| # | What changes | Where it lands here | Fix and cost |
|---|---|---|---|
| A1 | Floors: the enricher imports format 0.9's `parse_release`, so all three move together | `pyproject.toml` (four pins) | `>=0.9.0` on all three plus `uv lock`. A minor, so a coordinated cut by CLAUDE.md's lockstep, but nothing a module carries moved (their § 1.0) |
| A2 | `CLIENT_FIELDS` gains `snapshots` (`RemoteSnapshots`) | `shared_lookup_clients` leaves it `None`: `test_the_shared_bundle_actually_holds_clients` and both `test_the_timeout_setting_reaches_every_client_in_the_bundle` cases fail | Fill it, by our own "fill every field" rule. Build it **Hub-only** in our process (`proxy_url=None` is not enough: with none it reads `$JUST_DNA_SNAPSHOT_PROXY_URL`, so the registry could ask itself; pass `huggingface=True` with the env var left unset on our boxes, or a guard that refuses our own URL). A process-wide holder keeps the revision it first read until closed (their lead's answer, 2026-11-19); our lane routes resolve the head per read since 0.33. About 1 h with the guard and tests |
| A3 | `VariantHint.routes` (set only for a lane answered remotely) | `/hint/variant`'s model does not carry it: `test_every_field_the_enricher_reports_about_a_variant_survives_the_proxy` | Add the field (with its console mirror in `types.ts` and the SDK parity), `None` unless a lane was read remotely. 30 min |
| A4 | New lane `ensembl_rsid_index` (derived, built only when named, never published, not remote) | `.env.template` lacks its variable: `test_env_template_mentions_every_cache_lane` | One line. `warm-caches` must not build it by default (upstream's `named_only` says why: 42 min, 6 GB); building it on a box is an operator choice, and `rsid_index=` is then passed by path (S36's lanes do not need it) |
| A5 | **S36**: read `key_compare.KEY_COMPARES` for the lane proxy's compare per lane, table and column | `services/lanes.py` compares a cell exactly | The pm's decision, at this floor. Since RM454 the registry covers the local readers too (Ensembl `id`, ClinVar `rsid`/`chrom`/`gene`, constraint, MANE, PharmVar, PubMind, Open Targets) beside the remote lanes. Until it lands, upstream ships **RM459** as a known issue: a 0.9 client with our proxy set and Hugging Face off answers could-not-ask on gene lookups for clinpgx, cpic, drug_labels and civic. The largest item here |
| A6 | `enrich(rederive_subjects=..., verify_written_only=...)` (RM467, our S160) | `registry upgrade`'s re-derive re-asks every row of a held module | Pass the held module's subjects; cardio ~30 rows of ~75k. Selection by a declared correction's reach waits for RM441 (0.10). Optional for the floor release, the biggest saving for the next sweep |
| A7 | `enrich(clients=, sequences=)` (RM404) | We hand single clients per pass | Optional: pass the shared bundle whole; no client we pass is closed by the run. Not needed for the floor |
| A8 | `caches.lane_status(locations=...)`, `LANE_STATES` gains `stale` | Our `/caches` derives its own states (`lane_status` in `services/enrich.py`), so `stale` does not reach us; a URL in `locations` raises, and we pass none | Nothing at the floor; their § 3 item 3 (replace our loop) is a choice for later |
| A9 | RM470: ClinVar-GKM builds from its `v1/1.2` line; a retired line raises `ClinVarGkmRetired` (a `ClinVarGkmUnavailable`) | `clinvar_gkm` is a pulled lane here; the published snapshot stays readable | Nothing; a rebuild of that lane works only on 0.9 |
| A10 | `just-dna-compiler[compat]` / `just-dna-enricher[compat]` = `polars[rtcompat]>=1.42.0` | Our own `compat` extra (`polars[rtcompat]`, for whale's CPU without AVX2) | Optional: point ours at `just-dna-enricher[compat]` to stay in step with upstream's floor. Whale works either way |
| A11 | `EnsemblSettings` refuses `batch_size` outside 1..200 and `batch_timeout <= 0`; private names gone (`_BatchResolver`, `_resolve_rsids`, `_held_by_one_run`, `_ensure_opentargets_snapshot`, `_PART_COUNT_KEYS`) | We pass only `timeout`, and import none of the names (grep, 2026-11-27) | Nothing |

**The sixth failure is ours and not 0.9's**: `test_publish_recovery.py::test_a_version_that_never_appears_gives_up_at_the_deadline_and_says_so`
saw 1 poll inside its 0.3 s deadline under the niced full run and passes alone (1.3 s). A timing margin to widen.

**Checked by the lead against 0.35** (644018585, 2026-11-27): A1, A2, A3, A5, A10 done on branch `0.35`; A4 after its suite (landed `2d0394c`; 0.35.0 merged `f8c6013`, suite 981 passed, publish asked on desk #471); A7-A9, A11 nothing. A2 is Hub-only by `proxy_url=""`, which never reads the variable (the map's wording above was loose). **A6 corrected**: production's cardio, cancer and pathogenic tables carry no `source_release` column at all (57,756 / 70,808 / 309,394 rows, measured on whale), so the sweep re-derives them whole and RM467 saves nothing there; it goes in a later release. **The order note is moot for production**: November's refusal ran under 0.33.0 and kept nothing, so no held re-derivation exists to lose.

**Order, per box**: the 0.9-floor release reaches a box only after that box's 0.34.3 sweep has finished, since a
held re-derivation (`services/held.py`) is not reused across enricher releases. Optional on a box that reads
remotely: `duckdb` `httpfs` preinstalled (their § 1.2); none of ours reads remotely through the enricher yet.

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

- **0.9 pre-cut try** (2026-11-19, their ask 641755221; reported 641766434): full suite against all three tiers
  from git at `d9c578ae` (they install as 0.8.10): 975 passed, 6 failed, no upstream break. Ours at the 0.9 floor:
  `CLIENT_FIELDS` gains `snapshots` (`RemoteSnapshots`), left `None` by `shared_lookup_clients` (3 tests); the
  variant hint report gains `routes`, not passed by our proxy (`test_hint_proxy` parity); new lane
  `ensembl_rsid_index` absent from `.env.template` (`test_startup`); `test_deploy`'s constraints `KeyError` is an
  artefact of git sources. Asked: is `snapshots` process-shared state or per run. Lead and pm told (641766463).
  **Answered** (641766510, their liaison from `remote.py` on `origin/0.9`, their lead to confirm): `RemoteSnapshots`
  is a thread-safe holder like the HTTP clients (the proxy httpx client, a Hub client, one duckdb connection and one
  pin per lane, per-lane locks, a cursor per query), so it may be shared process-wide. Two facts for our design: a
  lane's pin lives as long as the holder, so a process-wide one keeps the revision it first read until closed and
  rebuilt (ours since 0.33 resolves the head commit per remote read); and with no proxy URL it reads
  `$JUST_DNA_SNAPSHOT_PROXY_URL`, so in the registry's own process it should be Hub-only, or it may ask itself.
  **Their lead confirms** (641766625): a process-wide holder in `LookupClients.snapshots` is the intended shape;
  `close()` waits for lookups in flight. A long-lived host rebuilds the holder to follow a new revision; in our own
  process pass `proxy_url=None` with the variable unset, or Hub-only; close it after the last lookup
  (their `INTEGRATION_0_9`). Our six failures need nothing from them.
- **S160, S161, S162** (filed 2026-11-19 at the lead's request 641717159, the person's word on re-derivation cost;
  uncommitted in their inbox): S160 row-level re-derive in the enricher (only the rows a correction or a stale
  `source_release` reaches, verify passes over those only; cardio ~75k rows for ~30 moved, 12.5 h `verify_ref` off,
  ~37 h on); S161 an enricher release record declaring derivation changes, so a kept re-derivation survives an
  enricher patch that declares none; S162 a persistent online-answer cache keyed by source release. Learned while
  filing: an ordinary `enrich` gap-fills and never re-asks, so drop-and-refill is open to us today (the lead's
  measurement on cardio).
  **Answered** 2026-11-19 (641761537; their `1fc67e47`, archived), all three filed as minors, release undecided:
  S160 is **RM467** (a re-derive scoped by a reason or a list of rows; verify over only the rows a run wrote, as an
  option); S161 folds into **RM441**, planned for 0.10, on the condition that every release record states its
  re-derive answer, "nothing to re-derive" included; S162 is **RM468** (a store of online answers keyed by the
  answering source release). The fact we asked: today verify does **not** skip carried rows on drop-and-gap-fill;
  it reads them too (`orchestration.py`), so drop-and-refill saves the resolve, not the verify.
- **0.8.10 cut asked** (2026-11-19, at the lead's request 641716768; sent 641716854 in `agent-chat > upstream`, a
  message, not an S item): all three tiers. Measurement: cardio's spec from production's refused 2026-11-17 run,
  re-derived online (enricher 0.8.8), strict under compiler 0.8.9: RM449's duplicates gone, 4 mirrored ins/del rsIDs
  `unplaced` both ways by ClinVar (rs551348450, rs759332741, rs771806027, rs786205353) refused by the RM453 case online,
  where their known-issue note says offline; a 5th (rs1452575772) is RM448, fixed by a 0.8.9 re-derive. Also asked:
  is RM453 the whole online story. Production's upgrade waits for 0.8.10 (registry 0.34.1 floors 0.8.9 meanwhile),
  since RM455 moves the enricher and a held re-derivation is not reused across enricher releases.
  **Answered** (641717086): their lead takes the 0.8.10 cut, all three tiers, once two things land on their main: the
  fix for main CI (red since 2026-11-05), and triage/pm's check that RM453 covers our four online rsIDs (with a fix on
  main if not), which is also the answer to (2). Main holds RM453 and RM455. Publishing is their person's step; no date.
  **Their pm on (2)** (641718057): RM453 covers the four sites by construction (the compiler reads only placement
  verdicts, online or offline; no verdict combination leaves a row unpositioned now; online the likelier cause is
  ClinVar holding neither spelling). No promise of no other strict refusal, but measurable today: the enricher moved
  only bookkeeping since 0.8.9 (RM455), so an 0.8.9 re-derive resolves as 0.8.10's would, and compiling the existing
  re-derive with main's compiler should leave only rs1452575772 (RM448). **0.8.10 cut** (641746186, 2026-11-19;
  `65cfa25b`, RM453, RM455, RM456), checks green; on PyPI 2026-11-26 11:11Z, all three, tagged `v0.8.10` at `65cfa25b` the same hour (their main's package sources unchanged since the cut); the lead told. Additive enricher names
  `CacheLane.payload_filename`, `net.check_batch_size`; `MirroredSettlement.withheld_all` (0.8.9) removed; nothing
  here uses it.
- **S158** (filed 2026-11-17 at the lead's request, 641258676; uncommitted in their inbox): production's 0.8 catalog
  upgrade (online, `verify_ref`) refused cardio, cancer and pathogenic as `compile_failed`. On cardio 21 of 22 strict
  errors are `Duplicate (variant, genotype)`: the SNP-core fill expands an rsID-only row's indel genotype (`C/CT`) onto
  both spellings Ensembl lists at one position (`C>CT` and `CT>C`), and the second lands on a coordinate row the ClinVar
  drafter authored there for another VCV. All 21 are one-base ins/del pairs, the colliding locus the one ClinVar did not
  witness. **Not filed as the lead first worded it** ("never place on an `unplaced` locus"): `unplaced` is the witness's
  answer, not a refusal, and 5,750 cardio rsIDs carry only `unplaced` loci, so such a gate would unplace them all. Asked
  for one of: an ins/del-ambiguous genotype is ambiguous unless a witness answered `same_event`; an authored row wins
  over an expansion onto its key; the drafter writes the coordinate for an indel rsID. The 22nd (`rs1452575772`) has no
  `resolution.csv` row at all, not even `not_found`; asked whether a run can end with a subject neither placed nor
  marked. Not fixed on their `main` at `05abe19a`. The cost side is ours (a refusal after the re-derive drops it), with
  the pm as a 0.33 candidate (641258690).
  **Addendum 2026-11-18** (lead's 641398661, production's log): cancer (25+) and pathogenic (14+) refuse the same way,
  every duplicate an indel; pathogenic also has 12 unresolved rsIDs, and the four checked each had a `clinvar`-authority
  `resolved` row in the stored pre-0.8 table, none after re-derivation. Asked whether re-derivation drops a ClinVar
  placement Ensembl lacks without a `not_found` row, and what the drafter should author if so.
  **Answered 2026-11-18** (their `d611a73f`, 641407999): both halves are defects, reproduced on their `main` with an
  online `verify_ref` run, filed high as 0.8.x patches. **RM448**: the missing rows are not a dropped ClinVar placement;
  Ensembl holds `rs1452575772` as `A>AC,AT` and ClinVar as `A>AC`, and RM267's witness reads Ensembl's other insertion
  as a disagreement and withholds the whole locus (our run log should say `Placement disagreement` for those ids;
  reproduced for all four). **RM449**: the duplicates, and the silent case is real (an rsID row alone compiles under
  strict with its claim on both `C>CT` and `CT>C`); our remedy 1 recommended, 3 beside it, 2 rejected as hiding the
  silent case. Their pm sizes both now. **For us**: the three production modules wait on that patch; the retry is
  0.33.1's kept-spec path once a re-derive under the fixed enricher is not needed (RM448 changes what a re-derive
  writes, so that retry likely has to re-derive after all). Lead told.
  **RM449 on the catalog** (lead's 641415076, passed to their triage 2026-11-18): 2 of 69 latest 0.8.x-compiled versions
  carry the silent case: prod `just-dna-seq/superhuman@2.4.1` `rs766212849` `A/A` protective, placed on `A>AAACTT`
  (hom-ref) and on `AAACTT>A` (homozygous deletion); polygon `thrombophilia@2.0.1` `rs1572088853` `C/CC`. Their fix
  reaches these only by a recompile (a corrected derivation, so `registry upgrade` once its release record says so).
  6,183 single-locus `unplaced` rows across the catalog are not this: `unplaced` there means one witness, by design.
- **S157** (filed 2026-11-16 at the lead's request, 640870607, from desk #330's measurement): `enrich()` builds
  its one `SequenceProxy` at `DEFAULT_SEQREPO_URI` and takes no URI or proxy, so a re-derivation cannot read a
  local reference; one remote read is about 0.34 s, and cardio (57,756 rows) took 6.9 h with `verify_ref` and
  3.4 h without, same table. Asks a seqrepo URI or proxy through `enrich()`, ideally a GRCh38 lane. Filed as
  the online half of their **RM385** (a local reference for offline runs, in 0.10's scope). Not urgent.
  **Answered 2026-11-16** (their `c0671870`, 640872037): online is **RM404 in 0.9**, decided:
  `enrich(..., sequences: SequenceProxy | None = None)` replaces the per-run proxy, and the minter, `verify_ref`
  and left-alignment read through it, so a proxy built with `uri="seqrepo+file:///…"` serves a re-derivation.
  Our environment must then carry `biocommons.seqrepo`, which the enricher does not install. `offline` still
  outranks an injected proxy, so offline and the GRCh38 lane stay RM385 (0.10). A minor; nothing in 0.8.x.
  Lead told.

- **S156** (filed 2026-11-16 at the lead's request): `services/upgrade.rederive_converged` compares a table's
  `producer` with the *installed* enricher because nothing installed says which release last changed a derivation
  (no derived-table axis, RM441; no record at all for an enricher-only patch, 0.8.1 and 0.8.7). So every enricher
  patch re-derives every module whose table carries a reason (hours online per ClinVar panel; zero such modules on
  2026-11-15). Asks RM441's design to answer it too: a record for every release (an enricher-only "no derived table
  moved"), or a per-table "newest version whose derivation could differ" readable offline. Our side, once it ships:
  compare `producer` to that.
  **Answered 2026-11-16** (their `0431e934`): taken into **RM441 as a fourth ask**, a minor in 0.9, one design with
  RM399. Their fact: release records live in `just_dna_format`, which an enricher-only patch does not release, so a
  record per enricher patch needs a format release each time or records moved into the enricher; a per-table constant
  in the enricher is readable from the package that moved. Which side holds it is decided in the design. Our
  over-derive default stays until it ships. Lead told.
  **Corrected the same day** (640579065): their pm sized it inside RM441 with the answer held **in the enricher**, a
  per-table value beside `CACHE_LANES`; RM441 and RM399 are now *proposed for 0.10*, not 0.9, placement theirs (their
  desk #326). Lead told.
  **Placed** 2026-11-16 (640865880, their pm `8076cf54`): RM441 with RM399 in **0.10**, after the enricher-only 0.9;
  desk #326 applied on its default, the maintainer may still veto.

- **S154** (filed 2026-11-14 at the lead's request, roadmap C5): `caches.lane_status()` resolves every lane from its
  env var or default directory, and we pass configured paths to each resolver and never export them (two apps per
  process in the suite), so composing it would report on the wrong directory for any configured lane. Asks
  `lane_status(lanes, locations: Mapping[str, Path | None] | None = None)`; every resolver already takes the override
  as its first argument (all seventeen, checked on 0.8.6); also asks whether `load_dotenv_file` passes through. Our
  side, once it ships: `services/enrich.lane_status` composes it and drops its own loop.
  **Answered 2026-11-14** as **RM443, a minor** (0.9 at the earliest; their `f65c2a04`, unpushed). They add: every
  `resolve()` exports the whole `.env` into `os.environ` by design, so a status call through it writes the process
  environment today; the `load_dotenv_file` passthrough is decided in the same change. Keep our loop until it ships. Lead told.

- **S153** (filed 2026-11-12 at the pm's request for 0.30.1; their triage told): no release-record axis covers a
  derived table, so 0.8.5's record reads as "nothing moved" though RM438 corrects `resolution.csv`. Asks: an axis
  for derived tables, a `requires` that names the reach, RM438 declared on it in the next record. Our side, once it
  exists: `declared_movement` acting on that axis means a re-derive, not a recompile.
  **Answered 2026-11-12** as **RM441, a minor** (their pm sizes it; 0.9 at the earliest). Two design points: a new
  axis would join `RECOMPILE_DRIVING_AXES` by default, so it needs a re-derive route of its own; and RM438's reach is
  `None` (not stated) in today's `requires` grammar, which our `declared_movement` keeps, so a sweep would over-reach,
  bounded at one PATCH per module. Pm told.

- **S145 / RM430 made a 0.9 zone** (2026-11-15, their maintainer; asks 1-7, ROADMAP `5ddfd16f`): their readers go
  local disk, then **our lane proxy** if a host configures it (explicit, unset by default), then Hugging Face. Our lead
  answered the interface (640484735: `/lanes/{lane}/{table}`, fall through on 429/404/503/504/timeout, never on 422;
  polygon for their trial). Their pm measured the polygon (640494791): 0.22-0.37 s, plus three findings relayed to our
  lead (stale polygon ClinPGx; an Ensembl id-only lookup scans locally for 21.5 s since `remote_needs_position` guards
  remote reads only; chrom x start batches are a cross product).
  **RM461** (`c85ed125` on their `0.9`, 2026-11-26, RM430's rest, read): their `RemoteRoute` now carries our proxy's `release_unreadable` (served on every lane reply since 0.33), kept when every reply of a split agrees; a split now takes the column holding the most values (`start` on a tie), which our route answers on any key column under `lane_max_keys`; their `caches.lane_status` refuses a URL in `locations`, and we call only our own `enrich.lane_status`. Nothing moves here. **RM458, RM462, RM463, RM466** (0.9 branch, same day: the group preflight reads the pulled manifest, `lookup_variant` asks remote ClinVar twice at most, the public per-run sequence view, goldens for `enrich` with neither new argument) wait for the 0.9 cut, as planned; the duty run's `affects` on each named the paths, not a change we must make before then.
  **RM454** (`9a0f91a7`, merged `ae2dfc0a`, second part `1ab11fdb`, 0.9, 2026-11-26; `key_compare`, read early for S36): `KEY_COMPARES` now declares the local readers' keys too (Ensembl `id`, ClinVar `rsid`/`chrom`/`gene`/citations, constraint, MANE, PharmVar, PubMind, Open Targets) beside 0.9's remote lanes, each reader building its SQL from its entry; gene keys fold by `gene_key` on both sides (Unicode whitespace and casefold), contigs by the format tier's reading. For S36 at our 0.9 floor: the lane proxy reads its compare per lane and table off that registry, so more of our `/lanes` tables get a declared compare than when the pm decided S36; read each entry, never a list of ours. **RM467** (`93cd4955`, merged `172ef801`, 0.9) is our **S160**: `enrich(rederive_subjects=[...])` re-asks only the named `variant_key`s and carries every other `resolution.csv` row byte for byte (`reasked`, `rederived` as `SubjectDrift`); `verify_written_only=True` verifies only fresh rows, the scope recorded in `verification.json`. Both default off. For `registry upgrade` at the 0.9 floor: a held module's re-derive can name its subjects instead of re-asking ~75k cardio rows; selection by a declared correction's reach waits for RM441 (0.10). Lead and pm told.

- **S145** and **S146** (filed 2026-11-11, appended to `/data/sources/just-dna-format`'s inbox, uncommitted; their
  triage told in `agent-chat > upstream`): the lead's 0.30 handoff (remote keyed lane reads). S145: no lane reads
  remotely through the enricher, since a URL collapses in `Path`, every `resolve_*_reference` and
  `snapshot.read_release` answer `None`, and the connectors check locally; plus an rsID index for the Ensembl split
  repo, keys on the whole-table readers (ClinPGx, drug labels, CIViC, ClinVar GKM), a keyed Open Targets function, and
  fsspec in `read_local_scores`. The lead measured the keyed SQL pruning over `hf://` (ClinVar 3.1 s / ~2.4 MB,
  resolver by position 3.5 s / ~5.4 MB of 200 MB). S146: `gene_metrics.lookup_snapshot` and the CIViC row reader
  return `{}` / `[]` over an unreadable snapshot. Also learned: the ClinPGx and CPIC mirrors read anonymously
  (public, ungated); duckdb `httpfs` must be preinstalled on a server with no route to the extension repo.
  **Answered 2026-11-11** (archived, open, their pm sizes): S145 is **RM430** (asks 1-3; the format tier never fetches,
  so a remote `release.json` is read by the enricher, not `just_dna_format.snapshot`) and **RM431** (asks 4-7); S146
  is **RM432**. Lead told.
  **RM431, first part on `0.9`** (`f3b8c657`, 2026-11-18, unreleased): `mitomap_miss` now declares a `stale_reason`
  from `stale_parents` (a moved ClinVar or MITOMAP parent makes `cache status` say stale; a gone parent leaves it
  present), and a walk over `CACHE_LANES` holds every lane with parents to one. Not asks 4-7 of S145 yet (the remote
  reads). It is a parent-moved axis, not the builder-version one our `LaneAge` bandaid in `warm-caches` covers
  (CLAUDE.md, "One bandaid"), so the bandaid stays; re-check the retire condition when 0.9 is cut.
  **RM432 landed** (`ac3f1bc`, 2026-11-11, unreleased): `gene_metrics.lookup_snapshot` and `civic_snapshot_rows` raise
  `FileNotFoundError` on a reference with no parquet (no new name); inside the enricher the gene-metrics pass reads it
  as not consulted (offline it had written `not_found` rows for a snapshot it never opened), the CIViC refutation
  check skips with a could-not-read warning, the citations pass warns. We call neither reader directly; we reach
  them only through `enrich()`'s gene-metrics pass, whose reference we resolve first (`resolve_constraint_reference`
  already answers `None` without parquet), so the new arm is unreachable here today. Nothing moves; a direct keyed
  read in 0.30 catches it as "snapshot unreadable", never as empty.

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
