"""The variant-level catalog's projection (0.31): what a published version says about each variant, read
from its own parquets, kept for each module's latest version only, never failing a publish."""

import io

import polars as pl
from fastapi.testclient import TestClient
from test_handle_rename import _publish, _user

from just_dna_registry.db.repository import Repository
from just_dna_registry.services import claims


def _claims(repo: Repository, ns: str, name: str, version: str) -> list[dict]:
    return [dict(r) for r in repo.conn.execute(
        "SELECT c.* FROM version_claims c JOIN versions v ON v.id = c.version_id "
        "JOIN modules m ON m.id = v.module_id WHERE m.namespace = ? AND m.name = ? AND v.version = ?",
        (ns, name, version),
    ).fetchall()]


def _projector(repo: Repository, ns: str, name: str, version: str) -> str | None:
    return repo.conn.execute(
        "SELECT v.claims_projector FROM versions v JOIN modules m ON m.id = v.module_id "
        "WHERE m.namespace = ? AND m.name = ? AND v.version = ?", (ns, name, version),
    ).fetchone()[0]


def test_a_publish_projects_its_claims_and_keeps_only_the_latest(client: TestClient, repo: Repository) -> None:
    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    first = _claims(repo, "just-dna-seq", "coronary", "1.0.0")
    assert first and first[0]["kind"] == "weight" and first[0]["genotype"] == "A/G", first
    assert first[0]["rsid"] == "rs4244285" and first[0]["gene"] == "CYP2C19"
    assert _projector(repo, "just-dna-seq", "coronary", "1.0.0") == claims.PROJECTOR_VERSION
    aliases = {r[0] for r in repo.conn.execute("SELECT alias FROM claim_aliases").fetchall()}
    assert "rs4244285" in aliases

    _publish(client, key, "just-dna-seq", "coronary", "1.0.1", weight="-0.7")
    assert _claims(repo, "just-dna-seq", "coronary", "1.0.0") == []
    assert _projector(repo, "just-dna-seq", "coronary", "1.0.0") is None  # not projected, not "no claims"
    assert len(_claims(repo, "just-dna-seq", "coronary", "1.0.1")) == len(first)


def test_a_projection_that_fails_never_fails_the_publish(client: TestClient, repo: Repository, monkeypatch) -> None:
    def broken(*_a, **_k):
        raise ValueError("a parquet the projector cannot read")

    monkeypatch.setattr(claims, "project", broken)
    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    assert _projector(repo, "just-dna-seq", "coronary", "1.0.0") is None


def _reader(**tables: pl.DataFrame):
    def read(name: str) -> bytes | None:
        frame = tables.get(name.removesuffix(".parquet"))
        if frame is None:
            return None
        buf = io.BytesIO()
        frame.write_parquet(buf)
        return buf.getvalue()

    return read


def test_direction_is_projected_only_where_it_compares() -> None:
    """`direction` first, `state` for older modules; never a weight's sign, never `significant`."""
    weights = pl.DataFrame({
        "variant_key": ["rs1", "rs2", "rs3", "rs4"],
        "genotype": [["G", "A"], ["C", "C"], ["T", "C"], ["A", "A"]],
        "direction": ["risk", None, None, "contested"],
        "state": [None, "protective", "significant", None],
        "weight": [1.0, -2.0, 3.0, 0.5],
    })
    got = {c.variant_key: c for c in claims.project(_reader(weights=weights), "GRCh38").claims}
    assert (got["rs1"].direction, got["rs1"].direction_source, got["rs1"].genotype) == ("risk", "direction", "A/G")
    assert (got["rs2"].direction, got["rs2"].direction_source) == ("protective", "state")
    assert got["rs3"].direction is None and got["rs4"].direction is None


def test_columns_are_read_by_presence_and_each_table_is_its_own_kind() -> None:
    """A 0.7 parquet has no `vrs_id`; haplotypes and pharmacogenomic rows never carry a direction."""
    weights = pl.DataFrame({"variant_key": ["rs9"], "genotype": [["A", "G"]], "rsid": ["rs9"]})
    haplotypes = pl.DataFrame({"variant_key": ["rs9"], "allele": ["A"], "gene": ["CYP2D6"]})
    pgs = pl.DataFrame({"pgs_id": ["PGS000001"], "trait_efo_id": ["EFO_0001645"]})
    got = claims.project(_reader(weights=weights, haplotypes=haplotypes, pgs=pgs), "GRCh37")
    kinds = {(c.kind, c.direction) for c in got.claims}
    assert kinds == {("weight", None), ("haplotype", None)}
    assert all(c.genome_build == "GRCh37" for c in got.claims)
    assert ("rs9", "rs9", "GRCh37") in got.aliases and got.pgs == [("PGS000001", "EFO_0001645")]


def test_a_backfill_projects_what_was_published_before_and_skips_what_is_current(
    client: TestClient, repo: Repository, app
) -> None:
    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    repo.conn.execute("DELETE FROM version_claims")
    repo.conn.execute("UPDATE versions SET claims_projector = NULL")
    repo.conn.commit()

    first = claims.backfill(repo, app.state.storage)
    assert first.projected == ["just-dna-seq/coronary@1.0.0"] and first.failed == []
    assert _claims(repo, "just-dna-seq", "coronary", "1.0.0")
    again = claims.backfill(repo, app.state.storage)
    assert (again.projected, again.current) == ([], 1)
    assert claims.backfill(repo, app.state.storage, every=True).projected == ["just-dna-seq/coronary@1.0.0"]


def _weight(module: str, **kw) -> dict:
    base = {"kind": "weight", "module": module, "genome_build": "GRCh38", "genotype": "C/C",
            "trait_efo_id": "EFO_1", "effect_allele": "C", "direction": "risk", "direction_source": "direction"}
    return {**base, **kw}


def test_the_conflict_marker_compares_one_allele_one_trait_one_genotype() -> None:
    """Opposite directions are a conflict only for the same effect allele, genotype and trait; everything else
    is counted as not compared, by reason, so silence never reads as agreement."""
    out = claims.conflicts([_weight("a/m"), _weight("b/m", direction="protective")])
    assert len(out["pairs"]) == 1 and out["compared"] == 1
    # One claim seen from opposite alleles is not a conflict (the critic's 8 of 18).
    other = claims.conflicts([_weight("a/m"), _weight("b/m", effect_allele="T", direction="protective")])
    assert other["pairs"] == [] and other["incomparable"] == {"other_effect_allele": 1}
    traits = claims.conflicts([_weight("a/m"), _weight("b/m", trait_efo_id="EFO_2", direction="protective")])
    assert traits["pairs"] == [] and traits["incomparable"] == {"other_trait": 1}
    none = claims.conflicts([_weight("a/m", trait_efo_id=None), _weight("b/m", direction="protective")])
    assert none["incomparable"] == {"no_trait": 1}
    state = claims.conflicts([_weight("a/m", direction_source="state"), _weight("b/m", direction="protective")])
    assert state["incomparable"] == {"no_effect_allele_or_direction": 1}
    strand = claims.conflicts([_weight("a/m", effect_allele="A"), _weight("b/m", effect_allele="T", direction="protective")])
    assert strand["incomparable"] == {"allele_not_orientable": 1}
    assert claims.conflicts([_weight("a/m"), _weight("a/m", direction="protective")])["pairs"] == []


def test_the_routes_answer_by_any_spelling_and_say_what_is_not_projected(
    client: TestClient, repo: Repository
) -> None:
    from sdk_transport import sdk_transport

    from just_dna_registry.client import RegistryClient

    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    found = sdk.variant_claims("rs4244285")
    assert found["modules"] == ["just-dna-seq/coronary"] and found["claims"][0]["genotype"] == "A/G"
    assert found["not_projected"] == 0 and found["conflicts"]["pairs"] == []
    by_gene = sdk.gene_claims("cyp2c19")
    assert by_gene["modules"] == ["just-dna-seq/coronary"] and by_gene["variants"] == 1
    assert sdk.variant_claims("rs999999999")["claims"] == []

    repo.conn.execute("UPDATE versions SET claims_projector = NULL")
    repo.conn.execute("DELETE FROM version_claims")
    repo.conn.commit()
    unprojected = sdk.variant_claims("rs4244285")
    assert unprojected["claims"] == [] and unprojected["not_projected"] == 1


def test_a_test_namespace_is_hidden_on_production(client: TestClient, repo: Repository) -> None:
    key = _user(repo, "sandboxer", namespace="test-space")
    client.post("/api/v1/modules/test-space/coronary/versions",
                data={"version": "1.0.0", "allow_test_data": "true"},
                files=[("files", (n, d, "text/plain")) for n, d in __import__("test_handle_rename")._spec("coronary").items()],
                headers={"Authorization": f"Bearer {key}"})
    assert repo.get_module_row("test-space", "coronary") is not None
    assert client.get("/api/v1/variants", params={"key": "rs4244285"}).json()["modules"] == []
