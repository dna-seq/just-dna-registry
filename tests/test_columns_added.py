"""C3 (0.28): under a patch-grain format skew, the client lists the columns its tables could carry
that the instance's format does not know yet, from upstream's schema (`field_first_seen`, `model_for`)
and the two version strings. Never from a finding: S18's `curator` and a typo read the same there."""

from pathlib import Path
from types import SimpleNamespace

from just_dna_compiler.draft import model_for
from just_dna_format.base import field_first_seen
from just_dna_format.identity import parse_version

from just_dna_registry import client_cli
from just_dna_registry.columns import columns_added_between


def test_the_s18_case_names_curator_and_its_release() -> None:
    added = columns_added_between("0.6.1", "0.6.6", ["studies.csv", "variants.csv"])
    assert added, "a floor: an emptied upstream roster must not read as nothing added"
    assert added["studies.csv"]["curator"] == field_first_seen(model_for("studies.csv"))["curator"]
    for fields in added.values():
        for release in fields.values():
            assert parse_version("0.6.1") < parse_version(release) <= parse_version("0.6.6")


def test_nothing_is_listed_unless_the_client_is_the_newer_side() -> None:
    assert columns_added_between("0.6.6", "0.6.1", ["studies.csv"]) == {}
    assert columns_added_between("0.6.6", "0.6.6", ["studies.csv"]) == {}
    assert columns_added_between(None, "0.6.6", ["studies.csv"]) == {}
    assert columns_added_between("0.6.1", "0.6.6", ["not_a_table.csv"]) == {}


def test_the_cli_prints_them_under_the_advisory(tmp_path: Path, capsys) -> None:
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "studies.csv").write_text("rsid,pmid\n")
    (spec / "module_spec.yaml").write_text("module: {}\n")
    report = SimpleNamespace(
        valid=False, errors=[], warnings=[], info=[], carried_warnings=[],
        format_version="0.6.1", format_advisory="just-dna-format skew: ...",
    )
    client_cli._echo_columns_added(report, spec)
    out = capsys.readouterr().out
    assert "studies.csv:" in out and "curator (0.6.5)" in out, out
