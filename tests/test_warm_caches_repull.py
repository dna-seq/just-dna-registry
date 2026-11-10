"""`warm-caches` hands upstream a present Ensembl cache whose pull record names the old repo, or none.

Format 0.8 moved the Ensembl lane to `ensembl_variations_split` under the same file names (RM372), so a
0.7 cache resolves as present, and through 0.28.0 this command only ever handed upstream the lanes that
were absent: the 0.28 upgrade guide had to send operators to `just-dna-enricher cache pull` instead.
Since 0.28.6 (enricher 0.8.3, RM420) every other selected present pulled lane is handed over too, for
upstream to compare its release with the one the hub publishes.

The real `prepare_lane` runs here; only the lane's download (`ensure`) is replaced, by one that writes
what a finished pull leaves on disk, answers the hub comparison as upstream's would, or is never reached.
Each takes `_follow_hub`, which `prepare_lane` passes from 0.8.3.
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
    def ensure(**_: object) -> Path:
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


def _answers_the_hub(cache: Path, calls: list[str], outcome: str, published: str):
    """An `ensure` that does what upstream's does with `_follow_hub`: says what it compared, and re-pulls
    when the outcome is `refreshed`."""

    def ensure(_follow_hub=None, **_: object) -> Path:
        assert _follow_hub is not None, "a present lane was handed over without the hub comparison"
        calls.append(outcome)
        _follow_hub.repo, _follow_hub.local, _follow_hub.published = NEW, "115", published
        _follow_hub.outcome = outcome
        return cache

    return ensure


def test_a_cache_of_the_current_repo_is_compared_with_the_hub_only_under_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whole, current pull is present to the dry run, which reads no hub, and is compared under --apply."""
    cache = _cache(tmp_path / "cache", {"repo": NEW, "files": ["data/chr1.parquet"]})
    calls: list[str] = []
    ensure = _answers_the_hub(cache, calls, "current", "115")

    code, out = _run(tmp_path, monkeypatch, ensure)
    assert code == 0 and "Every selected lane is present." in out and "--apply compares" in out, out
    assert "checked against the hub's on --apply" in out, out
    assert calls == [], "the dry run read the hub"

    code, out = _run(tmp_path, monkeypatch, ensure, "--apply")
    assert calls == ["current"], out
    assert code == 0 and "✓ ensembl: present" in out, out


def test_a_cache_the_hub_has_a_newer_release_of_is_re_pulled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upstream's own line names both releases; nothing here reads them."""
    cache = _cache(tmp_path / "cache", {"repo": NEW, "files": ["data/chr1.parquet"]})
    calls: list[str] = []

    code, out = _run(tmp_path, monkeypatch, _answers_the_hub(cache, calls, "refreshed", "116"), "--apply")
    assert calls == ["refreshed"], out
    line = next(row for row in out.splitlines() if row.startswith("✓ ensembl"))
    assert code == 0 and "re-pulled" in line and "115" in line and "116" in line, out


def test_an_unselected_present_lane_is_not_compared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The comparison costs a hub read and may cost a download, so it follows the operator's selection."""
    _cache(tmp_path / "cache", {"repo": NEW, "files": ["data/chr1.parquet"]})

    def never(**_: object) -> Path:
        raise AssertionError("an unselected lane was handed over")

    code, out = _run(tmp_path, monkeypatch, never, "--no-ensembl", "--apply")
    assert code == 0 and "Every selected lane is present." in out, out


def test_a_repull_that_did_not_take_is_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The record is read back: a pull that returns without rewriting it is reported, not trusted."""
    cache = _cache(tmp_path / "cache", {"repo": OLD, "files": ["data/chr1.parquet"]})

    code, out = _run(tmp_path, monkeypatch, lambda **_: cache, "--apply")
    assert code == 1 and "not re-pulled" in out and OLD in out, out
