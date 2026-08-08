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


def is_trusted(manifest: ModuleManifest) -> Optional[bool]:
    """Whether a consumer should treat this version as fully-baked. `None` = predates the contract.

    The rule the format documents is a **disjunction**, and both halves are load-bearing:
    `resolution_mode == "strict" or fully_resolved`. Testing only the mode would mark every PGx-only
    module untrusted — `resolution_mode` is assigned inside the compiler's variants branch, so a
    module with no `variants.csv` has `None` there while `fully_resolved` is vacuously true. Testing
    only `fully_resolved` would miss a strict compile that resolved everything it was asked to.

    Returns `None` rather than `False` for a pre-0.5 manifest. The distinction matters: `False` is a
    verdict about a module, `None` is an admission that we cannot make one, and painting a whole
    pre-existing catalogue scarlet on upgrade day would be the former standing in for the latter.
    """
    if predates_resolution_contract(manifest):
        return None
    compilation = manifest.compilation
    return compilation.resolution_mode == "strict" or compilation.fully_resolved


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
