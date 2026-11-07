"""`run_log`: a long command's own record of what it printed and logged, and how it ended."""

import logging
from pathlib import Path

import click
import pytest

from just_dna_registry.config import Settings
from just_dna_registry.run_log import run_log, run_log_dir


def test_default_directory_is_beside_the_db(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "db" / "registry.db")
    assert run_log_dir(settings) == (tmp_path / "db" / "logs").resolve()
    assert run_log_dir(Settings(db_path=tmp_path / "r.db", run_log_dir=tmp_path / "x")) == tmp_path / "x"


def test_printed_lines_and_log_records_land_and_a_failure_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(db_path=tmp_path / "r.db", run_log_dir=tmp_path / "runs")
    with pytest.raises(click.exceptions.Exit), run_log(settings, "upgrade", "registry upgrade apply=True") as path:
        click.secho("held ns/mod@1.0.0: drift", fg="yellow")
        logging.getLogger("just_dna_registry.services.upgrade").info("re-derived 3 subjects")
        logging.getLogger("httpx").info("GET https://example.org")  # pinned to WARNING, kept out
        raise click.exceptions.Exit(1)

    body = path.read_text()
    assert "held ns/mod@1.0.0: drift" in body and "\x1b[" not in body
    assert "re-derived 3 subjects" in body and "example.org" not in body
    assert body.rstrip().splitlines()[-1].startswith("# ended by Exit (exit 1)")
    assert "held ns/mod@1.0.0: drift" in capsys.readouterr().out, "the terminal lost its output"
    assert not any(isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is not None
                   and getattr(h.stream, "name", "") == str(path) for h in logging.getLogger().handlers)


def test_a_stream_captured_during_the_run_still_works_after_it(tmp_path: Path) -> None:
    """A handler built inside the run holds the tee; logging flushes it at exit, after the file closed."""
    import sys

    settings = Settings(db_path=tmp_path / "r.db", run_log_dir=tmp_path / "runs")
    with run_log(settings, "upgrade", "registry upgrade") as path:
        captured = logging.StreamHandler(sys.stdout)
    captured.stream.write("after the run\n")
    captured.flush()
    assert "after the run" not in path.read_text()
