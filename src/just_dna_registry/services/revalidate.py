"""
Contract-drift audit: re-run the *current* `validate_spec` over a published version's stored spec
inputs to find modules that no longer satisfy the contract after a `just-dna-format` bump.

Published artifacts are immutable and keep verifying by `artifact.digest`; this never touches them.
It only tells you which versions would fail a re-compile today, so the `needs_upgrade` flag can be
set and an upgrade (re-publish as a new PATCH) scheduled. See docs/UPGRADE.md.
"""

import csv
import io
import tempfile
from pathlib import Path
from typing import Optional

from just_dna_compiler.compiler import compile_module, validate_spec
from just_dna_format.manifest import MARKETPLACE_COMPILED_BY, ModuleManifest
from just_dna_format.normalize import IDENTITY_AUTHORITY_KEYS
from just_dna_format.spec import extract_pmids

from just_dna_registry.config import Settings
from just_dna_registry.services.enrich import enrich_spec, unresolved_hint
from just_dna_registry.services.publish import normalize_module_block
from just_dna_registry.services.upgrade import plan_variants_upgrade
from just_dna_registry.specfiles import RECOGNIZED_SPEC_FILES, SPEC_YAML, has_spec_data
from just_dna_registry.storage.base import StorageBackend, version_key

def revalidate_version(
    storage: StorageBackend,
    namespace: str,
    name: str,
    version: str,
    manifest: ModuleManifest,
    *,
    settings: Optional[Settings] = None,
    strict_check: bool = False,
    recompile_check: bool = False,
) -> tuple[str, list[str]]:
    """Re-run the current `validate_spec` against a version's stored spec inputs.

    Returns `(status, messages)` where status is:
      * `"needs_upgrade"` — the spec no longer *validates* under the current contract (a tightened
        rule, e.g. the 0.2 PMID pattern). Re-publish is required.
      * `"strict_blocked"` — it validates, but would not survive today's **strict** publish. Kept
        distinct from `needs_upgrade` on purpose: that one drives `registry upgrade`, and a
        strict-blocked module cannot be fixed by re-publishing the same data. Either the author adds
        coordinates or the operator provisions a fuller reference snapshot.
      * `"upgradable"` — the spec still validates, but one or more variant rows can be losslessly
        back-populated to the additive 0.3 columns (direction/stat_significance/clin_sig) from the
        legacy `state`/booleans. Re-publish is optional-but-recommended; run `registry upgrade`.
      * `"ok"` — validates and already carries the current columns.
      * `"skipped"` — spec inputs aren't retrievable (e.g. a legacy import that shipped no inputs;
        not counted as a failure).

    `strict_check` grades the mode-ladder findings at their real severity. It is cheap and covers the
    whole catalog, but it cannot see the one that matters most — the unresolved-position gate lives
    in `compile_module`, not in `validate_spec` — so its findings are reported as warnings rather
    than as a verdict.

    `recompile_check` is the real answer, and the slow one: enrich into a scratch dir, then compile
    strict and see. This is the "find out what a strict flip would cost" tool.
    """
    key = version_key(namespace, name, version)
    # Probe storage directly. `manifest.inputs` is the compiler's hashed-input set and by construction
    # excludes `resolution.csv` and the 0.5 fact sidecars, so filtering by it would materialize an
    # incomplete spec dir and then blame the module for the difference.
    present = [n for n in RECOGNIZED_SPEC_FILES if storage.exists(key, n)]
    if SPEC_YAML not in present or not has_spec_data(set(present)):
        return "skipped", ["spec inputs not available for revalidation"]
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp)
        for iname in present:
            (spec / iname).write_bytes(storage.read_file(key, iname))
        # Normalize registry-owned keys before the drift check — the publish path does the same, so a
        # legacy `module.namespace` (forbidden but registry-overridden) must not read as un-fixable
        # contract drift. Genuine drift (typo'd/forbidden columns) still surfaces.
        normalize_module_block(spec)
        result = validate_spec(spec, IDENTITY_AUTHORITY_KEYS, strict=strict_check)
        if not result.valid:
            return "needs_upgrade", result.errors
        strict_notes = list(result.warnings) if strict_check else []

        if recompile_check and settings is not None:
            blocked = _strict_recompile_blockers(spec, settings)
            if blocked:
                return "strict_blocked", blocked

        # Still valid — but do the additive 0.3 axes have a legacy source to back-populate?
        # A PGx-only module has no `variants.csv`, and that is complete rather than deficient.
        plan = (
            plan_variants_upgrade((spec / "variants.csv").read_text(encoding="utf-8"))
            if (spec / "variants.csv").is_file()
            else None
        )
    if plan is not None and plan.needed:
        return "upgradable", [
            f"{plan.upgradable_rows}/{plan.total_rows} variant row(s) can be back-populated to the "
            f"0.3 columns (direction/stat_significance/clin_sig) — run `registry upgrade`"
        ] + strict_notes
    return "ok", strict_notes


def _strict_recompile_blockers(spec: Path, settings: Settings) -> list[str]:
    """Would a strict publish of this spec succeed today? Returns the reasons it would not.

    Runs the real pipeline — enrich, then compile strict into a throwaway directory — because
    nothing cheaper can answer it: the unresolved-position gate is the compiler's, and whether a
    position is unresolved depends on what the enricher could reach.
    """
    with tempfile.TemporaryDirectory() as out:
        enriched = enrich_spec(spec, settings)
        result = compile_module(
            spec,
            Path(out) / "compiled",
            resolve_with_ensembl=True,
            authority_keys=IDENTITY_AUTHORITY_KEYS,
            strict=True,
            ba1_threshold=settings.ba1_threshold,
            compiled_by=MARKETPLACE_COMPILED_BY,
            ensembl_reference=settings.ensembl_reference,
        )
        if result.success:
            return []
        reasons = list(result.errors)
        if enriched.unresolved or not enriched.ran:
            reasons.append(unresolved_hint(enriched, settings))
        return reasons


def gather_pmids(
    storage: StorageBackend, namespace: str, name: str, version: str, manifest: ModuleManifest
) -> list[str]:
    """All digit-only PMIDs referenced by a version's `studies.csv` (deduplicated, in order)."""
    key = version_key(namespace, name, version)
    if not any(e.name == "studies.csv" for e in manifest.inputs) or not storage.exists(key, "studies.csv"):
        return []
    text = storage.read_file(key, "studies.csv").decode("utf-8")
    seen: dict[str, None] = {}
    for row in csv.DictReader(io.StringIO(text)):
        for pmid in extract_pmids((row.get("pmid") or "").strip()):
            seen.setdefault(pmid, None)
    return list(seen)
