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
