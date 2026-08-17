"""
Per-version facets derived from a manifest, in one place.

Three callers need the same derivation and must not disagree: the insert on publish, the refresh
after an out-of-digest amendment (a logo swap), and the 0.11 backfill migration. A second
implementation anywhere is a catalog that filters differently from how it indexes.
"""

from typing import Any, Optional

from just_dna_compiler.compiler import UNJOINABLE_PHRASE
from just_dna_format.manifest import ModuleManifest


def predates_resolution_contract(manifest: ModuleManifest) -> bool:
    """Whether this manifest predates the 0.5 fields we would otherwise judge it on.

    Keyed on `content_signature`, which the compiler began stamping in 0.5 and never stamped before,
    so its presence is an exact witness for "this manifest speaks the 0.5 contract".

    The obvious alternative — parsing `compilation.compiler_version` — does not work and fails in the
    quiet direction: the field holds a *prefixed* string (`"just-dna-compiler 0.5.0"`), not a bare
    SemVer, so a strict parse raises and every 0.5 module reads as legacy. Presence of a field the
    release introduced is a better witness than a version string's spelling.
    """
    return manifest.content_signature is None


def predates_positional_counts(manifest: ModuleManifest) -> bool:
    """Whether this manifest predates the 0.6 counters, so the prose fallback is the only record.

    Keyed on `positional_rows`, which a 0.6 compile sets **unconditionally** — `0` for a module
    carrying no positional table at all, which is a real answer. `None` therefore means exactly "this
    compiler did not count", which is what every pre-0.6 manifest honestly is.

    `resolution_subjects` cannot be the witness even though it is the field this era introduced: it
    is typed plain `int` with a default of `0`, so a 0.5 manifest parsed by a 0.6 model reads `0` —
    indistinguishable from a module that genuinely attempted no resolution. That asymmetry is
    upstream's deliberate choice (`0` is meaningful for that field and `None` would be a breaking
    read), and it is precisely why the era test has to be a sibling field rather than the obvious one.
    """
    return manifest.compilation.positional_rows is None


def positionally_joinable(manifest: ModuleManifest) -> Optional[bool]:
    """Whether every positional row in this version carries `chrom`+`start`. `None` = cannot say.

    The structured half of what `joins_nothing_positionally` reads out of prose, and the preferred
    path since 0.6: `positional_rows_placed == positional_rows` (RM44/S31). Parts rather than a
    ratio, and "complete" is derived rather than stored, which is the house pattern.

    `positional_rows == 0` is **True, not None**: a module carrying no `pharm_variants`/`haplotypes`/
    `heteroplasmy` table has nothing that could fail to join, so there is no unjoinability to report.
    That is a different statement from the one `resolution_subjects == 0` makes about `fully_resolved`,
    and conflating them is what this whole family of fields exists to prevent.
    """
    compilation = manifest.compilation
    rows, placed = compilation.positional_rows, compilation.positional_rows_placed
    if rows is None or placed is None:
        return None
    return placed == rows


def joins_nothing_positionally(manifest: ModuleManifest) -> bool:
    """Whether the compiler reported a table in this version that no VCF can join by position.

    Keyed on `UNJOINABLE_PHRASE` — the factual core of the compiler's positional-joinability warning,
    **imported from the compiler since 0.5.4 rather than spelled out here**. Matched as a substring
    because the sentence around it names a table and two counts.

    Still prose-coupled, which is not where this belongs — but the *drift* half of that coupling is
    gone, and that is what the floor bump bought. Reported upstream as S13 and accepted twice over: the
    fragment is frozen on their side as a named constant whose own docstring names this consumer, so a
    reword is now a deliberate act with someone to tell rather than a silent re-granting of trust to
    modules that annotate nothing. Through 0.11.x this module carried the literal because 0.5.3 had no
    constant to import.

    **RM44 landed in format 0.6, and this function survived it deliberately.** The structural fix is
    here — `positionally_joinable` reads `positional_rows`/`positional_rows_placed` and says how many
    of how many, where the sentence only ever said *some do not* — and it is the preferred path.
    `CLAUDE.md` and the 0.11.3 ROADMAP entry both said to delete this function when that happened.
    That instruction is **superseded**, and by upstream's own integration note: already-published
    artifacts carry neither new field, so for every version in the catalog compiled before 0.6 the
    sentence remains the only record that survives into a reindex, when the spec directory is long
    gone. Deleting it would silently re-grant trust to exactly the modules 0.11.3 took it from — the
    PGx modules that join to no VCF — which is the original defect restored by a cleanup.

    So: structured counts when the manifest has them, this when it does not, and the fallback retires
    on its own when the last pre-0.6 version is upgraded off the catalog rather than on a date.

    Only the fragment is frozen; the rest of the sentence is free to change, so never widen the match.
    Two things still keep the coupling honest: a test compiles a real rsid-authored spec through the
    real compiler and asserts this fires — an import proves the *spelling* agrees, not that the warning
    still reaches the manifest — and the miss direction is `None` ("cannot say"), never `True`.

    That import is what makes this module server-tier, and it costs nothing: every caller
    (`db/schema.py`, `db/repository.py`, `services/catalog.py`) already needs the compiler, and no
    client path reaches here.
    """
    return any(UNJOINABLE_PHRASE in w for w in manifest.compilation.warnings)


def is_trusted(manifest: ModuleManifest) -> Optional[bool]:
    """Whether a consumer should treat this version as fully-baked. `None` = we cannot say.

    The rule the format documents is a **disjunction**, and both halves are load-bearing:
    `resolution_mode == "strict" or fully_resolved`. Testing only the mode would mark every PGx-only
    module untrusted — `resolution_mode` is assigned inside the compiler's variants branch, so a
    module with no `variants.csv` has `None` there. Testing only `fully_resolved` would miss a strict
    compile that resolved everything it was asked to.

    **But `fully_resolved` is `all()` over `variants.csv`, so for a table-only module it is vacuously
    `True`** — and that half of the disjunction was granting trust on an empty quantifier. Measured on
    the format's own `pgx_slco1b1_simvastatin` reference example: 9 of 9 `pharm_variants.csv` rows with
    a null `chrom`/`start`, `resolution_mode=None`, `fully_resolved=True`, and this function returned
    `True` for a module that joins to **no VCF at all** and therefore annotates nothing. Upstream
    records the same defect (compiler 0.5.3, RM43) as recorded-not-fixed on their side, because the
    remedy there is a compiler change; the facet is ours.

    So the order below, and the first test is deliberately outside the disjunction entirely:

    * the compiler said **any** positional table joins by rsID only → **`False`**. Checked before the
      mode, not only in the vacuous branch, because `resolution_mode` and `fully_resolved` are both
      statements about `variants.csv` alone: a module can resolve its SNP core perfectly and still
      ship a `haplotypes.csv` that matches nothing. Not blame — rsid-only identity is legal, and 0.5.3
      keeps it a warning in both modes on purpose — but this facet answers "can a consumer use this",
      and for the unjoinable part the answer is no.
    * nothing was ever resolved and no such warning → **`None`**. A coordinate-authored PGx module is
      probably fine; "probably" is not a verdict, and we have no positive evidence to offer.
    * a real strict compile, or a real `fully_resolved` over a real `variants.csv` → **`True`**.

    `None` rather than `False` for a pre-0.5 manifest, on the same distinction: `False` is a verdict
    about a module, `None` is an admission that we cannot make one, and painting a whole pre-existing
    catalogue scarlet on upgrade day would be the former standing in for the latter.

    **0.6 changed two of the three steps, and one module's verdict with them.** The positional test is
    now a pair of counts rather than a substring (`positionally_joinable`), and the vacuity test is now
    the denominator upstream published for it (`resolution_subjects`) rather than an inference from
    `resolution_mode is None`. Upstream states the rule as
    `resolution_subjects > 0 and (resolution_mode == "strict" or fully_resolved)` and names a *catalog*
    as its reader — this function is that reader.

    The changed verdict is worth stating, because it is a real reversal and not a refactor. A
    table-only module whose rows all carry coordinates used to land on `None`: nothing was resolved, we
    had no positive evidence, and "probably fine" is not a verdict. 0.6's positional fill (RM43) plus
    its counts supply that evidence — `positional_rows_placed == positional_rows` over a non-zero
    denominator says every row joins to a VCF by position — so such a module is now **`True`**. The
    reference PGx example is exactly this case: at 0.5 it was `False` (106 rows, none placed), and at
    0.6 the same 106 rows are placed from the `resolution.csv` it ships. Nothing about the module
    changed; the compiler learned to do what the warning had been complaining about.
    """
    if predates_resolution_contract(manifest):
        return None
    compilation = manifest.compilation
    joinable = positionally_joinable(manifest)
    if joinable is None:
        # Pre-0.6: the warning is the only record, and it only ever speaks in the negative.
        if joins_nothing_positionally(manifest):
            return False
    elif not joinable:
        return False

    if predates_positional_counts(manifest):
        # Pre-0.6, so `resolution_subjects` is a default rather than a measurement. The 0.5 rule
        # stands for these versions, unchanged — including its blind spot, which is the honest state
        # of the evidence a pre-0.6 manifest offers.
        if compilation.resolution_mode == "strict":
            return True
        if compilation.resolution_mode is None:
            return None
        return compilation.fully_resolved

    if compilation.resolution_subjects > 0:
        return compilation.resolution_mode == "strict" or compilation.fully_resolved
    # Nothing was resolved, so `fully_resolved` is `all()` over an empty list and says nothing. The
    # positional side may still carry the module: every row placed, over rows that exist, is positive
    # evidence that it joins — which is the question this facet answers.
    if joinable and (compilation.positional_rows or 0) > 0:
        return True
    return None


def version_facets(manifest: ModuleManifest) -> dict[str, Any]:
    """The `versions` columns projected from a manifest, as a column→value mapping.

    Licence facets are **tri-state**: `None` is not `False`. A source whose terms could not be
    established has not been shown to permit anything, so "unknown" must not read as "no" — and it
    must not read as "yes" either.
    """
    compilation = manifest.compilation
    sources = manifest.sources
    trusted = is_trusted(manifest)
    return {
        "resolution_mode": compilation.resolution_mode,
        "fully_resolved": int(compilation.fully_resolved),
        "trusted": None if trusted is None else int(trusted),
        "vrs_alleles": compilation.vrs_alleles,
        "vrs_identified": compilation.vrs_alleles_identified,
        "commercial_use": _tri(sources.commercial_use if sources else None),
        "redistribution": _tri(sources.redistribution if sources else None),
        # Only the *annotation* layer taints. A source consulted purely to look up a coordinate
        # contributed a fact every reference reports identically, so marking the module viral for it
        # would be a false positive — which is why the manifest keeps per-layer lists rather than one
        # boolean, and why this counts layers instead of sources.
        "share_alike": int(bool(sources.share_alike_layers)) if sources else 0,
        # Which derived fact tables this version carries (0.6). Presence of the manifest block is the
        # question — a block is written exactly when the compile had the table — so a legacy manifest
        # honestly projects `0` here rather than "unknown": the table did not exist to be omitted.
        "has_gene_validity": int(manifest.gene_validity is not None),
        "has_clinical_assertions": int(manifest.clinical_assertions is not None),
        "has_gwas_effects": int(manifest.gwas_effects is not None),
        "has_frequencies": int(manifest.frequency is not None),
        # Authored rather than derived, and the odd one out in kind: this says the module **stated**
        # what its weights mean, not that it has any. Filterable because "whose weights can I combine"
        # is the question S36 was actually asking, and an absent declaration answers it with *no*.
        "weighting_declared": int(manifest.weighting is not None),
        # The RM44/S31/S33 counters, projected so a version row and a parsed manifest cannot give
        # different answers. `None` throughout for a pre-0.6 compile — including `resolution_subjects`,
        # whose manifest default of `0` is the one value here that would silently lie.
        **_counters(manifest),
    }


def _counters(manifest: ModuleManifest) -> dict[str, Optional[int]]:
    """The 0.6 counters, or `None` for every one of them on a manifest that predates them.

    `resolution_subjects` needs the era gate more than its siblings, not less: the other four are
    already `int | None` upstream and arrive as `None` on their own, while this one is a plain `int`
    defaulting to `0`. Projected naively, every 0.5-era version in the catalog would report "nothing
    was resolved" — indistinguishable from a module where that is true, and exactly the vacuity the
    field was added to expose.
    """
    compilation = manifest.compilation
    if predates_positional_counts(manifest):
        return {
            "resolution_subjects": None,
            "positional_rows": None,
            "positional_rows_placed": None,
            "expanded_keys": None,
            "expanded_rows": None,
        }
    return {
        "resolution_subjects": compilation.resolution_subjects,
        "positional_rows": compilation.positional_rows,
        "positional_rows_placed": compilation.positional_rows_placed,
        "expanded_keys": compilation.expanded_keys,
        "expanded_rows": compilation.expanded_rows,
    }


def _tri(value: Optional[bool]) -> Optional[int]:
    return None if value is None else int(value)
