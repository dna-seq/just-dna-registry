"""`warm-caches` hands upstream a present Ensembl cache whose pull record names the old repo, or none.

Format 0.8 moved the Ensembl lane to `ensembl_variations_split` under the same file names (RM372), so a
0.7 cache resolves as present, and through 0.28.0 this command only ever handed upstream the lanes that
were absent: the 0.28 upgrade guide had to send operators to `just-dna-enricher cache pull` instead.
The real `prepare_lane` runs here; only the lane's download (`ensure`) is replaced, by one that writes
what a finished pull leaves on disk, or by one that is never reached.
"""

import dataclasses
import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from just_dna_registry import cli
from just_dna_registry.services import enrich

OLD = "datasets/just-dna-seq/ensembl_variations/data"
NEW = "datasets/just-dna-seq/ensembl_variations_split/data"


def _cache(base: Path, record: dict | None) -> Path:
    cache = base / "ensembl_variations"
    (cache / "data").mkdir(parents=True)
    pl.DataFrame({"rsid": ["rs1"], "chrom": ["1"], "start": [1]}).write_parquet(cache / "data" / "chr1.parquet")
    if record is not None:
        (cache / "pull-record.json").write_text(json.dumps(record))
    return cache


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ensure, *args: str) -> tuple[int, str]:
    real = enrich.cache_lanes()
    lanes = {**real, "ensembl": dataclasses.replace(real["ensembl"], ensure=ensure)}
    monkeypatch.setattr(enrich, "cache_lanes", lambda: lanes)
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("JUST_DNA_PIPELINES_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("JUST_DNA_ENSEMBL_CACHE", raising=False)
    cli.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["warm-caches", "--no-clinvar", *args])
    finally:
        cli.get_settings.cache_clear()
    return result.exit_code, result.output


def _pulls_the_new_repo(cache: Path, calls: list[str]):
    def ensure() -> Path:
        calls.append("pulled")
        (cache / "pull-record.json").write_text(json.dumps({"repo": NEW, "files": ["data/chr1.parquet"]}))
        return cache

    return ensure


def test_the_premise_a_cache_of_the_old_repo_reads_as_present(tmp_path: Path, monkeypatch) -> None:
    cache = _cache(tmp_path / "cache", {"repo": OLD, "files": ["data/chr1.parquet"]})
    monkeypatch.setenv("JUST_DNA_PIPELINES_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("JUST_DNA_ENSEMBL_CACHE", raising=False)
    assert enrich.lane_presence(enrich.Settings())["ensembl"] == cache


@pytest.mark.parametrize(
    ("record", "reason"),
    [({"repo": OLD, "files": ["data/chr1.parquet"]}, OLD), (None, "no pull record")],
)
def test_the_dry_run_marks_it_and_apply_repulls_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record: dict | None, reason: str
) -> None:
    cache = _cache(tmp_path / "cache", record)
    calls: list[str] = []
    ensure = _pulls_the_new_repo(cache, calls)

    code, out = _run(tmp_path, monkeypatch, ensure)
    line = next(row for row in out.splitlines() if row.lstrip().startswith(("⟳ ensembl [", "✓ ensembl [", "✗ ensembl [")))
    assert code == 1 and "⟳" in line and reason in line, out
    assert calls == [], "the dry run downloaded"

    code, out = _run(tmp_path, monkeypatch, ensure, "--apply")
    assert calls == ["pulled"], out
    assert code == 0 and "✓ ensembl" in out, out

    code, out = _run(tmp_path, monkeypatch, ensure)
    assert code == 0 and "Every selected lane is present." in out, out


def test_a_cache_of_the_new_repo_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cache(tmp_path / "cache", {"repo": NEW, "files": ["data/chr1.parquet"]})

    def never() -> Path:
        raise AssertionError("a current cache was re-pulled")

    code, out = _run(tmp_path, monkeypatch, never, "--apply")
    assert code == 0 and "Every selected lane is present." in out, out


def test_a_repull_that_did_not_take_is_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The record is read back: a pull that returns without rewriting it is reported, not trusted."""
    cache = _cache(tmp_path / "cache", {"repo": OLD, "files": ["data/chr1.parquet"]})

    code, out = _run(tmp_path, monkeypatch, lambda: cache, "--apply")
    assert code == 1 and "not re-pulled" in out and OLD in out, out
