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
from typing import Optional

import yaml
from just_dna_format.binning import (
    ActivityPhenotypeRow,
    CopyNumberRow,
    HeteroplasmyRow,
    RepeatAlleleRow,
)
from just_dna_format.frequency import FrequencyRow
from just_dna_format.gene_metrics import GeneMetricsRow
from just_dna_format.identity import parse_version
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
                out[col] = _csv_cell(getattr(up, col))
        out_rows.append(out)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=out_fields, extrasaction="ignore", restval="")
    writer.writeheader()
    writer.writerows(out_rows)
    migrated = buf.getvalue() if total else variants_csv_text
    return UpgradePlan(total_rows=total, upgradable_rows=upgradable, migrated_variants_csv=migrated)


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
    # The 0.5 derived-fact sidecars. Enricher-produced rather than hand-authored, but they round-trip
    # through storage like everything else and an unknown column in one fails the same recompile.
    "frequencies.csv": FrequencyRow,
    "gene_metrics.csv": GeneMetricsRow,
    "literature.csv": LiteratureRow,
    "sources.csv": SourceRow,
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
#: MODULE.md) is carried through as opaque bytes.
_TEXT_SPECS: frozenset[str] = frozenset({SPEC_YAML}) | frozenset(_ROW_MODELS)


_YAML_BLOCK_MODELS: tuple[tuple[Optional[str], type[BaseModel], frozenset[str]], ...] = (
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

    #: Set when the predecessor predates the 0.5 contract, so a recompile is genuinely needed rather
    #: than merely available. Makes the catalog-wide 0.5 migration `registry upgrade --apply` instead
    #: of a `--force` an operator has to know to pass.
    needs_contract_recompile: bool = False

    def would_act(self, *, recompile: bool) -> bool:
        """Whether re-publishing this version is worthwhile: it has 0.3 drift, trimmed something,
        predates the current contract, or a `recompile` was explicitly requested. Never acts while
        blocked."""
        if self.blocked:
            return False
        return (
            self.variants_plan.needed
            or bool(self.dropped)
            or self.needs_contract_recompile
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
) -> Optional[VersionUpgradePlan]:
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
    contract_recompile = needs_contract_recompile(manifest)
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
        needs_contract_recompile=contract_recompile,
    )


def _upgrade_changelog(prep: VersionUpgradePlan, version: str) -> str:
    """A human changelog describing what the automated re-publish of `version` changed."""
    parts: list[str] = []
    if prep.variants_plan.needed:
        parts.append(
            f"back-populated the 0.3 axes (direction/stat_significance/clin_sig) for "
            f"{prep.variants_plan.upgradable_rows} variant row(s)"
        )
    if prep.dropped:
        detail = "; ".join(f"{f}: {', '.join(items)}" for f, items in prep.dropped.items())
        parts.append(f"trimmed columns/keys the current contract rejects ({detail})")
    if prep.needs_contract_recompile:
        # Not "no content change". The authored data is untouched, but 0.5 re-baselined `variant_key`
        # onto the VRS allele id, so `artifact.digest` moves — and the module gains a resolution
        # table and licensing facts it did not have. Saying otherwise sends whoever compares the two
        # digests looking for a corruption that is not there.
        parts.append(
            "recompiled under just-dna-format 0.5: the authored data is unchanged, but "
            "`variant_key` was re-baselined onto the VRS allele identity, so `artifact.digest` "
            "differs from the predecessor's. The predecessor stays published and verifiable"
        )
    if not parts:
        parts.append("recompiled to the current just-dna-format contract (no content change)")
    return f"Automated upgrade of {version}: " + "; ".join(parts) + "."


def needs_contract_recompile(manifest: ModuleManifest) -> bool:
    """Whether this version predates the 0.5 contract and would genuinely benefit from a recompile.

    Keyed on `content_signature`, which the compiler began stamping in 0.5 — the same witness
    `db.facets` uses, and for the same reason: `compilation.compiler_version` holds a prefixed string
    rather than a bare SemVer, so parsing it fails quietly in the wrong direction.
    """
    return manifest.content_signature is None


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
    changelog: Optional[str] = None,
    recompile: bool = False,
    trim: bool = False,
    prepared: Optional[VersionUpgradePlan] = None,
) -> Optional[tuple[str, ModuleManifest]]:
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
    )
    return new_version, new_manifest
