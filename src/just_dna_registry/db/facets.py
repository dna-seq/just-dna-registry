"""
Per-version facets derived from a manifest, in one place.

Three callers need the same derivation and must not disagree: the insert on publish, the refresh
after an out-of-digest amendment (a logo swap), and the 0.11 backfill migration. A second
implementation anywhere is a catalog that filters differently from how it indexes.
"""

from typing import Any, Optional

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


#: The factual core of the compiler's positional-joinability warning (compiler 0.5.3). Matched as a
#: substring because the sentence around it names a table and two counts.
#:
#: Prose-coupled, which is not where this belongs and is exactly what the registry asked the format
#: for in `CONSUMER_SUGGESTIONS.md` S8 (upstream RM43): a structured `checks_run`/`checks_skipped` on
#: the manifest would make this a field lookup. Until then the warning is the only *durable* record —
#: it rides in `manifest.compilation.warnings`, which is what `is_trusted` can still see at reindex
#: time, when the spec directory is long gone. Two things keep the coupling honest: a test compiles a
#: real rsid-authored spec through the real compiler and asserts this fires, so an upstream reword
#: breaks the build instead of silently re-granting trust; and the miss direction is `None`
#: ("cannot say"), never `True`.
UNJOINABLE_MARKER = "have no chrom+start"


def joins_nothing_positionally(manifest: ModuleManifest) -> bool:
    """Whether the compiler reported a table in this version that no VCF can join by position."""
    return any(UNJOINABLE_MARKER in w for w in manifest.compilation.warnings)


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
    """
    if predates_resolution_contract(manifest):
        return None
    compilation = manifest.compilation
    if joins_nothing_positionally(manifest):
        return False
    if compilation.resolution_mode == "strict":
        return True
    if compilation.resolution_mode is None:
        # No `variants.csv`, so `fully_resolved` is an empty `all()` and says nothing on its own.
        return None
    return compilation.fully_resolved


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
    }


def _tri(value: Optional[bool]) -> Optional[int]:
    return None if value is None else int(value)
