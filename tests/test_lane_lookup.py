"""Keyed lane lookups (0.30): every lane's rows by identifier keys, local or from the published repo.

Local reads run against this machine's real snapshots where present, with the socket tripwire armed; the
remote branch is driven by pointing the repo listing at local files, so its bounds are tested with no
network."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sdk_transport import sdk_transport
from test_preflight_api import no_network, pinned_environment  # noqa: F401 — autouse fixtures

from just_dna_registry.api.app import create_app
from just_dna_registry.client import RegistryClient, RegistryError
from just_dna_registry.client_cli import _lane_terms_lines
from just_dna_registry.config import Settings
from just_dna_registry.services import lanes

_CACHE = Path("/data/just-dna-cache")


def _client(tmp_path: Path, **over) -> TestClient:
    return TestClient(create_app(Settings(db_path=tmp_path / "r.db", local_storage_dir=tmp_path / "a", **over)))


@pytest.mark.skipif(not (_CACHE / "gnomad_constraint").is_dir(), reason="needs this machine's constraint snapshot")
def test_a_local_lane_answers_by_key_with_no_egress(tmp_path) -> None:
    client = _client(tmp_path, constraint_cache=_CACHE / "gnomad_constraint")
    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    tables = sdk.lane_tables("constraint")
    assert tables["served_from"] == "local" and "gene" in tables["tables"][0]["keys"]
    found = sdk.lane_rows("constraint", "gnomad_constraint", {"gene": ["LPA", "APOB"]})
    assert found["served_from"] == "local" and {r["gene"] for r in found["rows"]} == {"LPA", "APOB"}
    assert found["truncated"] is False


@pytest.mark.parametrize(
    ("keys", "code"),
    [({}, "lane_needs_keys"), ({"category": ["x"]}, "unknown_key"), ({"chrom": ["1"]}, "position_needs_both")],
)
def test_nothing_enumerates_a_lane(tmp_path, keys: dict, code: str) -> None:
    resp = _client(tmp_path).post("/api/v1/lanes/constraint/gnomad_constraint", json={"keys": keys})
    assert resp.status_code == 422 and resp.json()["detail"]["error"] == code, resp.text


def test_keys_are_bounded_per_request(tmp_path) -> None:
    resp = _client(tmp_path, lane_max_keys=2).post(
        "/api/v1/lanes/constraint/gnomad_constraint", json={"keys": {"gene": ["A", "B", "C"]}}
    )
    assert resp.status_code == 422 and resp.json()["detail"]["error"] == "too_many_keys"


def test_an_unknown_lane_is_a_404(tmp_path) -> None:
    sdk = RegistryClient("http://testserver", transport=sdk_transport(_client(tmp_path)), check_version=False)
    with pytest.raises(RegistryError) as refused:
        sdk.lane_rows("no_such_lane", "t", {"gene": ["X"]})
    assert refused.value.status_code == 404


def _fake_remote(tmp_path: Path, monkeypatch, *, size: int, lane: str = "alphagenome_avi") -> None:
    """The remote branch with the hub swapped for local files: the lane is not held, its repo lists them."""
    import polars as pl

    data = tmp_path / "hub"
    data.mkdir(exist_ok=True)
    for chrom in ("21", "22"):
        pl.DataFrame({"chrom": [f"chr{chrom}"] * 3, "pos": [1, 2, 3], "ref": ["A", "C", "G"]}).write_parquet(
            data / f"avi-chr{chrom}.parquet"
        )
    monkeypatch.setattr(lanes, "lane_presence", lambda settings: {lane: None})
    monkeypatch.setattr(lanes, "_repo", lambda name: f"just-dna-seq/{name}")
    monkeypatch.setattr(
        lanes, "_remote_files", lambda repo: [(str(p), size) for p in sorted(data.glob("*.parquet"))]
    )


def test_a_lane_the_box_does_not_hold_is_read_from_its_repo_by_position(tmp_path, monkeypatch) -> None:
    _fake_remote(tmp_path, monkeypatch, size=10)
    found = lanes.lookup("alphagenome_avi", "avi", {"chrom": ["22"], "start": [2]}, Settings())
    assert found.served_from == "remote:just-dna-seq/alphagenome_avi"
    assert found.rows == [{"chrom": "chr22", "pos": 2, "ref": "C"}]


def test_positions_match_as_pairs_never_as_a_cross_product(tmp_path, monkeypatch) -> None:
    """0.32.1: `chrom[i]` goes with `start[i]`. Asked for chr21:1 and chr22:3, the cross product also returned
    chr21:3 and chr22:1, rows nobody asked for. Unequal lengths keep the any-of-each meaning (v1 unchanged)."""
    _fake_remote(tmp_path, monkeypatch, size=10)
    paired = lanes.lookup("alphagenome_avi", "avi", {"chrom": ["21", "chr22"], "start": [1, 3]}, Settings())
    assert {(r["chrom"], r["pos"]) for r in paired.rows} == {("chr21", 1), ("chr22", 3)}
    one_chrom = lanes.lookup("alphagenome_avi", "avi", {"chrom": ["22"], "start": [1, 3]}, Settings())
    assert {(r["chrom"], r["pos"]) for r in one_chrom.rows} == {("chr22", 1), ("chr22", 3)}
    crossed = lanes.lookup("alphagenome_avi", "avi", {"chrom": ["21", "22"], "start": [1, 2, 3]}, Settings())
    assert len(crossed.rows) == 6


def test_a_big_remote_table_needs_a_position_key(tmp_path, monkeypatch) -> None:
    _fake_remote(tmp_path, monkeypatch, size=3_000_000_000)
    with pytest.raises(lanes.LaneLookupError) as refused:
        lanes.lookup("alphagenome_avi", "avi", {"ref": ["C"]} | {"rsid": ["rs1"]}, Settings())
    assert refused.value.code in {"unknown_key", "remote_needs_position"}
    with pytest.raises(lanes.LaneLookupError) as unbounded:
        lanes.lookup("alphagenome_avi", "avi", {"rsid": ["rs1"]}, Settings())
    assert unbounded.value.code == "remote_needs_position"


def test_a_lane_neither_held_nor_published_says_so(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lanes, "lane_presence", lambda settings: {"pharmvar": None})
    with pytest.raises(lanes.LaneLookupError) as refused:
        lanes.lookup("pharmvar", "alleles", {"gene": ["CYP2D6"]}, Settings())
    assert (refused.value.code, refused.value.status) == ("lane_not_available", 404)


def test_every_answer_carries_the_lanes_terms_as_upstream_states_them(tmp_path, monkeypatch) -> None:
    """S29 (0.32): a keyed read is served whatever the lane's terms, and the answer says them. Two lanes,
    chosen at runtime from upstream's registry: one stating terms, and one stating none whose snapshot is
    unpublished (`mane`, `acmg` today), whose `null` terms must arrive beside the reason, never alone."""
    import dataclasses

    from just_dna_enricher.caches import CACHE_LANES

    stated = [lane for lane in CACHE_LANES if lane.terms is not None]
    unstated = [lane for lane in CACHE_LANES if lane.terms is None and lane.unpublished]
    assert stated and unstated, "upstream's registry no longer has both kinds; the test reads nothing"
    for lane in (stated[0], unstated[0]):
        _fake_remote(tmp_path, monkeypatch, size=10, lane=lane.name)
        sdk = RegistryClient(
            "http://testserver", transport=sdk_transport(_client(tmp_path)), check_version=False
        )
        rows = sdk.lane_rows(lane.name, "avi", {"chrom": ["22"], "start": [2]})
        tables = sdk.lane_tables(lane.name)
        assert len(rows["rows"]) == 1
        expected = dataclasses.asdict(lane.terms) if lane.terms is not None else None
        for answer in (rows, tables):
            assert answer["terms"] == expected
            assert answer["unpublished"] == lane.unpublished
    assert rows["terms"] is None and rows["unpublished"]


def test_the_cli_prints_the_terms_and_never_reads_none_as_unrestricted() -> None:
    """The renderer is half the fix: a field only in the JSON is a field `registry-client` users never see."""
    stated = {"terms": {"license": "CC-BY-NC-ND-4.0", "notice": "NonCommercial.", "commercial_use": False,
                        "share_alike": False, "redistribution": True}, "unpublished": "refused: NoDerivatives"}
    lines = _lane_terms_lines(stated)
    assert lines[0] == "terms: CC-BY-NC-ND-4.0 (commercial use: no, share alike: no, redistribution: yes)"
    assert "  NonCommercial." in lines and "snapshot not published: refused: NoDerivatives" in lines
    unstated = _lane_terms_lines({"terms": None, "unpublished": "unestablished: never answered"})
    assert "not a statement that the lane is unrestricted" in unstated[0]
    assert unstated[1] == "snapshot not published: unestablished: never answered"
    assert _lane_terms_lines({"lane": "x", "tables": []}) == []  # an older server: nothing claimed
