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


def test_the_listing_filters_by_pgs_id_and_the_clients_print_claims(client: TestClient, repo: Repository) -> None:
    from sdk_transport import sdk_transport
    from typer.testing import CliRunner

    from just_dna_registry import client_cli
    from just_dna_registry.client import RegistryClient

    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    version_id = repo.conn.execute("SELECT id FROM versions").fetchone()[0]
    repo.conn.execute("INSERT INTO version_pgs(version_id, pgs_id, trait_efo_id) VALUES (?, 'PGS000001', NULL)",
                      (version_id,))
    repo.conn.commit()
    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    assert [m["name"] for m in sdk.list_modules(pgs_id="pgs000001")["items"]] == ["coronary"]
    assert sdk.list_modules(pgs_id="PGS999999")["items"] == []

    original = client_cli._client
    client_cli._client = lambda url, token, **_k: RegistryClient(
        "http://testserver", transport=sdk_transport(client), check_version=False
    )
    try:
        out = CliRunner().invoke(client_cli.app, ["variant", "rs4244285"]).output
        assert "just-dna-seq/coronary" in out and "pair(s) compared" in out, out
        assert "1 variant(s) in 1 module(s)" in CliRunner().invoke(client_cli.app, ["gene", "CYP2C19"]).output
    finally:
        client_cli._client = original


# ── S32 (0.32): spellings fold, an empty answer says which, haplotypes keep their names ────────────────


def test_a_key_folds_onto_the_stored_spellings_and_never_guesses_a_strand_or_build() -> None:
    assert claims.key_spellings("RS429358") == ["RS429358", "rs429358"]
    assert claims.key_spellings("rs429358") == ["rs429358"]
    for pasted in ("chr19:44908684:T:C", "19-44908684-T-C", "Chr19_44908684_t_c", "19:44908684:t:c"):
        assert claims.key_spellings(pasted)[-1] == "19:44908684:T:C", pasted
    assert claims.key_spellings("chrX-100-A") == ["chrX-100-A", "X:100:A"]
    # Same statement only: no complement, no M→MT, a VRS id untouched (its digest is case-sensitive).
    assert claims.key_spellings("chr19:1:A:T")[-1] == "19:1:A:T"
    assert claims.key_spellings("chrM:73:A:G")[-1] == "M:73:A:G"
    vrs = "ga4gh:VA.CxiA7kzKmTtfP-xZ6sRuvWlJ2pj7pvIy"
    assert claims.key_spellings(vrs) == [vrs]


def test_the_route_folds_the_key_and_says_whether_any_spelling_is_stored(client: TestClient, repo: Repository) -> None:
    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    version_id = repo.conn.execute("SELECT id FROM versions").fetchone()[0]
    # The stored coordinate form, as `_aliases` writes it from `resolution_loci`, and a spelling a module
    # names with no claim behind it.
    repo.conn.executemany(
        "INSERT INTO claim_aliases(version_id, alias, variant_key, genome_build) VALUES (?, ?, ?, 'GRCh38')",
        [(version_id, "10:94781859:G:A", "rs4244285"), (version_id, "rs7777777", "rs7777777")],
    )
    repo.conn.commit()
    for pasted in ("rs4244285", "RS4244285", "chr10-94781859-g-a", "10:94781859:G:A"):
        found = client.get("/api/v1/variants", params={"key": pasted}).json()
        assert found["modules"] == ["just-dna-seq/coronary"] and found["matched"] is True, pasted
    unknown = client.get("/api/v1/variants", params={"key": "RS999999999"}).json()
    assert (unknown["claims"], unknown["matched"], unknown["spellings"]) == ([], False, ["RS999999999", "rs999999999"])
    silent = client.get("/api/v1/variants", params={"key": "rs7777777"}).json()
    assert (silent["claims"], silent["matched"]) == ([], True)


def test_a_haplotype_claim_carries_its_haplotypes_name() -> None:
    """Two haplotypes defined by one allele were byte-identical claims; the name tells them apart."""
    haplotypes = pl.DataFrame({
        "variant_key": ["rs3892097", "rs3892097"], "allele": ["T", "T"], "gene": ["CYP2D6", "CYP2D6"],
        "haplotype_name": ["*4", "*4.013"],
    })
    got = claims.project(_reader(haplotypes=haplotypes), "GRCh38").claims
    assert {(c.kind, c.haplotype) for c in got} == {("haplotype", "*4"), ("haplotype", "*4.013")}
    assert claims.PROJECTOR_VERSION != "1", "projector 1 rows carry no name; the bump is what re-projects them"


def test_a_stored_haplotype_name_is_served_and_printed(client: TestClient, repo: Repository) -> None:
    from sdk_transport import sdk_transport
    from typer.testing import CliRunner

    from just_dna_registry import client_cli
    from just_dna_registry.client import RegistryClient

    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    version_id = repo.conn.execute("SELECT id FROM versions").fetchone()[0]
    projection = claims.Projection(
        claims=[claims.Claim(kind="haplotype", variant_key="rs3892097", genotype="T", gene="CYP2D6", haplotype="*4")],
        aliases=[("rs3892097", "rs3892097", "GRCh38")],
    )
    repo.store_claims(version_id, projection, claims.PROJECTOR_VERSION)
    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    (claim,) = sdk.variant_claims("rs3892097")["claims"]
    assert (claim["kind"], claim["haplotype"]) == ("haplotype", "*4")
    original = client_cli._client
    # A fresh client per command: each one closes its client on the way out.
    client_cli._client = lambda url, token, **_k: RegistryClient(
        "http://testserver", transport=sdk_transport(client), check_version=False
    )
    try:
        out = CliRunner().invoke(client_cli.app, ["variant", "RS3892097"]).output
        assert "haplotype" in out and "*4" in out, out
        none = CliRunner().invoke(client_cli.app, ["variant", "rs999999999"]).output
        assert "no visible module spells this variant as any of: rs999999999" in none, none
    finally:
        client_cli._client = original


def test_the_sdk_quotes_a_gene_symbol_into_the_path(client: TestClient, repo: Repository) -> None:
    """Unquoted, a `?` or `#` in a symbol ends the path and the route never sees the symbol."""
    from sdk_transport import sdk_transport

    from just_dna_registry.client import RegistryClient

    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    for symbol in ("CYP2C19", "HLA?A", "C4#B", "TWO WORDS"):
        assert sdk.gene_claims(symbol)["gene"] == symbol, symbol
