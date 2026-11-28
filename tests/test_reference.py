"""The local reference FASTA's provisioning (0.36): where it lives, what state it is in, and the download.

The network is stubbed with `httpx.MockTransport` serving a real gzipped FASTA and an NCBI-shaped checksum
file computed from it, so the md5 check, the resume and the unpack run on real bytes.
"""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from just_dna_registry import cli
from just_dna_registry.config import Settings
from just_dna_registry.services import reference as ref

FOLDER = "https://ftp.example.org/genomes/all/GCF_X"
URL = f"{FOLDER}/GCF_X_genomic.fna.gz"
NAME = "GCF_X_genomic.fna"

FASTA = (b">NC_012920.1 Homo sapiens mitochondrion, complete genome\n" + b"GATCACAGGTCTATCACCCTATTAACCACTCACG\n" * 40)
PACKED = gzip.compress(FASTA)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "db_path": tmp_path / "registry.db",
        "storage_backend": "local",
        "local_storage_dir": tmp_path / "artifacts",
        "reference_fasta_url": URL,
    }
    values.update(overrides)
    return Settings(**values)


class _Cut(httpx.SyncByteStream):
    """Serves `data` and then fails the read, as a connection dropped mid-transfer does."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __iter__(self) -> Iterator[bytes]:
        yield self.data
        raise httpx.ReadError("connection dropped")


class _Server:
    """A folder holding the download and NCBI's checksum file, with a log of what was asked."""

    def __init__(self, *, md5: str | None = None, cut_first_at: int | None = None) -> None:
        self.md5 = md5 or hashlib.md5(PACKED, usedforsecurity=False).hexdigest()
        self.cut_first_at = cut_first_at
        self.ranges: list[str | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == f"{FOLDER}/md5checksums.txt":
            return httpx.Response(200, text=f"0000  ./README.txt\n{self.md5}  ./{NAME}.gz\n")
        assert str(request.url) == URL
        asked = request.headers.get("range")
        self.ranges.append(asked)
        if self.cut_first_at is not None and len(self.ranges) == 1:
            return httpx.Response(200, stream=_Cut(PACKED[: self.cut_first_at]))
        if asked:
            start = int(asked.removeprefix("bytes=").rstrip("-"))
            return httpx.Response(206, content=PACKED[start:])
        return httpx.Response(200, content=PACKED)


def _client(server: _Server) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(server))


def test_path_follows_the_setting_then_the_cache_base_then_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ref.CACHE_BASE_VAR, raising=False)
    assert ref.reference_path(_settings(tmp_path)) is None
    assert ref.reference_state(_settings(tmp_path)).state == "not_configured"

    monkeypatch.setenv(ref.CACHE_BASE_VAR, str(tmp_path / "cache"))
    assert ref.reference_path(_settings(tmp_path)) == tmp_path / "cache" / "reference" / NAME

    chosen = tmp_path / "elsewhere" / "grch38.fna"
    assert ref.reference_path(_settings(tmp_path, reference_fasta=chosen)) == chosen


def test_a_url_that_is_not_gzipped_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ref.CACHE_BASE_VAR, str(tmp_path / "cache"))
    with pytest.raises(ref.ReferenceError, match="gzipped"):
        ref.reference_path(_settings(tmp_path, reference_fasta_url=f"{FOLDER}/plain.fna"))


def test_provisioning_downloads_checks_and_unpacks(tmp_path: Path) -> None:
    target = tmp_path / "ref" / NAME
    settings = _settings(tmp_path, reference_fasta=target)
    assert ref.reference_state(settings).state == "absent"
    lines: list[str] = []

    state = ref.provision_reference(settings, lines.append, client=_client(_Server()))

    assert target.read_bytes() == FASTA
    assert state.state == "unindexed"
    assert sorted(p.name for p in target.parent.iterdir()) == sorted([NAME, f"{NAME}.lock"])
    assert any("md5 matches" in line for line in lines)


def test_a_dropped_download_resumes_from_where_it_stopped(tmp_path: Path) -> None:
    target = tmp_path / "ref" / NAME
    server = _Server(cut_first_at=len(PACKED) // 3)

    ref.provision_reference(_settings(tmp_path, reference_fasta=target), lambda _: None, client=_client(server))

    assert target.read_bytes() == FASTA
    assert server.ranges == [None, f"bytes={len(PACKED) // 3}-"]


def test_a_download_whose_md5_disagrees_is_removed_and_nothing_reads_as_a_fasta(tmp_path: Path) -> None:
    target = tmp_path / "ref" / NAME
    settings = _settings(tmp_path, reference_fasta=target)

    with pytest.raises(ref.ReferenceError, match="md5"):
        ref.provision_reference(settings, lambda _: None, client=_client(_Server(md5="0" * 32)))

    assert not target.exists()
    assert ref.reference_state(settings).state == "absent"


def test_an_unfinished_provisioning_reads_as_partial_and_resumes(tmp_path: Path) -> None:
    target = tmp_path / "ref" / NAME
    target.parent.mkdir()
    half = len(PACKED) // 2
    (target.parent / f"{NAME}.gz.part").write_bytes(PACKED[:half])
    settings = _settings(tmp_path, reference_fasta=target)
    assert ref.reference_state(settings).state == "partial"
    server = _Server()

    ref.provision_reference(settings, lambda _: None, client=_client(server))

    assert target.read_bytes() == FASTA
    assert server.ranges == [f"bytes={half}-"]


def test_a_present_fasta_is_left_alone_and_asks_nothing(tmp_path: Path) -> None:
    target = tmp_path / "ref" / NAME
    target.parent.mkdir()
    target.write_bytes(FASTA)
    (target.parent / f"{NAME}.fai").write_text("NC_012920.1\t1360\t58\t34\t35\n")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"asked {request.url}")

    state = ref.provision_reference(
        _settings(tmp_path, reference_fasta=target), lambda _: None,
        client=httpx.Client(transport=httpx.MockTransport(refuse)),
    )
    assert state.state == "indexed"


def test_a_second_provisioning_of_the_same_file_is_refused_while_one_runs(tmp_path: Path) -> None:
    target = tmp_path / "ref" / NAME
    with ref._exclusive(target), pytest.raises(ref.ReferenceError, match="another provisioning"):
        ref.provision_reference(_settings(tmp_path, reference_fasta=target), lambda _: None, client=_client(_Server()))


def _warm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> tuple[int, str]:
    """`warm-caches` with every lane left out, so the reference alone decides the outcome."""
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv(ref.CACHE_BASE_VAR, str(tmp_path / "cache"))
    monkeypatch.setenv("REGISTRY_REFERENCE_FASTA_URL", URL)
    cli.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["warm-caches", "--no-ensembl", "--no-clinvar", *args])
    finally:
        cli.get_settings.cache_clear()
    return result.exit_code, result.output


def test_the_dry_run_lists_the_reference_under_its_own_heading_and_asks_for_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out = _warm(tmp_path, monkeypatch)
    assert code == 1
    assert out.index("lanes:") < out.index("reference:")
    assert f"✗ {tmp_path / 'cache' / 'reference' / NAME}: not provisioned" in out
    assert "The reference FASTA to provision" in out

    code, out = _warm(tmp_path, monkeypatch, "--no-reference")
    assert code == 0, out
    assert "(--no-reference)" in out


def test_apply_provisions_the_reference_and_the_next_dry_run_finds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, real = _Server(), httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **_: real(transport=httpx.MockTransport(server)))

    code, out = _warm(tmp_path, monkeypatch, "--apply")

    assert code == 0, out
    target = tmp_path / "cache" / "reference" / NAME
    assert target.read_bytes() == FASTA
    assert f"✓ reference: {target}" in out
    # Unindexed until the index is written (upstream S167), so the next dry run still says what is missing.
    code, out = _warm(tmp_path, monkeypatch)
    assert f"✗ {target}: no {NAME}.fai beside it" in out
