"""
Contract upgrade: migrate a published version's spec to the current `just-dna-format` contract and
re-publish as a new PATCH, never mutating the predecessor.

Three, increasingly manual, mechanisms — all re-publish through the normal server-side compile path
so `compile_success`, hashes, and the digest are produced by the trusted party:

  * **0.3 back-population (automatic).** The 0.3 axes are *additive* — a legacy module still
    validates — so a row carrying only the legacy `state`/ClinVar booleans is losslessly enriched
    with `direction`/`stat_significance`/`clin_sig` (and a trimmed `state`) via the format's own
    `VariantRow.upgraded()` derivation. Automates docs/UPGRADE.md step 3.
  * **Schema recompile (`recompile=True`).** Re-emit an already-on-contract module in the current
    parquet schema (e.g. after a minor bump that only moved the parquet shape). Non-lossy: the
    authored data is unchanged; only the compiled `artifact.digest` moves.
  * **Column/key trim (`trim=True`, LOSSY).** 0.4 made the row models *and* the `module_spec.yaml`
    blocks (`module:`/`defaults:`/`panel:`/`authorship:` + top level) `extra="forbid"`; older lax
    schemas only *warned* on an unknown column/key. `trim` drops such columns (variants/studies) and
    yaml keys so a legacy spec compiles. It discards data, so it is opt-in (CLI `--force`-gated).
    Registry-owned `module:` keys are never trimmed here — the always-on `normalize_module_block`
    handles them non-lossily at publish.

`studies.csv` gets no 0.3 back-population (`StudyRow` has no `state` to derive from) but is subject to
the column/key trim like `variants.csv` and `module_spec.yaml`.
"""

import csv
import io
import json
from pathlib import Path

import yaml
from just_dna_compiler.compiler import _FACT_TABLES, _TABLE_KINDS, AUTHORED_NON_KIND_TABLES
from just_dna_format.alleles import split_genotype
from just_dna_format.identity import parse_version
from just_dna_format.layout import sidecar_spellings
from just_dna_format.manifest import Contribution, GenePanelSpec, ModuleManifest
from just_dna_format.sources import SourceRow
from just_dna_format.spec import Defaults, ModuleInfo, ModuleSpecConfig, StudyRow, VariantRow
from just_dna_format.vrs import is_substitution
from pydantic import BaseModel, Field

from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.services.publish import (
    _REGISTRY_OWNED_MODULE_KEYS,
    publish_version,
)
from just_dna_registry.services.rebuild import (
    DeclaredMovement,
    RebuildVerdict,
    declared_movement,
    measure_output_drift,
    rebuild_verdict,
)
from just_dna_registry.specfiles import (
    PROVENANCE_FILE,
    RECOGNIZED_SPEC_FILES,
    RESOLUTION_CSV,
    SPEC_YAML,
    VERIFICATION_FILE,
    has_spec_data,
)
from just_dna_registry.storage.base import StorageBackend, version_key
from just_dna_registry.sweep_report import HELD_NEEDS_ONLINE
from just_dna_registry.version import contract_compatible, installed_compiler, installed_enricher

# The columns `VariantRow.upgraded()` may set, mirrored back into the CSV. `state` stays present
# (trimmed to a derived mirror of `direction`); the booleans are only ever set True or left blank.
_UPGRADED_COLUMNS: tuple[str, ...] = (
    "state",
    "direction",
    "stat_significance",
    "clin_sig",
    "pathogenic",
    "benign",
)


class UpgradePlan(BaseModel):
    """What a 0.3 upgrade of a single `variants.csv` would do (computed, not yet applied)."""

    total_rows: int = Field(description="Variant rows in the spec")
    upgradable_rows: int = Field(description="Rows whose 0.3 axes can be back-populated")
    migrated_variants_csv: str = Field(description="The rewritten variants.csv (== input if none)")
    changed_cells: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Column -> rows whose value this upgrade actually changed. Measured during the rewrite "
            "rather than inferred from `_UPGRADED_COLUMNS`, because which of those six move is a "
            "property of the module: a spec that already authored `direction` sees it untouched "
            "while `state` is rewritten on every upgradable row (S14's reporter measured exactly "
            "that). Columns with no change are absent, not zero."
        ),
    )
    added_columns: tuple[str, ...] = Field(
        default=(),
        description=(
            "Columns the rewrite appended to the header. Separate from `changed_cells` because a "
            "column can arrive and be empty on every row — true of `clin_sig` on a 0.2-era spec — "
            "which changes the file's shape while changing no value."
        ),
    )

    @property
    def needed(self) -> bool:
        return self.upgradable_rows > 0


def _csv_cell(value: object) -> str:
    """Serialize an upgraded field back to a CSV cell, matching the compiler's reverse writer:
    a True boolean becomes 'true'; None/False become '' (absent); strings pass through."""
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    return str(value)


def plan_variants_upgrade(variants_csv_text: str) -> UpgradePlan:
    """Compute the 0.3 back-population for a `variants.csv` string. Pure and idempotent: re-planning
    an already-upgraded CSV reports zero upgradable rows and returns it unchanged."""
    reader = csv.DictReader(io.StringIO(variants_csv_text))
    in_fields = list(reader.fieldnames or [])
    out_fields = in_fields + [c for c in _UPGRADED_COLUMNS if c not in in_fields]

    out_rows: list[dict[str, str]] = []
    changed: dict[str, int] = {}
    upgradable = 0
    total = 0
    for raw in reader:
        total += 1
        # Mirror the compiler's CSV loader: blank cells are absent (None), everything else stripped.
        cleaned = {
            k: (v.strip() if isinstance(v, str) and v.strip() != "" else None)
            for k, v in raw.items()
            if k is not None
        }
        row = VariantRow.model_validate(cleaned)
        # Preserve the original cells verbatim; only touch the derived columns, and only when the row
        # actually drifts (so an already-0.3 row is left byte-identical).
        out = {k: (v if v is not None else "") for k, v in raw.items() if k is not None}
        if row.needs_upgrade:
            upgradable += 1
            up = row.upgraded()
            for col in _UPGRADED_COLUMNS:
                cell = _csv_cell(getattr(up, col))
                # Compare before assigning: `out` still holds the authored cell, and a column the
                # spec never carried reads as "" here, which is what makes an arriving-but-empty
                # `clin_sig` correctly count as no change rather than as 990 of them.
                if cell != out.get(col, ""):
                    changed[col] = changed.get(col, 0) + 1
                out[col] = cell
        out_rows.append(out)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=out_fields, extrasaction="ignore", restval="")
    writer.writeheader()
    writer.writerows(out_rows)
    migrated = buf.getvalue() if total else variants_csv_text
    return UpgradePlan(
        total_rows=total,
        upgradable_rows=upgradable,
        migrated_variants_csv=migrated,
        changed_cells=changed,
        added_columns=tuple(c for c in out_fields if c not in in_fields),
    )


# A row CSV's allowed columns are exactly its row model's field names. just-dna-format 0.4 made the
# row models `extra="forbid"`; older (lax) schemas only *warned* on an unknown column, so a pre-0.4
# spec can carry columns a 0.4 compile now rejects. `--trim` drops them (lossy); without it such a
# version is reported blocked rather than crashing the planner.
#
# Every authored table kind, not just the SNP core: a PGx module carries `haplotypes.csv` and no
# `variants.csv` at all, and through 0.10 the trim/block pass simply could not see those files, so
# an offending column in one went unreported and then failed the recompile.
#
# **Read off upstream's own registries, never listed here** (0.27.1, the liaison's C4). The hand-kept
# list this replaced had drifted by four tables on 0.7 (`overrides.csv`, `expression_effects.csv`,
# `clin_sig_concordance.csv`, `clin_sig_authority_calls.csv`), each read by an `extra="forbid"` model,
# so an unknown column in one was neither trimmed nor reported and failed the recompile instead: the
# 0.10 failure above, back through a list nobody updated. `_TABLE_KINDS` (the authored annotation
# tables) and `_FACT_TABLES` (the derived sidecars, `sources.csv` among them) each carry their
# `(csv, parquet, model)` binding. Two categories are in neither and are named here, because upstream
# binds no model to them in those two: the SNP core (`variants.csv`, `studies.csv`, whose parquets are
# `SNP_CORE_PARQUETS`), named here, and the authored non-kind tables (the overlay, and 0.8's `meta.csv`
# and `model_organisms.csv`), read from `AUTHORED_NON_KIND_TABLES`, public from format 0.8.
# `tests/test_upgrade.py` holds every CSV in upstream's `_INPUT_FILES` and `_FACT_TABLES` to this
# roster, so a table upstream adds fails a test here rather than a recompile on a box.
#
# The licensing ledger is keyed by **every spelling**, so it is checked under whichever name a stored
# version actually carries. `normalize_spec` stores the preferred one, but this planner also runs over
# versions published years earlier, whose storage still holds the name of their own era.
_ROW_MODELS: dict[str, type[BaseModel]] = {
    "variants.csv": VariantRow,
    "studies.csv": StudyRow,
    **{csv_name: model for csv_name, _, model in (*_TABLE_KINDS, *_FACT_TABLES)},
    **{table.csv: table.model for table in AUTHORED_NON_KIND_TABLES},
    **dict.fromkeys(sidecar_spellings("sources.csv"), SourceRow),
}


def offending_columns(csv_text: str, model: type[BaseModel]) -> list[str]:
    """CSV header columns the row `model` does not recognize (what 0.4's `extra="forbid"` rejects)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    allowed = set(model.model_fields)
    return [c for c in (reader.fieldnames or []) if c and c not in allowed]


def trim_unknown_columns(csv_text: str, model: type[BaseModel]) -> tuple[str, list[str]]:
    """Drop columns the row `model` doesn't recognize, preserving the rest verbatim. **LOSSY** — the
    dropped cells are gone. Returns `(trimmed_csv, dropped_columns)`; a no-op (input returned
    unchanged) when there is nothing to drop."""
    reader = csv.DictReader(io.StringIO(csv_text))
    in_fields = list(reader.fieldnames or [])
    allowed = set(model.model_fields)
    dropped = [c for c in in_fields if c and c not in allowed]
    if not dropped:
        return csv_text, []
    keep = [c for c in in_fields if c in allowed]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keep, extrasaction="ignore", restval="")
    writer.writeheader()
    for row in reader:
        writer.writerow({k: (row.get(k) or "") for k in keep})
    return buf.getvalue(), dropped


# module_spec.yaml is a nest of `extra="forbid"` models (0.4). Each block trims against its model's
# fields. The `module:` block additionally tolerates the registry-owned keys — the always-on
# `normalize_module_block` removes those non-lossily at publish, so they are neither blocked nor
# counted as a lossy trim here.
#: The spec files whose *text* the trim/block pass rewrites. Everything else recognized (the logo,
#: `README.md`) is carried through as opaque bytes.
#:
#: This comment said `MODULE.md` until 0.14, and that was the package's only mention of a readme
#: filename — a convention with no reader, which cost a consumer two publish cycles guessing at it
#: (S5). The name is now `README.md` and `specfiles.README_FILE` is the one place it is spelled.
_TEXT_SPECS: frozenset[str] = frozenset({SPEC_YAML}) | frozenset(_ROW_MODELS)


_YAML_BLOCK_MODELS: tuple[tuple[str | None, type[BaseModel], frozenset[str]], ...] = (
    (None, ModuleSpecConfig, frozenset()),
    ("module", ModuleInfo, frozenset(_REGISTRY_OWNED_MODULE_KEYS)),
    ("defaults", Defaults, frozenset()),
    ("panel", GenePanelSpec, frozenset()),
)


def _yaml_offenders(doc: object) -> list[tuple[dict, str, str]]:
    """`(container, key, dotted_path)` for each `module_spec.yaml` key the 0.4 models reject, across
    the top level and the `module:`/`defaults:`/`panel:` blocks and each `authorship:` entry."""
    if not isinstance(doc, dict):
        return []
    out: list[tuple[dict, str, str]] = []

    def scan(block: object, model: type[BaseModel], prefix: str, tolerated: frozenset[str]) -> None:
        if not isinstance(block, dict):
            return
        allowed = set(model.model_fields) | tolerated
        out.extend((block, k, f"{prefix}{k}") for k in list(block) if k not in allowed)

    for key, model, tolerated in _YAML_BLOCK_MODELS:
        scan(doc if key is None else doc.get(key), model, f"{key}." if key else "", tolerated)
    authorship = doc.get("authorship")
    if isinstance(authorship, list):
        for i, entry in enumerate(authorship):
            scan(entry, Contribution, f"authorship[{i}].", frozenset())
    return out


def offending_yaml_keys(yaml_text: str) -> list[str]:
    """Dotted paths of `module_spec.yaml` keys the current contract rejects (registry-owned keys,
    handled by the always-on strip, are not counted)."""
    return [path for _, _, path in _yaml_offenders(yaml.safe_load(yaml_text))]


def trim_unknown_yaml_keys(yaml_text: str) -> tuple[str, list[str]]:
    """Drop `module_spec.yaml` keys the current contract rejects. **LOSSY**. Returns
    `(trimmed_yaml, dropped_paths)`; a no-op returning the input unchanged when nothing is dropped."""
    doc = yaml.safe_load(yaml_text)
    offenders = _yaml_offenders(doc)
    if not offenders:
        return yaml_text, []
    for container, key, _ in offenders:
        del container[key]
    return yaml.safe_dump(doc, sort_keys=False), [path for _, _, path in offenders]


#: The scales a contract gap comes in. `contract` is the only one that acts on its own, because it is
#: the only one where the stored parquet is a *different shape* from what this server now compiles.
GAP_NONE: str = "none"
GAP_PATCH: str = "patch"
GAP_CONTRACT: str = "contract"
GAP_UNKNOWN: str = "unknown"


class ContractGap(BaseModel):
    """How far behind the contract a published version was compiled under is, and how we know.

    **This replaces a boolean that was frozen at one era boundary, and the freeze is the lesson.**
    The predecessor asked "is `content_signature` absent", which is true only of a pre-0.5 manifest —
    so it answered *no gap* for every 0.5-era version the moment this server moved to 0.6, and the
    catalog-wide re-baseline the flag exists to automate silently became a no-op an operator had to
    know to override with `--force`. Measured at the 0.6 cut: 5 of 11 reference modules skipped. A
    one-era witness is a witness that stops being one, so this compares versions instead of testing
    for a landmark.

    `witness` says which comparison produced `scale`, because the two have different reach and a
    reader has to be able to tell "I compared 0.5.4 against 0.6.1" from "I found no signature, which
    only means older than 0.5". It is also the field that keeps `unknown` honest: a manifest whose
    compiler cannot be identified is neither current nor stale, and reporting it as either is how the
    original defect happened. Unknown does **not** act by default and is counted separately, so an
    operator sees the bucket and can aim `--force` at it deliberately.
    """

    compiled_under: str | None = Field(
        default=None, description="The compiler version that produced the stored artifact, if known"
    )
    current: str | None = Field(
        default=None, description="The compiler version this server would recompile with"
    )
    scale: str = Field(default=GAP_UNKNOWN, description=f"one of {GAP_NONE}/{GAP_PATCH}/{GAP_CONTRACT}/{GAP_UNKNOWN}")
    witness: str = Field(
        default="none",
        description="What decided `scale`: `compiler_version`, `content_signature`, or `none`",
    )

    @property
    def acts_by_default(self) -> bool:
        """Whether this gap is reason enough to re-publish without `--force`.

        Only `contract`. A **patch** difference must not act: the compiler patch is not a schema
        change, so re-publishing would mint a fresh PATCH per module and move every
        `artifact.digest` to record that we upgraded a dependency — the sweep would never be finished
        because the next patch release starts it again. That is what `--force` is for, and with the
        contract gap detected it is finally what its name says: an override, not the normal path.

        **Compiler 0.6.6 is the first patch to falsify the premise in that paragraph, and it is worth
        writing down rather than patching around.** Upstream RM121 shipped, in a patch, a fix to
        `manifest.stats.genes` — a published field this catalog *indexes*, so a 0.6.1-compiled
        table-only module really is stale in a way an operator would want found. The rule above still
        returns the right answer (`patch`, does not act): it says the parquet **shape** is unchanged,
        which remains true, and a version rule that made an exception for `0.6.6` would be dating a
        stored artifact by a landmark — the exact defect this class was built to end.

        So the honest gap is not in the scale, it is that *nothing* looks for the stale field. The
        durable answer is a **defect predicate, not a version exception**: for a stored version, do its
        authored gene-bearing tables carry a gene its `manifest.stats.genes` does not? Built in 0.21 as
        `services/rebuild.py`, and answered from the other side in 0.24 by format 0.7's release record,
        which declares that same RM121 change as a *correction* rather than leaving a consumer to
        notice. Neither is a version exception, which is what this paragraph was protecting.

        **What this property does NOT decide any more is the whole question.** `VersionUpgradePlan`
        composes it with the record, which can withhold a contract-scale gap that measurably moved
        nothing (`DeclaredMovement.refutes_a_contract_gap`) — the version comparison here was standing
        in for a measurement that had never been published, and where the measurement exists and is
        complete it wins. This stays as the fallback, and the fallback is not vestigial: it is the only
        answer for every artifact compiled before the first release that has a record at all.
        """
        return self.scale == GAP_CONTRACT

    def describe(self) -> str:
        """One clause naming the gap, for an operator report and for an immutable changelog entry."""
        if self.scale == GAP_CONTRACT:
            under = self.compiled_under or "a pre-0.5 contract"
            return f"compiled under {under}, this server compiles with {self.current or 'unknown'}"
        if self.scale == GAP_PATCH:
            return f"compiler patch differs ({self.compiled_under} → {self.current}), same contract"
        if self.scale == GAP_UNKNOWN:
            return "the compiler that produced it cannot be identified"
        return "already on this contract"


def stamped_compiler_version(manifest: ModuleManifest) -> str | None:
    """The bare SemVer out of `compilation.compiler_version`, or None if it is not one.

    The compiler stamps `"just-dna-compiler 0.6.1"` — a name and a version, not a version — and
    `"just-dna-compiler unknown"` when it cannot read its own metadata. So the last whitespace-separated
    token is the candidate and it is *validated* by parsing rather than assumed: an unparseable stamp
    (a foreign compiler, an `unknown`, a spelling upstream changes) has to reach `GAP_UNKNOWN` rather
    than crash a catalog-wide sweep or, worse, be read as up to date.
    """
    stamp = manifest.compilation.compiler_version
    if not stamp:
        return None
    candidate = stamp.split()[-1]
    try:
        parse_version(candidate)
    except ValueError:
        return None
    return candidate


def contract_gap(manifest: ModuleManifest) -> ContractGap:
    """How far behind the current compile contract this stored version is.

    Compiler against compiler, which is apples to apples: the stamp on the manifest is a
    `just-dna-compiler` version and so is what this process would recompile with. The *format* minor is
    the contract that actually moves the parquet schema, and comparing compilers inherits it — this
    workspace floors format and compiler at the same minor and upstream cuts them together (0.6.6 /
    0.6.6 as of registry 0.20; through 0.19 the enricher was free to move alone, which touches no
    artifact, and from upstream 0.6.5 even that stopped resolving apart).

    The rule is `version.contract_compatible`, unchanged and deliberately shared with the wire check:
    a differing MAJOR, or a differing MINOR while MAJOR is 0. If a 0.5 client may not exchange
    artifacts with a 0.6 server, then a 0.5-compiled artifact sitting in a 0.6 server's catalog is the
    same disagreement with nobody to report it to — which is exactly what a re-baseline fixes.

    Falls back to the pre-0.5 `content_signature` witness when the stamp says nothing, because that one
    still works where the stamp does not: the compiler began writing signatures in 0.5, so its absence
    dates a manifest without needing to parse anything.
    """
    current = installed_compiler()
    stamped = stamped_compiler_version(manifest)
    if stamped is None:
        if manifest.content_signature is None:
            return ContractGap(
                compiled_under=None, current=current,
                scale=GAP_CONTRACT, witness="content_signature",
            )
        return ContractGap(compiled_under=None, current=current, scale=GAP_UNKNOWN, witness="none")
    if current is None:
        # Nothing to compare against. Not "current" — this process cannot say, and saying so is the
        # whole point of the field.
        return ContractGap(
            compiled_under=stamped, current=None, scale=GAP_UNKNOWN, witness="compiler_version"
        )
    if not contract_compatible(current, stamped):
        scale = GAP_CONTRACT
    elif stamped != current:
        scale = GAP_PATCH
    else:
        scale = GAP_NONE
    return ContractGap(
        compiled_under=stamped, current=current, scale=scale, witness="compiler_version"
    )


class VersionUpgradePlan(BaseModel):
    """Everything a re-publish of one published version needs, plus a report of what would change:
    the 0.3 back-population (`variants_plan`), any lossy `--trim` column drops, and the prepared
    input file set. Internal to the upgrade service — carries raw bytes and is never API-serialized.
    """

    variants_plan: UpgradePlan
    dropped: dict[str, list[str]] = Field(
        default_factory=dict,
        description="What --trim removed (LOSSY), keyed by filename: CSV column names, or dotted "
        "key paths for module_spec.yaml",
    )
    blocked: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Columns/keys the current contract rejects that are still present (no --trim); "
        "the version cannot be re-published until they are dropped",
    )
    files: dict[str, bytes] = Field(
        default_factory=dict, description="Prepared re-publish inputs (empty when blocked)"
    )

    #: How far behind the current compile contract the predecessor is — the reason a catalog-wide
    #: re-baseline is `registry upgrade --apply` rather than a `--force` an operator has to know to
    #: pass. See `ContractGap`: only a `contract`-scale gap acts on its own.
    gap: ContractGap = Field(default_factory=ContractGap)

    #: Whether recompiling would actually produce a different manifest — the axis `gap` cannot see
    #: (0.21). A compiler *patch* moves no schema, so `gap` scores it `patch` and declines to act;
    #: upstream RM121 nevertheless changed `stats.genes` in one. `services/rebuild.py` recomputes the
    #: probed fields from these very `files` and reports the difference, so a measured gap acts under
    #: plain `--apply` and `--force` goes back to meaning *act despite the detector*. It also carries
    #: the corrections `declared` names, so what a re-baseline repairs reaches the changelog entry.
    verdict: RebuildVerdict = Field(default_factory=RebuildVerdict)

    #: What upstream's release record says the compile interval moved (0.24, format 0.7). The third
    #: term, and the only one that can **subtract**: a contract-scale version gap over an interval the
    #: record covers with every driving axis measured `False` moved nothing, so re-publishing would
    #: reproduce the stored bytes. See `DeclaredMovement.refutes_a_contract_gap`.
    declared: DeclaredMovement = Field(default_factory=DeclaredMovement)

    #: Whether the re-publish re-derives its resolutions rather than carrying them (M12): the stored
    #: `resolution.csv` holds a row that names no `source_release`, which no 0.8 run writes. See
    #: `resolution_needs_rederive`. Never a reason to act on its own; it says *how* an acting re-publish
    #: enriches.
    rederive: bool = False
    #: Whether that re-derivation needs the network: the module carries an allele that is not a
    #: single-base substitution, and offline 0.8 cannot left-align one (upstream RM385, until 0.9).
    needs_online: bool = False
    #: Recorded subjects the re-derivation re-asks: the run's size, and online its request budget.
    rederive_subjects: int = 0
    #: Why it re-derives, by `rederive_reasons` code, with the rows behind each (0.30.1). A reason that is
    #: not `cannot_say` is a reason to act on its own (the person asked that the sweep re-derive exactly the
    #: modules that need it, whatever their compiler gap) when `rederive_written_by` predates the installed
    #: enricher; a table the installed enricher wrote has converged and never acts on its reasons alone.
    rederive_reasons: dict[str, int] = Field(default_factory=dict)
    #: The enricher that wrote the stored tables (`verification.json`'s producer), or `None` unknown.
    rederive_written_by: str | None = None
    #: Whether those reasons act on their own: some reason other than `cannot_say`, from an older enricher.
    rederive_acts: bool = False

    @property
    def contract_acts(self) -> bool:
        """The contract gap's own verdict, after the record has had its say.

        The version comparison was standing in for a measurement nobody published. Where the
        measurement exists and is complete, it is the answer; everywhere else — an uncovered span, an
        unstamped compiler, a single unknown axis — the comparison stands exactly as before, which is
        every artifact compiled before the first release that has a record.
        """
        return self.gap.acts_by_default and not self.declared.refutes_a_contract_gap

    def would_act(self, *, recompile: bool) -> bool:
        """Whether re-publishing this version is worthwhile: it has 0.3 drift, trimmed something, was
        compiled under an older contract the record has not refuted, carries a **measured** output
        drift or a declared correction, or a `recompile` was explicitly requested. Never acts while
        blocked.

        Three terms that are deliberately not folded into one another, because they answer at three
        different grains. `gap` is a statement about **versions**; `verdict` is a measurement of this
        **artifact**; `declared` is upstream's record of what a **release** did. Keeping them apart is
        what lets the verdict refuse to act on drift it measured under the identical compiler, and
        what lets the record withhold a re-baseline the version comparison would have ordered — two
        distinctions neither of the others could draw.
        """
        if self.blocked:
            return False
        return (
            self.variants_plan.needed
            or bool(self.dropped)
            or self.contract_acts
            or self.verdict.acts_by_default
            or self.rederive_acts
            or recompile
        )


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def resolution_needs_rederive(resolution_csv_text: str) -> bool:
    """Whether a stored `resolution.csv` predates the snapshot switch, so the sweep re-derives it (M12).

    Detected, never flagged (*a migration detects its own trigger*): since format 0.8 (RM373) every row a
    run answers names the release that answered it in `source_release`, so a row naming none was
    written by a 0.7 run, against the old Ensembl repo. Upstream's upgrade order, step 5: an ordinary
    enrich fills gaps and leaves such a row as it was, and a table holding both releases' placements
    for one rsID refuses under `strict` (`rsid_placements_disagree`, RM374).

    **Half of the trigger, and the other half is a condition:** a row naming a release *other than the
    snapshot's* is the same staleness after the next snapshot move, and this does not see it. It
    matters when `just-dna-enricher cache status` reports an Ensembl release newer than the one a
    published `resolution.csv` names; until then every non-blank row is the current release's.
    """
    return any(not (row.get("source_release") or "").strip() for row in _rows(resolution_csv_text))


#: The re-derivation discriminator's arms (0.30.1, the person: "build some discriminator to determine which
#: items need rederivation"). Each is read off the stored `resolution.csv`, compared by value, never by a
#: landmark; a module carries every arm that applies, with the rows behind it.
REDERIVE_NO_SOURCE_RELEASE = "no_source_release"
REDERIVE_OLDER_SNAPSHOT = "older_snapshot_release"
REDERIVE_DECLARED_CORRECTION = "declared_correction"
REDERIVE_CANNOT_SAY = "cannot_say"

#: The authority a `source=cache` row names, to the snapshot lane whose release it would carry.
_AUTHORITY_LANES: dict[str, str] = {"ensembl": "ensembl", "clinvar": "clinvar"}


def installed_snapshot_releases(settings: Settings) -> dict[str, str | None]:
    """The release label of each snapshot a `source=cache` row can name, as this box holds it; `None` for a
    lane not held or whose label cannot be read (the arm is then `cannot_say` for its rows, never current)."""
    from just_dna_registry.services.enrich import cache_lanes, lane_presence

    present, lanes = lane_presence(settings), cache_lanes()
    out: dict[str, str | None] = {}
    for authority, lane in _AUTHORITY_LANES.items():
        where = present.get(lane)
        try:
            out[authority] = lanes[lane].release_label(Path(where)) if where is not None else None
        except Exception:  # noqa: BLE001 - an unreadable label is one honest "cannot say"
            out[authority] = None
    return out


def _authored_genotype_alleles(variants_csv_text: str | None) -> dict[str, set[str]]:
    """Every allele each `variant_key` (or rsID / coordinate) authors in a genotype, upper-cased."""
    out: dict[str, set[str]] = {}
    if not variants_csv_text:
        return out
    for row in _rows(variants_csv_text):
        alleles = {a.strip().upper() for a in split_genotype(row.get("genotype") or "") if a.strip()}
        if not alleles:
            continue
        for key in (row.get("variant_key"), row.get("rsid"),
                    f"{row.get('chrom')}:{row.get('start')}:{row.get('ref')}" if row.get("chrom") else None):
            if key:
                out.setdefault(key, set()).update(alleles)
    return out


def rederive_reasons(
    resolution_csv_text: str, variants_csv_text: str | None, installed: dict[str, str | None]
) -> dict[str, int]:
    """Why a stored `resolution.csv` needs re-deriving, with the rows behind each reason (0.30.1).

    * `no_source_release`: a row a source answered (not `authored`) naming no `source_release`, which no
      0.8 run writes. A table with no such column at all is entirely this.
    * `older_snapshot_release`: a `source=cache` row naming a release other than the installed snapshot's
      for its authority: the staleness after a snapshot move, which the 0.28 check did not see.
    * `declared_correction`: upstream RM438 (enricher 0.8.5, undeclared in its release record) changed the
      rsID back-fill at a position several rsIDs share to follow the row's genotype. Probed from the table:
      a coordinate-keyed row with a back-filled rsID whose ref/alts cannot hold every allele its authored
      genotype names is one 0.8.5 would no longer back-fill so. A necessary condition, so it can under-report
      (two hosting rsIDs, now withheld, are not visible here) but never flags a row 0.8.5 would keep.
    * `cannot_say`: a `source=cache` row whose authority's installed release cannot be read.
    Converges: a table re-derived on the installed enricher names the installed release on every answered
    row and back-fills only hosting rsIDs, so none of the first three arms fires again."""
    reasons: dict[str, int] = {}

    def add(code: str) -> None:
        reasons[code] = reasons.get(code, 0) + 1

    genotypes = _authored_genotype_alleles(variants_csv_text)
    for row in _rows(resolution_csv_text):
        source = (row.get("source") or "").strip()
        if source == "authored":
            continue
        release = (row.get("source_release") or "").strip()
        if not release:
            add(REDERIVE_NO_SOURCE_RELEASE)
            continue
        if source == "cache":
            authority = (row.get("authority") or "").strip()
            want = installed.get(authority) if authority in _AUTHORITY_LANES else release
            if want is None:
                add(REDERIVE_CANNOT_SAY)
            elif release != want:
                add(REDERIVE_OLDER_SNAPSHOT)
            key = row.get("variant_key") or ""
            if row.get("rsid") and not key.startswith("rs"):
                authored = genotypes.get(key) or genotypes.get(
                    f"{row.get('chrom')}:{row.get('start')}:{row.get('ref')}", set()
                )
                hosted = {(row.get("ref") or "").upper(), *(a.upper() for a in (row.get("alts") or "").split(",") if a)}
                if authored and not authored <= hosted:
                    add(REDERIVE_DECLARED_CORRECTION)
    return reasons


def table_written_by(verification_json: bytes | None) -> str | None:
    """The enricher version that wrote a version's derived tables, from its `verification.json` `producer`
    (`just-dna-enricher 0.8.4` → `0.8.4`); `None` when there is no such document or it names none."""
    if not verification_json:
        return None
    try:
        producer = json.loads(verification_json).get("producer") or ""
    except ValueError:
        return None
    name, _, version = str(producer).rpartition(" ")
    return version if name.endswith("enricher") and version else None


def rederive_converged(written_by: str | None, installed: str | None) -> bool | None:
    """Whether the stored table was written by the installed enricher (or a newer one): then re-deriving it
    would write the same table again, so its reasons are what this enricher writes, not staleness, and they
    must not act (the convergence rule `RebuildVerdict` keeps for compiled output; a fresh 0.8.5 publish
    leaves `source_release` blank on rows it carries, measured 2026-11-13). `None` when either version is
    unknown: the reasons are reported and act only beside another reason to re-publish."""
    from just_dna_format.release_records import parse_version

    if not written_by or not installed:
        return None
    try:
        return parse_version(written_by) >= parse_version(installed)
    except ValueError:
        return None


def _not_substitutions(ref: str | None, alts: list[str]) -> bool:
    return any(not is_substitution(ref, alt) for alt in alts if alt)


def needs_online_rederive(files: dict[str, bytes]) -> bool:
    """Whether a module carries an allele offline 0.8 cannot place: anything but a single-base
    substitution (upstream's `vrs.is_substitution`, the class it mints without a reference).

    Offline an indel is trimmed but not proven leftmost, and its authored-event verdict is `undecided`
    (upstream RM385, open until 0.9; guide § 2 step 5: "Run it online"). Read from both sides, the
    resolved `ref`/`alts` and the authored `ref`/`alt` and genotype, since an rsID-only row has no
    resolved alleles yet. Errs towards online: a multi-base substitution or a symbolic allele asks the
    network too, which costs requests and never a wrong placement.
    """
    if RESOLUTION_CSV in files:
        for row in _rows(files[RESOLUTION_CSV].decode("utf-8")):
            if row.get("ref") and _not_substitutions(row["ref"], (row.get("alts") or "").split(",")):
                return True
    if "variants.csv" in files:
        for row in _rows(files["variants.csv"].decode("utf-8")):
            if row.get("ref") and row.get("alt") and _not_substitutions(row["ref"], [row["alt"]]):
                return True
            if any(len(allele) != 1 for allele in split_genotype(row.get("genotype") or "")):
                return True
    return False


def rederive_subjects(resolution_csv_text: str) -> int:
    """How many recorded subjects a re-derivation re-asks: distinct `variant_key`s (one subject can
    expand to several loci, RM381, and is asked once)."""
    return len({row.get("variant_key") for row in _rows(resolution_csv_text)})


def prepare_version_upgrade(
    storage: StorageBackend,
    namespace: str,
    name: str,
    version: str,
    manifest: ModuleManifest,
    *,
    trim: bool = False,
    installed_releases: dict[str, str | None] | None = None,
) -> VersionUpgradePlan | None:
    """Compute the re-publish plan for a version from its stored spec inputs, or None when they
    aren't all retrievable (a legacy import — cannot be upgraded).

    Applies the 0.3 back-population to `variants.csv`. With `trim`, first drops the columns/keys the
    current contract rejects from `variants.csv`/`studies.csv` and `module_spec.yaml` (LOSSY);
    without it, any such offenders are recorded in `blocked` and the plan builds no files (so the
    planner never trips over an unknown column). Registry-owned `module:` keys are never offenders
    here — the always-on strip removes them non-lossily at publish."""
    key = version_key(namespace, name, version)
    # Probe storage directly rather than filtering `manifest.inputs`. The two disagree, and the
    # disagreement is load-bearing: `inputs[]` is the compiler's *hashed input* set, which by
    # construction excludes `resolution.csv` and the 0.5 fact sidecars (they are multi-producer, so
    # they are hashed by facts rather than bytes). Reading only what the manifest lists therefore
    # dropped every one of them on upgrade — silently losing `sources.csv` (licence facts, and a
    # digest change) and `resolution.csv` (without which the strict recompile then fails).
    present = {n for n in RECOGNIZED_SPEC_FILES if storage.exists(key, n)}
    if SPEC_YAML not in present or not has_spec_data(present):
        return None
    # Composition is the compiler's rule, not ours: a PGx module carries no `variants.csv` and is
    # complete. Read whatever is actually there.
    specs = {n: storage.read_file(key, n).decode("utf-8") for n in sorted(present) if n in _TEXT_SPECS}

    dropped: dict[str, list[str]] = {}
    blocked: dict[str, list[str]] = {}
    # module_spec.yaml keys and every CSV's columns share the trim/block treatment; each file uses
    # its own offender detector and trimmer.
    for fname in sorted(specs):
        is_yaml = fname == SPEC_YAML
        offenders = (
            offending_yaml_keys(specs[fname]) if is_yaml
            else offending_columns(specs[fname], _ROW_MODELS[fname])
        )
        if not offenders:
            continue
        if trim:
            specs[fname], dropped[fname] = (
                trim_unknown_yaml_keys(specs[fname]) if is_yaml
                else trim_unknown_columns(specs[fname], _ROW_MODELS[fname])
            )
        else:
            blocked[fname] = offenders
    if blocked:
        return VersionUpgradePlan(
            variants_plan=UpgradePlan(
                total_rows=0, upgradable_rows=0, migrated_variants_csv=specs.get("variants.csv", "")
            ),
            blocked=blocked,
        )

    # The 0.3 back-population applies to `variants.csv` only, and a PGx-only module has none.
    plan = (
        plan_variants_upgrade(specs["variants.csv"])  # safe: no unknown columns remain
        if "variants.csv" in specs
        else UpgradePlan(total_rows=0, upgradable_rows=0, migrated_variants_csv="")
    )
    gap = contract_gap(manifest)
    # Carry every recognized spec file forward, plus the logo (version-independent branding, out of
    # the digest); then override the text ones with the migrated/trimmed content. Logs and provenance
    # are intentionally NOT carried: they describe how the *predecessor* was built, and this
    # mechanical re-publish has its own (absent) provenance.
    #
    # `resolution.csv` and `sources.csv` ride along deliberately. The enricher treats existing rows
    # as authoritative and merges rather than clobbering, so carrying them makes the re-publish cheap
    # and deterministic instead of re-resolving everything against whatever the cache holds today.
    carry = set(present) - {PROVENANCE_FILE}
    if manifest.logo is not None:
        carry.add(manifest.logo.name)
    files: dict[str, bytes] = {n: storage.read_file(key, n) for n in sorted(carry) if storage.exists(key, n)}
    for fname, text in specs.items():
        files[fname] = text.encode("utf-8")
    if "variants.csv" in specs:
        files["variants.csv"] = plan.migrated_variants_csv.encode("utf-8")
    # **Measured only when the answer could still change the decision.** A contract gap, pending 0.3
    # drift or a `--trim` drop each act on their own, and probing under a pending migration would
    # measure the migration rather than the compiler: `files` carries the *migrated* rows, so the
    # recomputation would legitimately disagree with a manifest compiled before them.
    # The interval half of the same question, from format 0.7's release record. Computed first,
    # because it can *withhold* the contract gap's action as well as add its own: a minor that
    # measurably moved nothing is a minor whose recompile reproduces the stored bytes, and the
    # version comparison was only ever standing in for that measurement. It withholds on nothing
    # less than a complete chain with every driving axis `False` — see `refutes_a_contract_gap`.
    # `gap.compiled_under` is already the parsed bare version; passing the raw stamp would raise on
    # the one manifest a foreign compiler touched.
    declared = declared_movement(gap.compiled_under, gap.current, manifest)
    contract_acts = gap.acts_by_default and not declared.refutes_a_contract_gap
    already_acting = contract_acts or plan.needed or bool(dropped)
    drift, unmeasured = ([], []) if already_acting else measure_output_drift(manifest, files)
    verdict = rebuild_verdict(
        gap_scale=gap.scale,
        gap_acts=already_acting,
        drift=drift,
        unmeasured=unmeasured,
        identical_compiler=gap.scale == GAP_NONE,
        declared=declared,
    )
    resolution = files[RESOLUTION_CSV].decode("utf-8") if RESOLUTION_CSV in files else ""
    reasons = (
        rederive_reasons(
            resolution,
            files["variants.csv"].decode("utf-8") if "variants.csv" in files else None,
            installed_releases if installed_releases is not None else {},
        ) if resolution else {}
    )
    written_by = table_written_by(files.get(VERIFICATION_FILE))
    converged = rederive_converged(written_by, installed_enricher())
    # The reasons always say *how* an acting re-publish enriches (M12); they act *alone* only for a table an
    # older enricher wrote, so a module the installed enricher wrote converges.
    rederive = any(code != REDERIVE_CANNOT_SAY for code in reasons)
    return VersionUpgradePlan(
        variants_plan=plan,
        dropped=dropped,
        files=files,
        gap=gap,
        verdict=verdict,
        declared=declared,
        rederive=rederive,
        needs_online=rederive and needs_online_rederive(files),
        rederive_subjects=rederive_subjects(resolution) if rederive else 0,
        rederive_reasons=reasons,
        rederive_written_by=written_by,
        rederive_acts=rederive and converged is False,
    )


def _describe_variants_rewrite(plan: UpgradePlan) -> str:
    """What the 0.3 back-population did to `variants.csv`, named per column and counted.

    **The sentence used to hardcode `direction/stat_significance/clin_sig`, and that was wrong on
    real modules (S15).** `_UPGRADED_COLUMNS` has six entries, and which of them move is a property
    of the spec: the reporter measured a module whose `direction` and `stat_significance` were
    already authored and whose `clin_sig` arrived empty, so all three named columns were untouched
    while `state` — named nowhere — was rewritten on 990 of 990 rows. The changelog is the only
    human-readable record of what a version changed, so it named the columns it did not touch and
    omitted the one it did.

    The repair is not a longer hardcoded list. It reads the diff the rewrite measured, so a column is
    mentioned exactly when it moved. This is the same defect as S13 one layer down — a sentence
    restating a fact that is stated authoritatively elsewhere, drifting from it — and the fix is the
    same: derive it.
    """
    bits = [
        f"{column} on {count} row(s)"
        for column, count in sorted(plan.changed_cells.items())
    ]
    rewrote = f"rewrote {', '.join(bits)}" if bits else "changed no existing cell"
    added = (
        f"; added column(s) {', '.join(plan.added_columns)}, empty where the spec said nothing"
        if plan.added_columns
        else ""
    )
    return (
        f"back-populated the 0.3 axes for {plan.upgradable_rows} variant row(s): {rewrote}{added}"
    )


def _upgrade_changelog(prep: VersionUpgradePlan, version: str) -> str:
    """A human changelog describing what the automated re-publish of `version` changed."""
    parts: list[str] = []
    if prep.variants_plan.needed:
        parts.append(_describe_variants_rewrite(prep.variants_plan))
    if prep.dropped:
        detail = "; ".join(f"{f}: {', '.join(items)}" for f, items in prep.dropped.items())
        parts.append(f"trimmed columns/keys the current contract rejects ({detail})")
    if prep.contract_acts:
        # Not "no content change". The authored data is untouched, but a contract cut re-shapes the
        # parquet, so `artifact.digest` moves — and the module can gain tables it did not have (0.5
        # re-baselined `variant_key` onto the VRS allele id; 0.6 places positional rows from
        # `resolution.csv`). Saying otherwise sends whoever compares the two digests looking for a
        # corruption that is not there.
        #
        # **The versions are named from the gap, never written down here.** This sentence goes into a
        # published manifest, which is immutable — and the hardcoded "under just-dna-format 0.5" it used
        # to carry would have been stamped, permanently and wrongly, onto every version re-baselined at
        # the 0.6 cut. A migration that misdates its own record is worse than one that says less.
        parts.append(
            f"recompiled to the current contract ({prep.gap.describe()}): the authored data is "
            f"unchanged, but the parquet shape and therefore `artifact.digest` differ from the "
            f"predecessor's. The predecessor stays published and verifiable"
        )
    if prep.verdict.drift:
        # Measured on this artifact: a published field the current compiler derives differently from
        # the same authored rows. Named per field rather than summarised, because this entry is
        # immutable and "recompiled" tells a later reader nothing about what it repaired.
        parts.append(
            "re-derived published fields this compiler produces differently "
            f"({'; '.join(f.detail for f in prep.verdict.drift)})"
        )
    if prep.verdict.declared:
        # Declared by upstream over the compile interval, not measured here — so it is worded as what
        # the release did, and the release is named. These are `correction`s only: an *addition* is a
        # field that was absent rather than wrong, and re-publishing to gain one would mint a PATCH
        # for something nobody published incorrectly.
        detail = "; ".join(
            f"{c.item or 'a release'} corrected {c.target}" for c in prep.verdict.declared
        )
        parts.append(
            f"picks up corrections upstream declared since this version was compiled ({detail})"
        )
    if not parts:
        parts.append("recompiled to the current just-dna-format contract (no content change)")
    return f"Automated upgrade of {version}: " + "; ".join(parts) + "."


def is_latest_version(repo: Repository, namespace: str, name: str, version: str) -> bool:
    """Whether `version` is the module's current latest (non-yanked) version.

    Only the latest is upgrade-eligible: an upgrade re-publishes as a NEW patch, and the original is
    immutable, so a superseded older version is masked — otherwise every run would forever mint a
    fresh patch from the same un-upgraded bytes even though an upgraded successor already exists."""
    row = repo.get_module_row(namespace, name)
    return row is not None and row["latest_version"] == version


def _next_free_patch(repo: Repository, namespace: str, name: str, version: str) -> str:
    """The next PATCH after `version` not already taken (`1.0.0` → `1.0.1`, skipping any in use)."""
    v = parse_version(version)
    patch = v.patch + 1
    while repo.version_exists(namespace, name, f"{v.major}.{v.minor}.{patch}"):
        patch += 1
    return f"{v.major}.{v.minor}.{patch}"


class UpgradeHeld(Exception):
    """A version the sweep will not re-publish under this run's switches, with the reason (M12).

    Not a `PublishError`: nothing was attempted, so no publish refused. The sweep reports it per module
    and goes on, under `code` on the terminal and with the sentence in the run's log.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def upgrade_version(
    *,
    repo: Repository,
    storage: StorageBackend,
    settings: Settings,
    namespace: str,
    name: str,
    version: str,
    manifest: ModuleManifest,
    changelog: str | None = None,
    recompile: bool = False,
    trim: bool = False,
    prepared: VersionUpgradePlan | None = None,
    online: bool = False,
    accept_drift: bool = False,
) -> tuple[str, ModuleManifest] | None:
    """Re-publish a version's spec as the next PATCH after migrating it to the current contract.

    Applies the 0.3 back-population and (with `trim`) drops columns the current contract rejects,
    then re-publishes through the full server-side compile path so the successor carries a freshly
    computed, trusted digest. The predecessor is never mutated.

    Returns `(new_version, new_manifest)`, or None when nothing needs doing — this version is
    **superseded** (only the latest is upgraded), its spec inputs aren't retrievable, it is
    **blocked** by columns the contract rejects (needs `trim`), or it is already on-contract and no
    `recompile` was requested. Pass `recompile=True` to re-emit an on-contract module in the current
    parquet schema anyway (a non-lossy schema migration). `prepared` reuses a plan already computed
    by `prepare_version_upgrade` (same `trim`), avoiding a second storage read.

    A plan that re-derives (M12) passes `rederive=True` to the publish, which refuses unread drift as
    `rederive_drift_needs_reading` unless `accept_drift`. One that also `needs_online` raises
    `UpgradeHeld` unless `online` permits egress, and then runs that one publish with
    `enrich_offline=False`: the shared clients and their pacing are untouched, and every module that
    does not need the network still re-derives from the snapshot alone."""
    if not is_latest_version(repo, namespace, name, version):
        return None
    prep = prepared or prepare_version_upgrade(
        storage, namespace, name, version, manifest, trim=trim,
        installed_releases=installed_snapshot_releases(settings),
    )
    if prep is None or not prep.would_act(recompile=recompile):
        return None
    if prep.needs_online and not online:
        raise UpgradeHeld(
            "its re-derivation needs the network: it carries an indel, and offline 0.8 cannot left-align "
            "one (upstream RM385); re-run with --online",
            code=HELD_NEEDS_ONLINE,
        )
    if prep.needs_online:
        # Online, the dbSNP merge check is on for this publish whatever the server's setting: since
        # enricher 0.8.1 (RM398) it is also the third placement witness, read from the record it
        # fetches, where 0.8.0 asked live REST unconditionally. Left at the setting (off by default),
        # the same command would check an indel's placement less than it did on 0.8.0, and S117's
        # misanchored ABO insertion is the case it exists for. Through `settings`, so the publish path
        # takes `_UNSHARED_EGRESS` for it and a `--jobs` sweep stays inside NCBI's pace. A withdrawn
        # rsID it finds refuses the module (`enrich_failed`), never a successor that names nothing.
        settings = settings.model_copy(update={"enrich_offline": False, "enrich_verify_rsids": True})

    new_version = _next_free_patch(repo, namespace, name, version)
    new_manifest = publish_version(
        repo=repo,
        storage=storage,
        settings=settings,
        namespace=namespace,
        name=name,
        version=new_version,
        changelog=changelog or _upgrade_changelog(prep, version),
        owner=manifest.owner or namespace,
        files=prep.files,
        # **The prospective test-data guard cannot be about this publish.** It exists so a mistyped
        # namespace cannot spend a version number and a global `content_hash` that only a purge frees
        # (0.12/0.14) — a question about an identifier arriving for the first time. Here the module is
        # already in the catalog under this exact name, admitted either by an `allow_test_data=true`
        # override or by an instance whose mode says this is the data it holds, and the successor is a
        # PATCH of that same identifier. So there is nothing left to prevent, and refusing instead made
        # a catalog-wide re-baseline impossible to finish: `registry upgrade --apply --force` died on
        # `test_data_on_prod` at the first such module, with no flag to pass and no way past it. The
        # override's own warning still fires and is still logged, so production holding test-prefixed
        # data remains as findable as it was before this re-publish.
        allow_test_data=True,
        rederive=prep.rederive,
        accept_drift=accept_drift,
    )
    return new_version, new_manifest
