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
from just_dna_format.release_records import (
    RECOMPILE_DRIVING_AXES,
    DeclaredChange,
    needs_recompile,
)
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


#: What the record answers, keyed by the `UNPROBED_SURFACES` entry it retires. The third entry has no
#: key here on purpose: upstream's sweep is an **offline compile**, so it says nothing about what the
#: enricher wrote into a module, and their own instruction with the record was to treat those blocks
#: as unmeasured rather than unchanged. A record that grew an enricher axis would add a key here; one
#: that is silent about them must not be read as clearing them.
_SURFACE_AXES: dict[str, str] = {
    UNPROBED_SURFACES[0]: "parquet_bytes",
    UNPROBED_SURFACES[1]: "warnings",
}


class DeclaredMovement(BaseModel):
    """What upstream's release record says a release *did*, over the interval this version straddles.

    **The other half of S62, and it arrives as data in format 0.7 (RM126).** `_DRIFT_PROBES` answers
    per *field value*, by recomputing one published field from the stored authored rows; this answers
    per *interval*, from `release_records.needs_recompile`, and it reaches the surfaces no local probe
    can — the parquet bytes above all. The two are deliberately kept side by side rather than folded
    together, exactly as the note beside `_DRIFT_PROBES` said they would be: a recomputation checks
    the artifact in front of us and a record states what a release did in general, and neither
    subsumes the other.

    **Only a `correction` acts, and this is the whole of the judgement in this class.** Upstream
    declares each change as `correction` (the value we published was **wrong**) or `addition` (it was
    **absent**), and a differ cannot tell those apart — which is why the field is declared rather than
    measured. A registry must route them differently: re-publishing to *repair* a value we no longer
    stand behind is what a re-baseline is for, while re-publishing to *gain* an optional new field
    mints an immutable PATCH per module for something nobody published wrongly. That is the failure
    the patch rule exists to prevent, and `parquet_bytes` is where it would arrive — upstream measured
    10 of 16 reference modules moving `artifact.digest` across a pure **patch** interval, so acting on
    that axis alone would re-baseline the whole catalog on every dependency bump.

    Convergence holds for free and is asserted rather than argued: the successor is compiled under
    `current`, the self-interval is empty by construction upstream, so every axis comes back `False`
    and there is nothing left to declare. A false positive therefore costs one wasted PATCH per module
    ever, which is the same bound `RebuildVerdict` already accepts.
    """

    compiled_under: str | None = Field(
        default=None, description="The release the stored artifact was compiled under, if known"
    )
    current: str | None = Field(
        default=None, description="The release this server would recompile with"
    )
    axes: dict[str, bool | None] = Field(
        default_factory=dict,
        description="Per output axis: True moved, False did not, **None means nobody measured**",
    )
    corrections: list[DeclaredChange] = Field(
        default_factory=list,
        description="Declared corrections on a recompile-driving axis — the only thing here that acts",
    )
    additions: list[DeclaredChange] = Field(
        default_factory=list,
        description="Declared additions: reported so an operator sees them, never a reason to act",
    )
    complete: bool = Field(
        default=False,
        description="Whether the record chain covers the whole interval; False leaves every axis unknown",
    )

    @property
    def acts_by_default(self) -> bool:
        """Whether the record alone is reason enough to re-publish without `--force`."""
        return bool(self.corrections)

    def residual_surfaces(self) -> list[str]:
        """The `UNPROBED_SURFACES` entries this record does **not** answer.

        An axis the record measured is no longer a thing we cannot see, so it leaves the list — which
        is the point of adopting this at all: before 0.7 a version compiled under a different compiler
        came back `cannot_say` forever, because the parquet bytes were unreachable by construction. An
        `None` axis, or a chain that does not cover the interval, keeps its entry: the record's axes
        are tri-state precisely so a silence is not read as a licence to stop looking.
        """
        residual = [
            surface for surface in UNPROBED_SURFACES
            if self.axes.get(_SURFACE_AXES.get(surface, ""), None) is None
        ]
        if not self.complete:
            under = self.compiled_under or "an unstamped compiler"
            residual.append(
                f"upstream's release record does not cover {under} → {self.current or 'unknown'}, "
                f"so what that interval changed about compiled output is unknown rather than nothing"
            )
        return residual

    def describe(self) -> str:
        """One clause for an operator report and for an immutable changelog entry."""
        if not self.corrections:
            return "upstream declares no correction over this interval"
        return "; ".join(
            f"{change.target} was corrected in {change.item or 'a release'} ({change.axis})"
            for change in self.corrections
        )


def declared_movement(compiled_under: str | None, current: str | None) -> DeclaredMovement:
    """Read upstream's release record for the interval `(compiled_under, current]`.

    **`compiled_under` must already be a bare, parsed version** — `upgrade.stamped_compiler_version`
    returns exactly that, `None` included. `needs_recompile` answers *unknown* for a `None` stamp
    (S88/RM183) but still **raises** on a stamp that is present and unreadable, on the reasoning that
    it was asked and cannot be read; passing a raw `compilation.compiler_version` through would
    therefore kill a catalog-wide sweep on the one manifest a foreign compiler touched. The parse
    happens once, in the caller that already does it.

    `current` is `None` on an install with no compiler tier. That is *cannot say*, not *current* — the
    same rule `ContractGap` applies one axis over.
    """
    if current is None:
        return DeclaredMovement(compiled_under=compiled_under, current=None, complete=False)
    answer = needs_recompile(compiled_under, current)
    declared = [
        change for change in answer.declared if change.axis in RECOMPILE_DRIVING_AXES
    ]
    return DeclaredMovement(
        compiled_under=answer.compiled_under,
        current=answer.current,
        axes=dict(answer.axes),
        corrections=[c for c in declared if c.kind == "correction"],
        additions=[c for c in declared if c.kind == "addition"],
        complete=answer.complete,
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
    declared: list[DeclaredChange] = Field(
        default_factory=list,
        description=(
            "Corrections upstream's release record declares over this version's compile interval — "
            "the surfaces no local probe reaches. Reported beside `drift`, never merged into it: one "
            "is a value measured on this artifact, the other a statement about a release."
        ),
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
        parts = [f.detail for f in self.drift]
        parts += [
            f"upstream corrected {c.target} in {c.item or 'a release'} since this version compiled"
            for c in self.declared
        ]
        if parts:
            return "; ".join(parts)
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
    # carrying the sole mention of a gene would show drift that no recompile can clear.
    #
    # **`compilation.dropped_rows` (format 0.7) is the first witness that says so directly, and it
    # closes a hole the counter never could — which is why this arm is first.** Our own S65 asked for
    # it: a drop from `variants.csv` moves `stats.variant_count`, so the counter below catches it, but
    # a drop inside a *kind* table moves **no published counter at all**. From outside, that module was
    # indistinguishable from one whose spec had changed, and `_probe_stats_genes` would have reported
    # the gene it lost as drift a recompile cannot clear. Upstream ships the count per table instead of
    # leaving us to infer it, and names the same rule as `DROPPED_ROWS_CONDITION` on their own roster
    # of recomputable fields.
    #
    # **Only a non-empty value is evidence.** The field has a default, so a manifest compiled before
    # 0.7 parses as `{}` — which is also what a 0.7 compile writes when nothing was dropped. The two
    # are indistinguishable here and must stay that way: reading an empty dict as *nothing was dropped*
    # would date a stored artifact by a field's presence, and the counter guard below is what covers
    # the pre-0.7 case, unchanged.
    dropped = manifest.compilation.dropped_rows
    if dropped:
        tables = ", ".join(f"{count} row(s) from {table}" for table, count in sorted(dropped.items()))
        return [], [
            f"this compile discarded {tables}, so `manifest.stats` is the post-drop answer while a "
            f"recomputation from the authored rows is the pre-drop one — they disagree permanently "
            f"and correctly, and no field derived from those rows can be compared"
        ]

    # The pre-0.7 half of the same guard: a disagreeing `variant_count` is the structural signal that
    # a drop happened, and it stays because a published manifest is immutable — every version compiled
    # before 0.7 carries no `dropped_rows` and will never gain one.
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
    identical_compiler: bool, declared: DeclaredMovement | None = None,
) -> RebuildVerdict:
    """Compose the axes into one tri-state answer.

    Takes the gap's *conclusions* rather than the `ContractGap` itself, to keep the import one-way:
    `upgrade` composes this, and nothing here needs to know how a gap is scored. `declared` is the
    same arrangement for the record — `upgrade` reads the manifest's stamp, this file reads what a
    release did with it.

    **`declared=None` is not "nothing was declared".** It is the pre-0.7 caller, or a process with no
    compiler tier, and it keeps the whole of `UNPROBED_SURFACES` unmeasured — which is what the answer
    was before the record existed.
    """
    unreachable = list(declared.residual_surfaces()) if declared is not None else list(UNPROBED_SURFACES)
    corrections = list(declared.corrections) if declared is not None else []
    if gap_acts:
        # The contract already decided. Probes are not run in this case (see `upgrade`), so saying
        # anything about drift here would be inventing a measurement — but the record is a statement
        # about the interval rather than about this artifact, so it is carried: it names *what* the
        # re-baseline repairs, which is what goes into the successor's immutable changelog entry.
        return RebuildVerdict(state=REBUILD_YES, declared=corrections, unmeasured=unreachable)
    if drift and identical_compiler:
        return RebuildVerdict(state=REBUILD_YES, drift=drift, anomaly=True, unmeasured=list(unmeasured))
    if drift:
        return RebuildVerdict(
            state=REBUILD_YES, drift=drift, declared=corrections, unmeasured=list(unmeasured)
        )
    if corrections:
        # Nothing this server can recompute has moved, and upstream says a value we published is
        # nonetheless wrong — the parquet cell RM110 corrected is the worked example, since no probe
        # here reads a compiled parquet. `identical_compiler` cannot be true here: the self-interval
        # declares nothing, which is what keeps this arm from firing on its own successor.
        return RebuildVerdict(
            state=REBUILD_YES, declared=corrections, unmeasured=list(unmeasured) + unreachable
        )
    residual = list(unmeasured)
    if not identical_compiler or gap_scale == "unknown":
        # A different compiler, nothing measured: the probed fields agree, and what is left is exactly
        # what we cannot see. This is the shape S62 exists to close, and since 0.7 the record closes
        # most of it — `residual_surfaces` returns only the axes it could not answer.
        residual = residual + unreachable
    if residual:
        return RebuildVerdict(state=REBUILD_CANNOT_SAY, unmeasured=residual)
    return RebuildVerdict(state=REBUILD_NO)
