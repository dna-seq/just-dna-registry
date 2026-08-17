"""
Format 0.6 adoption (registry 0.17): the properties the upgrade procedure asserts to operators.

Distinct from `test_v06.py`, which is this *registry's* own 0.6.0 release (stars, membership,
popularity) and has nothing to do with the format. The collision of numbers is unfortunate and the
two files are kept apart rather than merged for exactly that reason.

What lives here is the evidence behind claims `docs/UPGRADE.md` makes to someone about to run a
catalog-wide migration. A sentence in an operator note is only as good as the test under it, and the
expensive ones to get wrong are the reassurances: "no stored verdict moves", "no `content_signature`
moves", "you do not need to re-derive signatures".
"""

from itertools import product

from just_dna_format.manifest import ModuleManifest

from just_dna_registry.db.facets import UNJOINABLE_PHRASE, is_trusted

_BASE = {
    "schema_version": "1.0",
    "module": {"name": "m", "title": "T", "description": "d", "report_title": "R"},
    "identity": {"namespace": "ns", "name": "m", "version": "1.0.0"},
    "display": {
        "title": "T", "description": "d", "report_title": "R", "icon": "dna", "color": "#21ba45",
    },
    "genome_build": "GRCh38",
    "artifact": {"digest": "sha256:" + "0" * 64, "files": []},
}


def _pre_06_manifest(*, signed: bool, mode, fully_resolved: bool, warned: bool) -> ModuleManifest:
    """A manifest shaped exactly as a 0.5-era compile left it, parsed by the 0.6 models."""
    doc = dict(_BASE)
    doc["content_signature"] = ("sha256:" + "a" * 64) if signed else None
    doc["compilation"] = {
        "compile_success": True,
        "resolution_mode": mode,
        "fully_resolved": fully_resolved,
        "warnings": (
            [f"haplotypes.csv: 2 of 2 row(s) {UNJOINABLE_PHRASE}, so this table joins by rsID only."]
            if warned
            else []
        ),
    }
    return ModuleManifest.model_validate(doc)


def _the_0_5_rule(manifest: ModuleManifest):
    """`is_trusted` exactly as 0.16.2 shipped it, kept here as the differential baseline.

    A copy of superseded logic is normally a smell. It earns its place because the claim it checks is
    the one an operator acts on — that adopting 0.6 re-judges nothing already in their catalog — and
    the only way to check that is to run both rules over the same inputs. Delete it when the last
    pre-0.6 version is gone from every deployment, which is the same moment the fallback in
    `db/facets.py` can go.
    """
    if manifest.content_signature is None:
        return None
    compilation = manifest.compilation
    if any(UNJOINABLE_PHRASE in w for w in compilation.warnings):
        return False
    if compilation.resolution_mode == "strict":
        return True
    if compilation.resolution_mode is None:
        return None
    return compilation.fully_resolved


def test_adopting_0_6_re_judges_nothing_already_published() -> None:
    """The reason `docs/UPGRADE.md` §0.17 ships **no** trust migration, unlike 0.11.3.

    0.11.3 changed the rule out from under stored values and needed `_migrate_0_11_3_trust` to
    re-project them. 0.17 changes the rule too — counts instead of prose, a published denominator
    instead of an inference — but only for manifests that *carry* the new counters, and no version in
    any existing catalog does. The pre-0.6 branch of `is_trusted` is the 0.5 rule unchanged, so every
    stored verdict stays exactly where it is until a version is recompiled onto 0.6 by
    `registry upgrade`, which republishes as a new PATCH and projects its facets fresh.

    Checked exhaustively over the pre-0.6 shape space rather than on a sample: 2 × 3 × 2 × 2 = 24
    combinations of (speaks the 0.5 contract, resolution policy, outcome, warned). A single
    divergence here means the upgrade note is wrong and a migration is owed.
    """
    for signed, mode, fully_resolved, warned in product(
        [True, False], [None, "strict", "best_effort"], [True, False], [True, False]
    ):
        manifest = _pre_06_manifest(
            signed=signed, mode=mode, fully_resolved=fully_resolved, warned=warned
        )
        # The premise: parsed by 0.6 models, a 0.5 manifest has no counters. `positional_rows` is
        # `None` (the era witness) while `resolution_subjects` defaults to a misleading `0` — which
        # is why the era test cannot be the latter.
        assert manifest.compilation.positional_rows is None
        assert manifest.compilation.resolution_subjects == 0

        assert is_trusted(manifest) == _the_0_5_rule(manifest), (
            f"verdict moved for (signed={signed}, mode={mode}, "
            f"fully_resolved={fully_resolved}, warned={warned})"
        )
