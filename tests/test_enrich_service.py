"""
Unit tests for `services/enrich.py` — the seam where the network tier is wired.

Three things worth pinning that no HTTP test reaches:

* **The tier boundary.** CONSTITUTION Principle 2 says the compile path never imports the enricher.
  That is enforceable only because the import is lazy, and enforceable *forever* only because a test
  checks it.
* **VRS coverage**, which since enricher 0.5.1 (RM40) the registry *projects* rather than derives —
  so what is worth pinning moved: not the arithmetic, but that a dry run's numbers still equal the
  ones the compiler independently stamps into the manifest.
* **Cache resolution**, where the difference between "as configured" and "as resolved" decides
  whether a deployment can be pinned at all.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from just_dna_registry.config import Settings
from just_dna_registry.services.enrich import (
    EnrichmentGate,
    enricher_available,
    EnrichOutcome,
    available_references,
    configured_caches,
    unresolved_hint,
    vrs_coverage,
)


# ── The tier boundary ─────────────────────────────────────────────────────────


def test_the_compile_path_does_not_import_the_enricher() -> None:
    """CONSTITUTION Principle 2, made mechanical.

    `services/publish.py` runs the compile. If it ever gains a module-level `just_dna_enricher`
    import — directly or through something it imports — the compile path is importing the network
    tier, and the guarantee that the compiler cannot fetch stops being structural. Checked in a fresh
    interpreter, because in this one the enricher is already imported by other tests.
    """
    probe = (
        "import sys; import just_dna_registry.services.publish; "
        "print('just_dna_enricher' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False", out.stdout


# ── VRS coverage ──────────────────────────────────────────────────────────────


def test_vrs_coverage_projects_the_enrichers_own_counters() -> None:
    """Since enricher 0.5.1 (RM40) the counting is upstream's and this only renders it.

    That is the whole value of the RM: through 0.11 the registry counted slots itself over
    `EnrichmentResult.rows`, because `enrich()` computed a `MintResult` and dropped it — so a dry run
    could disagree with the manifest a publish would stamp from the same data. What is left to test
    is that nothing is re-derived here, including `complete`, which is the enricher's derivation
    rather than a comparison repeated on this side.
    """

    @dataclass
    class _Mint:  # the shape of `just_dna_enricher.vrs.MintResult`
        alleles: int
        identified: int
        complete: bool
        unmintable_reasons: dict[str, int]

    coverage = vrs_coverage(
        _Mint(alleles=4, identified=2, complete=False, unmintable_reasons={"indel: needs seq": 2})
    )
    assert (coverage.alleles, coverage.identified, coverage.complete) == (4, 2, False)
    # The actionable half, previously reachable only as a log line.
    assert coverage.unmintable_reasons == {"indel: needs seq": 2}


def test_vrs_coverage_distinguishes_not_minted_from_a_coverage_of_zero() -> None:
    """`None` in means the pass did not run, which is not the same as running and naming nothing.

    Both render `alleles == 0`, so the difference has to live in `complete`: never `True` (that would
    claim a vacuous success), and never `False` for a table that was never asked about.
    """
    assert vrs_coverage(None).complete is None
    assert vrs_coverage(None).unmintable_reasons == {}


def test_a_dry_run_reports_the_same_coverage_the_manifest_will_carry(tmp_path: Path) -> None:
    """The guarantee RM40 buys, end to end rather than by construction.

    `manifest.compilation.vrs_alleles` / `vrs_alleles_identified` are stamped by the *compiler* from
    the resolution table; `/check` reports the *enricher's* counters for the same table. Two
    independent producers of one number, which is exactly the shape that drifts — so this publishes
    and dry-runs the same spec and demands they agree.
    """
    from fastapi.testclient import TestClient

    from just_dna_registry.api.app import create_app

    empty = tmp_path / "no-cache"
    client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "m.db", local_storage_dir=tmp_path / "a",
                ensembl_cache=empty, clinvar_cache=empty, constraint_cache=empty,
            )
        )
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    auth = {"Authorization": "Bearer mk_live_testkey"}

    yaml = (
        'schema_version: "1.0"\nmodule:\n  name: coronary\n  title: C\n  description: d\n'
        "  report_title: C\ngenome_build: GRCh38\n"
    )
    variants = (
        "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
        "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
    )
    studies = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"
    parts = [
        ("files", ("module_spec.yaml", yaml.encode(), "text/yaml")),
        ("files", ("variants.csv", variants.encode(), "text/csv")),
        ("files", ("studies.csv", studies.encode(), "text/csv")),
    ]

    check = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True}, files=parts, headers=auth,
    )
    assert check.status_code == 200, check.text
    reported = check.json()["enrichment"]["vrs"]

    published = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"}, files=parts, headers=auth,
    )
    assert published.status_code == 201, published.text
    compilation = published.json()["compilation"]

    assert reported["alleles"] == compilation["vrs_alleles"]
    assert reported["identified"] == compilation["vrs_alleles_identified"]


# ── Cache resolution ──────────────────────────────────────────────────────────


def test_configured_caches_passes_the_setting_through_unresolved(tmp_path: Path) -> None:
    """What the enricher is handed must be the configured path, even when nothing is there.

    Resolving first and passing the result would send `None` for an empty cache, and `None` tells the
    enricher to go looking — which is exactly the ambient discovery the setting exists to forbid.
    """
    empty = tmp_path / "not-provisioned"
    settings = Settings(ensembl_cache=empty, clinvar_cache=empty, constraint_cache=empty)
    assert configured_caches(settings)["ensembl"] == empty
    # ...while *resolution* correctly reports there is nothing usable there.
    assert available_references(settings)["ensembl"] is None


def test_available_references_ignores_ambient_state_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit setting must win over the environment, or CI and production disagree."""
    monkeypatch.setenv("JUST_DNA_ENSEMBL_CACHE", "/somewhere/else/entirely")
    monkeypatch.setenv("JUST_DNA_PIPELINES_CACHE_DIR", "/another/place")
    settings = Settings(ensembl_cache=tmp_path / "empty")
    assert available_references(settings)["ensembl"] is None


# ── Actionability of the failure ──────────────────────────────────────────────


def test_the_unresolved_hint_names_both_remedies() -> None:
    """A strict refusal has two possible fixers — the author and the operator — and the message has
    to reach whichever one is reading it."""
    outcome = EnrichOutcome(ran=True, offline=True, unresolved=["rs1", "rs2"])
    hint = unresolved_hint(outcome, Settings())
    assert "2 variant(s) unresolved" in hint
    assert "warm-caches" in hint  # the operator's move
    assert "variants.csv" in hint  # the author's move


def test_the_hint_explains_a_skipped_enrichment_differently() -> None:
    outcome = EnrichOutcome(ran=False, skipped_reason="enrichment disabled")
    assert "enrichment disabled" in unresolved_hint(outcome, Settings())


# ── The concurrency gate ──────────────────────────────────────────────────────


def test_the_gate_rejects_rather_than_queues() -> None:
    """Queueing behind a multi-minute paced run converts a fast 503 into a slow timeout."""
    gate = EnrichmentGate(1)
    assert gate.try_acquire() is True
    assert gate.try_acquire() is False
    assert gate.active == 1
    gate.release()
    assert gate.active == 0
    assert gate.try_acquire() is True


def test_the_gate_floors_at_one() -> None:
    """A misconfigured 0 must not disable enrichment silently."""
    assert EnrichmentGate(0).try_acquire() is True


# ── declared_use: the third axis ──────────────────────────────────────────────


def test_declared_use_is_validated_at_config_time() -> None:
    """A typo'd deployment value must fail at boot, not silently read as `unstated` and quietly skip
    every PGx source for the life of the deployment."""
    import pytest as _pytest

    assert Settings(declared_use="non_commercial").declared_use == "non_commercial"
    with _pytest.raises(ValueError, match="declared_use must be one of"):
        Settings(declared_use="noncommercial")  # the hyphenless CLI spelling, which is not the vocab


def test_the_pgx_sources_all_forbid_sale() -> None:
    """The premise the gating rests on. If an upstream ever relicensed, `unstated` would start
    fetching it and this test is where we would find out."""
    from just_dna_enricher.licensing import CPIC_TERMS, PHARMVAR_TERMS, check_declared_use

    for terms in (CPIC_TERMS, PHARMVAR_TERMS):
        assert terms.commercial_use is False
        assert check_declared_use(terms, "unstated") is not None  # skipped, with a reason
        assert check_declared_use(terms, "non_commercial") is None  # proceed


def test_a_missing_snapshot_is_not_an_unavailability(tmp_path: Path) -> None:
    """The corrected contract. A snapshot is what makes *offline* resolution possible; an online run
    reaches live Ensembl without one. Raising here would refuse the configuration that works."""
    settings = Settings(
        ensembl_cache=tmp_path / "empty",
        clinvar_cache=tmp_path / "empty",
        constraint_cache=tmp_path / "empty",
    )
    assert all(v is None for v in available_references(settings).values())
    assert enricher_available()  # ...and the tier itself is present, which is what a 503 would mean
