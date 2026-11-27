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
from just_dna_registry.client_cli import _lane_release_line, _lane_terms_lines
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


_SHA = "e26f5739219002c97a92319b623b497574c342a5"


def _fake_remote(
    tmp_path: Path, monkeypatch, *, size: int, lane: str = "alphagenome_avi", release: str | None = None
) -> list[str]:
    """The remote branch with the hub swapped for local files: the lane is not held, its repo lists them at
    one commit, with `release` as the repo's `release.json` text when given. Returns the repos listed, one
    entry per listing, so a test can count how often a request resolved the head."""
    import polars as pl

    data = tmp_path / "hub"
    data.mkdir(exist_ok=True)
    for chrom in ("21", "22"):
        pl.DataFrame({"chrom": [f"chr{chrom}"] * 3, "pos": [1, 2, 3], "ref": ["A", "C", "G"]}).write_parquet(
            data / f"avi-chr{chrom}.parquet"
        )
    release_file = None
    if release is not None:
        release_file = data / "release.json"
        release_file.write_text(release)
    listed: list[str] = []

    def listing(repo: str) -> lanes.RemoteListing:
        listed.append(repo)
        return lanes.RemoteListing(
            revision=_SHA, files=[(str(p), size) for p in sorted(data.glob("*.parquet"))],
            release_file=str(release_file) if release_file is not None else None,
        )

    monkeypatch.setattr(lanes, "lane_presence", lambda settings: {lane: None})
    monkeypatch.setattr(lanes, "_repo", lambda name: f"just-dna-seq/{name}")
    monkeypatch.setattr(lanes, "_remote_files", listing)
    return listed


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


def test_a_remote_answer_says_the_release_and_the_one_commit_it_read(tmp_path, monkeypatch) -> None:
    """S34 (0.33): a remote read resolves the head once per request and reads every file at that commit, so
    `revision` is honest; `release` is the repo's `release.json` at that commit, read as `/caches` reads one."""
    listed = _fake_remote(tmp_path, monkeypatch, size=10, release='{"dataset": "avi_2026-11-01"}')
    sdk = RegistryClient("http://testserver", transport=sdk_transport(_client(tmp_path)), check_version=False)
    rows = sdk.lane_rows("alphagenome_avi", "avi", {"chrom": ["22"], "start": [2]})
    assert len(listed) == 1  # one listing, one commit, for the whole answer
    tables = sdk.lane_tables("alphagenome_avi")
    assert len(listed) == 2
    for answer in (rows, tables):
        assert answer["served_from"] == "remote:just-dna-seq/alphagenome_avi"
        assert (answer["release"], answer["release_unreadable"], answer["revision"]) == ("avi_2026-11-01", False, _SHA)


@pytest.mark.parametrize(
    ("text", "release", "unreadable"),
    [(None, None, False), ("{not json", None, True), ('{"dataset": ""}', None, False)],
    ids=["no-release-json", "unparseable", "blank-label"],
)
def test_an_unstated_release_is_null_and_an_unreadable_one_says_so(
    tmp_path, monkeypatch, text: str | None, release: str | None, unreadable: bool
) -> None:
    """Absent, blank and unparseable are three histories; only the last is a provenance failure, and none is a
    label something could match."""
    _fake_remote(tmp_path, monkeypatch, size=10, release=text)
    found = lanes.lookup("alphagenome_avi", "avi", {"chrom": ["22"], "start": [2]}, Settings())
    assert (found.release, found.release_unreadable, found.revision) == (release, unreadable, _SHA)
    assert found.rows  # the rows are served whatever the provenance says


def test_a_remote_listing_pins_every_path_to_the_resolved_commit(monkeypatch) -> None:
    """The real `_remote_files` with the hub's two calls stubbed: the head is resolved once and every path it
    hands on, data and `release.json` alike, names `@<sha>`, which is what makes `revision` true of all of them."""
    import huggingface_hub

    class Info:
        sha = _SHA

    calls: list[str] = []

    class Api:
        def dataset_info(self, repo: str) -> Info:
            calls.append(repo)
            return Info()

    class Fs:
        def find(self, path: str, detail: bool) -> dict:
            assert path == f"datasets/just-dna-seq/clinvar@{_SHA}"
            return {f"{path}/{name}": {"size": 5} for name in
                    ("release.json", "data/clinvar-chr1.parquet", ".gitattributes", "manifest.json")}

    monkeypatch.setattr(huggingface_hub, "HfApi", Api)
    monkeypatch.setattr(huggingface_hub, "HfFileSystem", Fs)
    listing = lanes._remote_files("just-dna-seq/clinvar")
    assert calls == ["just-dna-seq/clinvar"] and listing.revision == _SHA
    assert [p for p, _ in listing.files] == [f"hf://datasets/just-dna-seq/clinvar@{_SHA}/data/clinvar-chr1.parquet"]
    assert listing.release_file == f"hf://datasets/just-dna-seq/clinvar@{_SHA}/release.json"


@pytest.mark.skipif(not (_CACHE / "gnomad_constraint").is_dir(), reason="needs this machine's constraint snapshot")
def test_a_local_answer_names_the_release_caches_names_and_no_commit(tmp_path) -> None:
    """Read exactly as `/caches` reads it: the same label from the same box, through the one reader. A local
    copy keeps no commit, so `revision` is null rather than a guess."""
    client = _client(tmp_path, constraint_cache=_CACHE / "gnomad_constraint")
    sdk = RegistryClient("http://testserver", transport=sdk_transport(client), check_version=False)
    caches = {lane["name"]: lane for lane in client.get("/api/v1/caches").json()["lanes"]}
    assert caches["constraint"]["release"]  # the floor: a label to compare, not None == None
    rows = sdk.lane_rows("constraint", "gnomad_constraint", {"gene": ["LPA"]})
    tables = sdk.lane_tables("constraint")
    for answer in (rows, tables):
        assert answer["served_from"] == "local" and answer["revision"] is None
        assert answer["release"] == caches["constraint"]["release"]
        assert answer["release_unreadable"] is False


def test_the_cli_prints_the_release_and_the_commit() -> None:
    assert _lane_release_line({"release": "clinvar_2026-11-01", "revision": _SHA}) == (
        "release: clinvar_2026-11-01 at commit e26f57392190"
    )
    assert _lane_release_line({"release": "gnomad_v4.1.2", "revision": None}) == "release: gnomad_v4.1.2"
    assert _lane_release_line({"release": None, "release_unreadable": True, "revision": None}) == (
        "release: unknown (unreadable release.json)"
    )
    assert _lane_release_line({"release": None, "release_unreadable": False}) == "release: not stated"
    assert _lane_release_line({"lane": "x", "tables": []}) is None  # an older server: nothing claimed


def test_a_release_json_that_cannot_be_fetched_costs_the_label_not_the_rows(tmp_path, monkeypatch) -> None:
    """The listing names a `release.json` the fetch then fails on (a hub hiccup between two calls): the answer
    still serves its rows, with the release unknown and said to be so, never a 500 over provenance."""
    _fake_remote(tmp_path, monkeypatch, size=10, release='{"dataset": "avi_2026-11-01"}')
    (tmp_path / "hub" / "release.json").unlink()  # listed, then gone: the copy raises FileNotFoundError
    found = lanes.lookup("alphagenome_avi", "avi", {"chrom": ["22"], "start": [2]}, Settings())
    assert found.rows and (found.release, found.release_unreadable, found.revision) == (None, True, _SHA)


def _local_table(tmp_path: Path, name: str, frame) -> lanes.LaneTable:
    path = tmp_path / f"{name}.parquet"
    frame.write_parquet(path)
    return lanes.LaneTable(name, [str(path)], [path.stat().st_size], "parquet")


def test_a_key_is_compared_the_way_upstreams_reader_compares_it(tmp_path) -> None:
    """S36 (0.35): a gene folds and matches a member of a `;`-joined cell where upstream's reader does, an rsID
    is read as one, and the reply says which compare ran per key column, read off `KEY_COMPARES` itself.

    Through 0.34 every cell compared exactly, so `cyp2c9` missed `CYP2C9`, `CYP2C9` missed `CYP2C9;CYP4F2`, and
    the short answer said nothing."""
    import polars as pl
    from just_dna_enricher.key_compare import KEY_COMPARES, lane_compare

    assert len(KEY_COMPARES) >= 5, KEY_COMPARES  # floor: an emptied import must not read as "all exact"
    gene, rsid = lane_compare("clinpgx", "annotations", "gene"), lane_compare("clinpgx", "annotations", "rsid")
    assert gene.fold and gene.separator == ";" and rsid.rsid, "the declarations this test exercises moved"
    table = _local_table(tmp_path, "annotations", pl.DataFrame({
        "gene": ["CYP2C9;CYP4F2", " CYP2C19 ", "VKORC1", None],
        "rsid": ["rs1057910", "rs4244285", "rs9923231", "rs1"],
    }))
    settings = Settings(db_path=tmp_path / "r.db")

    rows, compares = lanes._parquet_rows("clinpgx", table, {"gene": ["cyp2c9", "Cyp2c19"]}, settings, remote=False)
    assert {r["rsid"] for r in rows} == {"rs1057910", "rs4244285"}
    assert compares == {"gene": gene.described}

    rows, compares = lanes._parquet_rows("clinpgx", table, {"rsid": ["RS9923231"]}, settings, remote=False)
    assert [r["gene"] for r in rows] == ["VKORC1"] and compares == {"rsid": rsid.described}

    # A lane and column upstream declares nothing for still compares the whole cell exactly, and says so.
    rows, compares = lanes._parquet_rows("alphagenome_avi", table, {"gene": ["cyp2c9"]}, settings, remote=False)
    assert rows == [] and compares == {"gene": "exactly"}
