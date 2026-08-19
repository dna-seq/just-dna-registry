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

import yaml
from just_dna_format.assertions import ClinicalAssertionRow
from just_dna_format.binning import (
    ActivityPhenotypeRow,
    CopyNumberRow,
    HeteroplasmyRow,
    RepeatAlleleRow,
)
from just_dna_format.frequency import FrequencyRow
from just_dna_format.gene_metrics import GeneMetricsRow
from just_dna_format.gene_validity import GeneValidityRow
from just_dna_format.gwas import GwasEffectRow
from just_dna_format.identity import parse_version
from just_dna_format.layout import sidecar_spellings
from just_dna_format.literature import LiteratureRow
from just_dna_format.manifest import Contribution, GenePanelSpec, ModuleManifest
from just_dna_format.pgs import PgsRow
from just_dna_format.pgx import (
    AlleleFunctionRow,
    DiplotypeRow,
    HaplotypeRow,
    PharmVariantRow,
)
from just_dna_format.sources import SourceRow
from just_dna_format.spec import Defaults, ModuleInfo, ModuleSpecConfig, StudyRow, VariantRow
from pydantic import BaseModel, Field

from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.services.publish import (
    _REGISTRY_OWNED_MODULE_KEYS,
    publish_version,
)
from just_dna_registry.specfiles import (
    PROVENANCE_FILE,
    RECOGNIZED_SPEC_FILES,
    SPEC_YAML,
    has_spec_data,
)
from just_dna_registry.storage.base import StorageBackend, version_key
from just_dna_registry.version import contract_compatible, installed_compiler

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
_ROW_MODELS: dict[str, type[BaseModel]] = {
    "variants.csv": VariantRow,
    "studies.csv": StudyRow,
    "activity_phenotype.csv": ActivityPhenotypeRow,
    "copynumbers.csv": CopyNumberRow,
    "repeat_alleles.csv": RepeatAlleleRow,
    "heteroplasmy.csv": HeteroplasmyRow,
    "haplotypes.csv": HaplotypeRow,
    "allele_function.csv": AlleleFunctionRow,
    "diplotypes.csv": DiplotypeRow,
    "pgs.csv": PgsRow,
    "pharm_variants.csv": PharmVariantRow,
    # The derived-fact sidecars. Enricher-produced rather than hand-authored, but they round-trip
    # through storage like everything else and an unknown column in one fails the same recompile.
    # The last three are 0.6's (RM24 / RM25 / RM90).
    "frequencies.csv": FrequencyRow,
    "gene_metrics.csv": GeneMetricsRow,
    "literature.csv": LiteratureRow,
    "gene_validity.csv": GeneValidityRow,
    "clinical_assertions.csv": ClinicalAssertionRow,
    "gwas_effects.csv": GwasEffectRow,
    # Keyed by **spelling**, so the licensing ledger is checked under whichever name a stored version
    # actually carries. `normalize_spec` stores the preferred one, but this planner also runs over
    # versions published years earlier, whose storage still holds the name of their own era.
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
    workspace floors format and compiler at the same minor and upstream cuts them together (0.6.1 /
    0.6.1, with only the enricher free to move alone, which touches no artifact).

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

    def would_act(self, *, recompile: bool) -> bool:
        """Whether re-publishing this version is worthwhile: it has 0.3 drift, trimmed something, was
        compiled under an older contract, or a `recompile` was explicitly requested. Never acts while
        blocked."""
        if self.blocked:
            return False
        return (
            self.variants_plan.needed
            or bool(self.dropped)
            or self.gap.acts_by_default
            or recompile
        )


def prepare_version_upgrade(
    storage: StorageBackend,
    namespace: str,
    name: str,
    version: str,
    manifest: ModuleManifest,
    *,
    trim: bool = False,
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
    return VersionUpgradePlan(
        variants_plan=plan,
        dropped=dropped,
        files=files,
        gap=gap,
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
    if prep.gap.acts_by_default:
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
    by `prepare_version_upgrade` (same `trim`), avoiding a second storage read."""
    if not is_latest_version(repo, namespace, name, version):
        return None
    prep = prepared or prepare_version_upgrade(
        storage, namespace, name, version, manifest, trim=trim
    )
    if prep is None or not prep.would_act(recompile=recompile):
        return None

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
    )
    return new_version, new_manifest
