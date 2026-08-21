"""
Output drift: would recompiling a published version produce a different manifest?

**The third axis, and until 0.21 nothing answered it.** Two questions were already answered and are
still answered here, unchanged:

* *Is the stored spec still legal?* — `services/revalidate.py` re-runs `validate_spec` over the
  stored inputs.
* *Was this compiled under a contract-incompatible compiler?* — `upgrade.ContractGap` compares the
  manifest's `compilation.compiler_version` stamp against the installed compiler.

Neither is the question upstream RM121 raised. That was a **patch** to the compiler which changed
`manifest.stats.genes` — the field `db/repository.py` feeds this catalog's gene side table from — so
every published table-only module carried `genes: []` and could not be found by `?gene=`. `revalidate`
answered `ok` (correctly: nothing is wrong with those specs) and the gap scored `patch` (correctly: the
parquet shape did not move). Both right, and the module stayed stale with nothing anywhere saying so.

**What makes this measurable without a compile is two public functions upstream shipped in 0.6.**
`compiler.spec_tables` (RM116) returns the defaults-folded authored rows that `content_signature`
hashes, and `compiler.module_stats` (RM121) is the derivation itself. So for a manifest field that is a
pure function of authored rows, a consumer can recompute the *current* answer from stored inputs and
compare it against what was published — no enrichment, no parquet, no network. That is the whole
mechanism, and it is why this file exists rather than a wish for upstream to tell us.

Filed upstream as **S62** and **accepted** the same day, as RM126 (the surface) and RM127 (the release
class that sizes it, which blocks the first). Nothing ships there yet, and their reply widened the case
rather than narrowing it: sixteen of sixteen reference examples changed at least one published manifest
field across the 0.6.1 → 0.6.6 *patch* interval, and ten moved `artifact.digest`. So the surfaces no
local probe can reach still need their answer — see `UNPROBED_SURFACES` for what those are and
`_DRIFT_PROBES` for where an upstream source attaches and what retires when it lands.
"""

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from just_dna_compiler.compiler import module_stats, spec_tables
from just_dna_format.manifest import ModuleManifest
from pydantic import BaseModel, Field

logger = logging.getLogger("registry.rebuild")

#: A recompile is owed: either the contract moved, or a probe measured a published field that the
#: current compiler would derive differently.
REBUILD_YES: str = "yes"
#: Measured, and current. Not "no findings" — see `REBUILD_CANNOT_SAY` for that.
REBUILD_NO: str = "no"
#: The honest third answer, and the reason this is not a bool. Nothing measured a difference *and*
#: something could not be measured, which is a different fact from having checked and found nothing.
REBUILD_CANNOT_SAY: str = "cannot_say"

#: Manifest surfaces no local probe can reach, because deciding them needs the compile we are trying
#: to avoid. Named rather than left implicit: a `cannot_say` that does not say *what* it could not see
#: is the empty list wearing a different hat.
#:
#: **Upstream measured this list rather than leaving us to guess, answering S62.** Compiling all
#: sixteen `reference_examples/` under `v0.6.1` and again under `0.6.6` — a pure patch interval, spec
#: inputs byte-identical — moved `artifact.digest` on **10 of 16**, because RM120's new authored
#: `curator` column grew `studies.parquet` by 257 bytes apiece. So the parquet schema does move across
#: a patch interval, `content_signature` held on all sixteen, and both facts are exactly why a digest
#: comparison cannot stand in for this axis.
#:
#: The third entry is theirs too, and it is a limit on their measurement rather than on ours: that
#: sweep is an offline compile, so it says nothing about enricher-written blocks. Their instruction was
#: to treat them as *unmeasured rather than unchanged*, which is this list's entire purpose.
#: `literature.quotes_unchecked` (RM119) moved on three of the sixteen and is the worked example — a
#: published manifest field we cannot recompute, because it is derived from a sidecar rather than from
#: authored rows.
#:
#: `compilation.warnings` stays listed as unreachable, but note it is **not** a defect when it moves:
#: upstream's release table sizes a warning or a count as patch-level legibility work, so it was never
#: promised stable across a patch. We reported RM106 as a second instance in 0.20.1 and they corrected
#: us; the correction is kept because it is what makes the axis decomposition worth having — warning
#: text is patch-legal and a column is not, so one "did the output change" bit would have been useless.
UNPROBED_SURFACES: tuple[str, ...] = (
    "artifact.digest (the parquet bytes — upstream measured 10 of 16 moving across 0.6.1 → 0.6.6)",
    "compilation.warnings (patch-legal upstream, so a move here is not a defect)",
    "the enricher-written blocks (literature, verification) — derived from sidecars, not authored rows",
)


class DriftFinding(BaseModel):
    """One published manifest field the current compiler would derive differently."""

    field: str = Field(description="Dotted manifest path, e.g. `stats.genes`")
    stored: str = Field(description="What the published manifest says, rendered for an operator")
    recomputed: str = Field(description="What this compiler derives from the same authored rows")
    detail: str = Field(description="One clause an operator can act on")


class RebuildVerdict(BaseModel):
    """Whether a published version should be recompiled, in three states rather than two.

    `anomaly` is the state that keeps the whole thing convergent, so it is a field rather than a
    special case of `drift`: drift measured against the **identical** compiler cannot be repaired by
    recompiling, because the recompile derives the same value again. Acting on it would mint a fresh
    PATCH per sweep forever — the exact failure the patch rule exists to prevent, reintroduced through
    a different door. It is reported loudly and never acted on.
    """

    state: str = Field(
        default=REBUILD_CANNOT_SAY,
        description=f"one of {REBUILD_YES}/{REBUILD_NO}/{REBUILD_CANNOT_SAY}",
    )
    drift: list[DriftFinding] = Field(default_factory=list)
    unmeasured: list[str] = Field(
        default_factory=list,
        description="Surfaces or fields no probe could answer for — never read as 'unchanged'",
    )
    anomaly: bool = Field(
        default=False,
        description="Drift under the identical compiler: a recompile cannot fix it, so nothing acts",
    )

    @property
    def acts_by_default(self) -> bool:
        """Whether a measured drift is reason enough to re-publish without `--force`.

        **Yes, and the delegation argument is the point.** `--dry-run` against `--apply` is already
        this command's look-vs-act discriminator; `--force` exists to act *despite* the detector —
        to override what it concluded and to remedy an overlook. Requiring `--force` for a gap the
        software has just measured asks an operator to confirm something the software already knows,
        which is the same misplacement 0.18.0 named one axis over: the tool could not see a gap it had
        everything it needed to compute, and the fix belonged in the tool rather than in a flag.

        `--force` keeps its meaning exactly. It is still the only way to act on `UNPROBED_SURFACES`.
        """
        return self.state == REBUILD_YES and not self.anomaly

    def describe(self) -> str:
        """One clause for an operator report and for an immutable changelog entry."""
        if self.anomaly:
            fields = ", ".join(f.field for f in self.drift)
            return f"{fields} disagrees with this compiler's own derivation — recompiling cannot fix it"
        if self.drift:
            return "; ".join(f.detail for f in self.drift)
        if self.state == REBUILD_NO:
            return "every probed field is current"
        return f"not measurable here: {', '.join(self.unmeasured)}"


def _probe_stats_genes(manifest: ModuleManifest, recomputed: dict[str, Any]) -> DriftFinding | None:
    """`stats.genes` / `stats.gene_count` — the field RM121 moved, and the only one probed.

    **One probe, deliberately.** Every other key `module_stats` returns has a compile-side adjustment
    this recomputation cannot see: `weights_rows` counts the written parquet, and `variant_count`,
    `clinvar_count` and the rest are re-derived after the symbolic-allele drop. Probing them would
    manufacture drift on modules that are perfectly current, so they stay out until each has a reason
    of its own — a probe added because a field *exists* is how a detector starts crying wolf.

    Compared as sets: both sides come from `module_stats`, which sorts, but a comparison that depends
    on the other end's ordering is a comparison that breaks the day it stops sorting.
    """
    stored = set(manifest.stats.genes)
    current = set(recomputed.get("genes") or [])
    if stored == current:
        return None
    gained = sorted(current - stored)
    lost = sorted(stored - current)
    parts = []
    if gained:
        parts.append(f"{len(gained)} gene(s) this compiler finds and the manifest does not "
                     f"({', '.join(gained[:5])}{'…' if len(gained) > 5 else ''})")
    if lost:
        parts.append(f"{len(lost)} gene(s) the manifest claims and this compiler does not "
                     f"({', '.join(lost[:5])}{'…' if len(lost) > 5 else ''})")
    return DriftFinding(
        field="stats.genes",
        stored=f"{len(stored)} gene(s)",
        recomputed=f"{len(current)} gene(s)",
        detail="stats.genes is stale: " + "; ".join(parts),
    )


#: The probes, in report order.
#:
#: **This tuple is the seam for upstream S62.** Each entry recomputes one published field from stored
#: authored rows; together they answer the *recomputable* half of "would a recompile differ". The other
#: half — `UNPROBED_SURFACES` — needs a fact only the compiler holds, which is what S62 asks for. When
#: that lands, an upstream-hint source attaches beside this tuple rather than inside it (it answers per
#: *interval*, not per field-value), and any probe whose field the hint covers retires by deletion from
#: here. Keeping a probe after its hint exists is a legitimate hedge, not an oversight: a recomputation
#: checks the artifact in front of us, while a hint states what a release did in general.
_DRIFT_PROBES: tuple[Callable[[ModuleManifest, dict[str, Any]], DriftFinding | None], ...] = (
    _probe_stats_genes,
)


def measure_output_drift(
    manifest: ModuleManifest, files: dict[str, bytes]
) -> tuple[list[DriftFinding], list[str]]:
    """Recompute the probed manifest fields from prepared spec inputs. Returns `(drift, unmeasured)`.

    `files` is `VersionUpgradePlan.files` — the **migrated** inputs, which is what a re-publish would
    actually compile. Measuring the predecessor's bytes instead would answer a question nobody asked.

    Cheap by construction: `spec_tables` parses CSVs and folds `defaults:`, with no enrichment, no
    parquet write and no network. That is the whole reason this axis is answerable at all rather than
    only by running the operation we are trying to decide about.
    """
    with tempfile.TemporaryDirectory() as tmp:
        spec_dir = Path(tmp)
        for fname, blob in files.items():
            target = spec_dir / fname
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        try:
            tables, _build = spec_tables(spec_dir)
        except ValueError as exc:
            # A stored CSV the current models reject. That is `revalidate`'s finding to report and a
            # real one, but here it means the recomputation could not run — which is `unmeasured`,
            # never a clean bill and never drift.
            return [], [f"the authored rows could not be parsed ({exc})"]

    recomputed = module_stats(tables.get("variants.csv") or [], tables)

    # **The false-drift guard, and it is not optional.** `validate_spec` computes `stats` from the
    # full row set; `compile_module` re-derives them over the survivors *only when the symbolic-allele
    # drop removed something*. This recomputation is the pre-drop side, so a module that lost a row
    # carrying the sole mention of a gene would show drift that no recompile can clear. A disagreeing
    # `variant_count` is the structural signal that a drop happened — cheaper and far more durable
    # than reading warning prose, which upstream is free to reword.
    stored_count = manifest.stats.variant_count
    if recomputed.get("variant_count") != stored_count:
        return [], [
            f"the row set moved since this version was compiled "
            f"(variant_count {stored_count} published, {recomputed.get('variant_count')} recomputed), "
            f"so a field derived from it cannot be compared"
        ]

    findings = [f for probe in _DRIFT_PROBES if (f := probe(manifest, recomputed)) is not None]
    return findings, []


def rebuild_verdict(
    *, gap_scale: str, gap_acts: bool, drift: list[DriftFinding], unmeasured: list[str],
    identical_compiler: bool,
) -> RebuildVerdict:
    """Compose the three axes into one tri-state answer.

    Takes the gap's *conclusions* rather than the `ContractGap` itself, to keep the import one-way:
    `upgrade` composes this, and nothing here needs to know how a gap is scored.
    """
    if gap_acts:
        # The contract already decided. Probes are not run in this case (see `upgrade`), so saying
        # anything about drift here would be inventing a measurement.
        return RebuildVerdict(state=REBUILD_YES, unmeasured=list(UNPROBED_SURFACES))
    if drift and identical_compiler:
        return RebuildVerdict(state=REBUILD_YES, drift=drift, anomaly=True, unmeasured=list(unmeasured))
    if drift:
        return RebuildVerdict(state=REBUILD_YES, drift=drift, unmeasured=list(unmeasured))
    residual = list(unmeasured)
    if not identical_compiler or gap_scale == "unknown":
        # A different compiler, nothing measured: the probed fields agree, and the unprobed ones are
        # exactly what we cannot see. This is the shape S62 exists to close.
        residual = residual + list(UNPROBED_SURFACES)
    if residual:
        return RebuildVerdict(state=REBUILD_CANNOT_SAY, unmeasured=residual)
    return RebuildVerdict(state=REBUILD_NO)
