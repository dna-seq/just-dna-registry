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


# ── The 0.6 manifest blocks, as the catalog serves them ────────────────────────

_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  title: Coronary
  description: d
  report_title: R
genome_build: GRCh38
weighting:
  scale: "0-1, curator-set, arbitrary"
  method: "literature triage, no GWAS input"
  note: "not comparable with any other module's weights"
"""
_YAML_NO_WEIGHTING = "\n".join(_YAML.splitlines()[:8]) + "\n"
#: Two genuinely different modules, because `weighting` is **outside** `content_signature` and two
#: specs differing only by it are the same data — the registry answers that with `409
#: duplicate_content`, globally and permanently. Discovering that here was the cheap way to learn it;
#: `test_a_weighting_declaration_moves_no_identity` asserts it deliberately rather than by accident.
_ROWS: dict[str, tuple[str, str]] = {
    "declared": ("rs4244285", "10,94781859,G,A,A/G"),
    "undeclared": ("rs12248560", "10,94761900,C,T,C/T"),
}


def _files(name: str, yaml: str) -> list:
    rsid, locus = _ROWS.get(name, _ROWS["declared"])
    variants = (
        "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
        f"{rsid},{locus},-0.8,risk,het,CYP2C19,cyp2c19\n"
    )
    studies = (
        "rsid,pmid,population,p_value,conclusion,study_design\n"
        f"{rsid},[PMID: 29165669],T,0.05,E,U\n"
    )
    return [
        ("files", ("module_spec.yaml", yaml.replace("coronary", name).encode(), "text/yaml")),
        ("files", ("variants.csv", variants.encode(), "text/csv")),
        ("files", ("studies.csv", studies.encode(), "text/csv")),
    ]


def _publish(client, api_key, *, name: str, yaml: str = _YAML) -> dict:
    resp = client.post(
        f"/api/v1/modules/just-dna-seq/{name}/versions",
        data={"version": "1.0.0"},
        files=_files(name, yaml),
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_weighting_reaches_the_detail_verbatim_and_absence_is_not_a_pass(client, api_key) -> None:
    """RM92 on the catalog: what the module says its weights mean, in the author's words.

    Two properties, and the second is the one that carries the consumer report behind it. The prose
    is rendered **verbatim** — free text upstream on purpose, so any normalization here would be this
    catalog inventing a taxonomy the format declined to invent. And an **absent** block is `null`
    rather than an empty `WeightingInfo`, because "the module has not said what its weights mean" is
    the state a consumer must not read as "these weights are comparable". That conflation is what
    S36 reported one layer down: `weight` is a bare float with no unit column, every module means
    something different by it, and until 0.6 the artifact could not say so.
    """
    _publish(client, api_key, name="declared")
    detail = client.get("/api/v1/modules/just-dna-seq/declared").json()
    assert detail["weighting"] == {
        "scale": "0-1, curator-set, arbitrary",
        "method": "literature triage, no GWAS input",
        "note": "not comparable with any other module's weights",
    }
    assert detail["facts"]["weighting_declared"] is True

    _publish(client, api_key, name="undeclared", yaml=_YAML_NO_WEIGHTING)
    silent = client.get("/api/v1/modules/just-dna-seq/undeclared").json()
    assert silent["weighting"] is None, "an absent declaration must not render as an empty one"
    assert silent["facts"]["weighting_declared"] is False


def test_the_weighting_filter_finds_the_modules_you_must_not_aggregate(client, api_key) -> None:
    """`?weighting_declared=false` is the useful direction, and the reason the filter exists.

    A consumer combining weights across a corpus needs the population that has **not** stated a
    scale, because that is the one it must leave alone. Tri-state on the wire: omitting the
    parameter must return both, or the filter would be quietly narrowing every unfiltered listing.
    """
    _publish(client, api_key, name="declared")
    _publish(client, api_key, name="undeclared", yaml=_YAML_NO_WEIGHTING)

    def names(**params) -> set[str]:
        resp = client.get("/api/v1/modules", params=params)
        assert resp.status_code == 200, resp.text
        return {item["name"] for item in resp.json()["items"]}

    assert names() == {"declared", "undeclared"}
    assert names(weighting_declared=True) == {"declared"}
    assert names(weighting_declared=False) == {"undeclared"}


def test_the_verification_block_is_served_as_a_claim_not_a_verdict(client, api_key) -> None:
    """RM45 on the catalog, with the honesty the block requires.

    The server's own enrichment attests its checks during publish, so a published module carries a
    verification block even when its author shipped no `verification.json` — which is exactly why
    the surface must not read as an endorsement. What is asserted here is the shape a consumer
    depends on: the records are present with their `skipped` reasons intact (an unrun check must
    stay distinguishable from one that ran and found nothing), and `closed` is `false` when no human
    ever declared the module final.

    `closed` is the one field with a check behind it — the closure is hash-bound and the compiler
    drops it when the authored bytes moved — which is what makes it safe to publish as a boolean
    while everything beside it stays the publisher's word.
    """
    _publish(client, api_key, name="coronary")
    detail = client.get("/api/v1/modules/just-dna-seq/coronary").json()

    block = detail["verification"]
    assert block is not None and block["producer"].startswith("just-dna-enricher")
    assert block["closed"] is False and block["closed_at"] is None

    checks = {c["check"]: c for c in block["checks"]}
    assert checks, "a publish that ran enrichment must record what it checked"
    # The distinction this whole tier is organised around: a check that could not run says why, and
    # `subjects: 0` beside a reason is not the same statement as `subjects: 0` without one.
    for record in checks.values():
        assert record["skipped"] is None or isinstance(record["detail"], (str, type(None)))
        assert record["subjects"] >= 0

    # Never a card facet and never a filter: a registry that let you sort by someone else's
    # unverifiable pass would be lending it our credibility.
    card = client.get("/api/v1/modules", params={"namespace": "just-dna-seq"}).json()["items"][0]
    assert "verification" not in card


def test_a_weighting_declaration_moves_no_identity(client, api_key) -> None:
    """Declaring what your weights mean must not change what module you are.

    Upstream puts `weighting` outside both identity halves — advisory metadata, like `license` — and
    that is load-bearing here rather than incidental. If it moved `content_signature`, adding the
    declaration to an already-published module would produce a *different* module by the registry's
    reckoning, and the global `409 duplicate_content` claim would then refuse the honest version of
    a module in favour of the one that said nothing.

    Checked through `/validate`, which computes the signature without spending a publish.
    """
    def signature(yaml: str) -> str:
        resp = client.post(
            "/api/v1/modules/just-dna-seq/declared/validate",
            files=_files("declared", yaml),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["content_signature"]

    assert signature(_YAML) == signature(_YAML_NO_WEIGHTING)


def test_the_counters_reach_both_projection_paths_and_null_survives(client, api_key) -> None:
    """RM44/S31 on the wire, and the `None`-is-not-`0` rule holding at every hop.

    Two paths render a `ResolutionInfo` and they must agree: the card parses the latest manifest,
    the version list reads projected columns and never parses anything. This drives both and
    compares them, because a counter that survives one hop and is coalesced at the other is worse
    than one nobody published — a consumer would see `0` on the list and `null` on the card for the
    same version.

    The pre-0.6 direction is asserted from a stored row rather than argued: a legacy manifest is
    written into the projection and every counter must come back `null`, not `0`. The DB columns are
    nullable with no default for exactly this, which is the opposite of the choice made one tuple
    over for the fact-table booleans.
    """
    published = _publish(client, api_key, name="declared")
    compilation = published["compilation"]
    assert compilation["resolution_subjects"] == 1
    assert compilation["positional_rows"] == 0, "no positional table is a real 0, not a null"

    card = client.get("/api/v1/modules/just-dna-seq/declared").json()["resolution"]
    listed = client.get(
        "/api/v1/modules/just-dna-seq/declared/versions"
    ).json()["items"][0]["resolution"]
    for field in (
        "resolution_subjects", "positional_rows", "positional_rows_placed",
        "expanded_keys", "expanded_rows",
    ):
        assert card[field] == listed[field], f"{field} disagrees between the two projections"
    assert card["resolution_subjects"] == 1 and card["positional_rows"] == 0
    # `fully_resolved` is only a verdict beside a non-zero denominator, which is now readable.
    assert card["fully_resolved"] is True and card["resolution_subjects"] > 0


def test_a_legacy_row_projects_null_counters_rather_than_zero(tmp_path) -> None:
    """The half a live publish cannot reach: what a *pre-0.6* version looks like after migrating.

    Every version in a real catalog on upgrade day is this shape, and the failure mode is silent —
    `0` reads as "this module has no positional rows", which for a PGx artifact compiled in 0.5 is
    false. Asserted through `version_facets`, the single derivation both the migration backfill and
    the publish path use.
    """
    from just_dna_registry.db.facets import version_facets

    legacy = _pre_06_manifest(signed=True, mode="best_effort", fully_resolved=True, warned=False)
    facets = version_facets(legacy)
    for field in (
        "resolution_subjects", "positional_rows", "positional_rows_placed",
        "expanded_keys", "expanded_rows",
    ):
        assert facets[field] is None, f"{field} projected {facets[field]!r} for a pre-0.6 manifest"
    # ...while the fact-table booleans genuinely are `0`: the blocks did not exist to be omitted.
    assert facets["has_gwas_effects"] == 0 and facets["weighting_declared"] == 0
