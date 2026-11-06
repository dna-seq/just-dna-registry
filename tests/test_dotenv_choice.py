"""The server reads the working directory's `.env` (0.28, S27), and falls back to the one above the
installed package, as 0.27 always did, only when the working directory has none, saying so at boot."""

import logging
from pathlib import Path

from just_dna_registry.config import DotenvChoice, choose_dotenv
from just_dna_registry.startup import report_dotenv


def _tree(tmp_path: Path, *, at_cwd: bool, at_package: bool) -> tuple[Path, Path]:
    """A container's shape: the package deep under `site-packages`, the service run from `srv/`."""
    package = tmp_path / "venv/lib/site-packages/just_dna_registry"
    cwd = tmp_path / "srv"
    package.mkdir(parents=True)
    cwd.mkdir()
    if at_cwd:
        (cwd / ".env").write_text("REGISTRY_MODE=test\n")
    if at_package:
        (tmp_path / "venv/.env").write_text("REGISTRY_MODE=prod\n")
    return cwd, package


def test_the_working_directory_wins_and_the_one_passed_over_is_named(tmp_path: Path, caplog) -> None:
    cwd, package = _tree(tmp_path, at_cwd=True, at_package=True)
    choice = choose_dotenv(cwd, package)
    assert choice == DotenvChoice(cwd / ".env", "cwd", tmp_path / "venv/.env")
    with caplog.at_level(logging.INFO, logger="registry.startup"):
        report_dotenv(choice)
    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith(".env: working directory") for line in lines), lines
    assert any("no longer read" in line and "venv/.env" in line for line in lines), lines


def test_with_none_in_the_working_directory_the_package_walk_is_the_fallback(
    tmp_path: Path, caplog
) -> None:
    """The case a flip of the rule would have broken: a box whose only `.env` the old walk found."""
    cwd, package = _tree(tmp_path, at_cwd=False, at_package=True)
    choice = choose_dotenv(cwd, package)
    assert choice == DotenvChoice(tmp_path / "venv/.env", "package")
    with caplog.at_level(logging.WARNING, logger="registry.startup"):
        report_dotenv(choice)
    assert [r.getMessage()[:15] for r in caplog.records] == [".env: fallback:"]


def test_a_checkout_finds_one_file_by_both_routes(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n")
    package = tmp_path / "src/just_dna_registry"
    package.mkdir(parents=True)
    assert choose_dotenv(tmp_path, package) == DotenvChoice(tmp_path / ".env", "cwd")


def test_none_anywhere_loads_nothing(tmp_path: Path) -> None:
    cwd, package = _tree(tmp_path, at_cwd=False, at_package=False)
    assert choose_dotenv(cwd, package) == DotenvChoice(None, None)
