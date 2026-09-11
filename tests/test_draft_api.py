"""`POST /api/v1/drafts` — the enricher's drafters run against this deployment's snapshots.

Most of what is worth pinning here is the **guards**, because the drafting itself is upstream's and
already has a suite. What is ours is: which source names exist, which parameters each one reads, what
happens when the lane is not on this box, and whether the response tells a caller the things that are
true but invisible — that the tree will not validate yet, and that a zero count can mean a licence
refusal rather than an empty source.

One test drives a **real** draft against the ClinVar snapshot when this box has one, and skips
otherwise. Hand-building a fake snapshot would test another package's private duckdb layout rather
than our wiring, which is the same call `test_preflight_api` makes.
"""

import io
import json
import tarfile

import pytest
from test_preflight_api import (  # noqa: F401 — the two autouse fixtures register for this module
    _AUTH,
    _app,
    _parts,
    no_network,
    pinned_environment,
)

from just_dna_registry.services.drafting import DRAFT_SOURCES
from just_dna_registry.specfiles import DRAFT_REPORT_FILE

_URL = "/api/v1/drafts"


def _real_snapshot(lane: str):
    """Where this box keeps a lane, resolved before the fixtures blank the environment."""
    from just_dna_enricher.caches import LANES_BY_NAME

    return LANES_BY_NAME[lane].resolve()


_CLINVAR = _real_snapshot("clinvar")


def _members(blob: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return {
            m.name: tar.extractfile(m).read()  # type: ignore[union-attr]
            for m in tar.getmembers() if m.isfile()
        }


def test_an_unknown_source_names_the_ones_that_exist(tmp_path) -> None:
    client = _app(tmp_path)
    resp = client.post(
        _URL, params={"source": "clinvarr", "gene": ["CYP2C19"]}, files=_parts(), headers=_AUTH
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "unknown_draft_source"
    for known in DRAFT_SOURCES:
        assert known in detail["errors"][0]


def test_a_parameter_the_source_does_not_read_is_refused_not_dropped(tmp_path) -> None:
    """A silently ignored filter produces a draft answering a different question from the one asked.

    `min_evidence_level` is ClinPGx's. Sent with `?source=clinvar` it must come back as a refusal
    naming both what was rejected and what that source *does* read — a 422 that does not say what to
    send instead just moves the guessing.
    """
    client = _app(tmp_path)
    resp = client.post(
        _URL,
        params={"source": "clinvar", "gene": ["CYP2C19"], "min_evidence_level": "1A"},
        files=_parts(),
        headers=_AUTH,
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "param_not_for_source"
    assert detail["rejected"] == ["min_evidence_level"]
    assert set(detail["accepted"]) == set(DRAFT_SOURCES["clinvar"].params)


@pytest.mark.parametrize(
    ("source", "genes"),
    [("cpic", []), ("cpic", ["CYP2C19", "CYP2D6"]), ("clinvar", []), ("pubmind", [])],
)
def test_the_gene_arity_is_checked_before_a_drafter_runs(tmp_path, source: str, genes) -> None:
    """CPIC drafts one gene per call and the panel sources need at least one.

    Checked up front so the answer is a sentence rather than an IndexError from inside an adapter.
    """
    client = _app(tmp_path)
    resp = client.post(
        _URL, params={"source": source, "gene": genes}, files=_parts(), headers=_AUTH
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "gene_count"


def test_a_lane_this_box_lacks_is_a_503_that_names_it(tmp_path) -> None:
    """Not `enrichment_unavailable` — that means the tier is missing, and the remedies differ.

    The response has to carry the lane and the route, because the fix is an operator's and "something
    was not provisioned" does not say which thing or how it would arrive.
    """
    client = _app(tmp_path)
    resp = client.post(
        _URL, params={"source": "clinvar", "gene": ["CYP2C19"]}, files=_parts(), headers=_AUTH
    )

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "snapshot_unavailable"
    assert detail["lane"] == "clinvar"
    assert detail["source"] == "clinvar"
    assert detail["route"] in {"pullable", "buildable", "none"}
    # No `Retry-After`: retrying does not help until an operator provisions the snapshot.
    assert "retry-after" not in {k.lower() for k in resp.headers}


def test_drafting_needs_an_account(tmp_path) -> None:
    """Anonymous drafting would make the box a free panel generator whose licence acceptance is ours."""
    client = _app(tmp_path)
    resp = client.post(_URL, params={"source": "civic"}, files=_parts())

    assert resp.status_code == 401


def test_an_unrecognized_declared_use_is_refused_rather_than_read_as_not_commercial(tmp_path) -> None:
    """`declared_use` decides whether a gated source is read at all, so a typo must not fall through."""
    client = _app(tmp_path)
    resp = client.post(
        _URL,
        params={"source": "civic", "declared_use": "non-commercial"},
        files=_parts(),
        headers=_AUTH,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_declared_use"


def test_every_source_declares_lanes_parameters_and_what_it_produces() -> None:
    """The registry is what the route dispatches on, so an incomplete entry is a broken source.

    Asserted over the whole table rather than spot-checked: a source added without its lanes would
    fail at request time with a KeyError instead of a 503 naming what is missing.
    """
    from just_dna_enricher.caches import LANES_BY_NAME

    for name, source in DRAFT_SOURCES.items():
        assert source.name == name
        assert source.lanes, f"{name} declares no lane, so nothing can check it is provisioned"
        assert set(source.lanes) <= set(LANES_BY_NAME), f"{name} names a lane the enricher has not"
        assert source.genes in {"one", "many", "optional"}
        assert source.produces, f"{name} does not say what it writes, so `next_step` cannot either"
        assert callable(source.run)


@pytest.mark.skipif(_CLINVAR is None, reason="this box has no ClinVar snapshot")
def test_a_real_draft_comes_back_as_a_tree_that_deliberately_does_not_validate(tmp_path) -> None:
    """The whole point, driven end to end against a real snapshot.

    The assertions are about what a *caller* needs and could otherwise get wrong: that the placeholder
    is there (so the spec will not validate, by design), that the report says which snapshots
    answered, and that `validates` is stated rather than left to be inferred from a missing field.
    """
    from just_dna_format.vocab import TEMPLATE_PLACEHOLDER

    # F5 rather than a gene that happens to match nothing: the first draft of this test asked for
    # CYP2C19, drafted zero rows, and every assertion below it passed without touching a drafter.
    client = _app(tmp_path, clinvar_cache=_CLINVAR)
    resp = client.post(
        _URL,
        params={"source": "clinvar", "gene": ["F5"], "min_review_stars": 1},
        files=_parts(),
        headers=_AUTH,
    )

    assert resp.status_code == 200, resp.text
    members = _members(resp.content)
    report = json.loads(members[DRAFT_REPORT_FILE])

    assert report["source"] == "clinvar"
    assert report["lanes_read"] == ["clinvar"]
    assert report["validates"] is False
    assert report["placeholder"] == TEMPLATE_PLACEHOLDER
    assert TEMPLATE_PLACEHOLDER in report["next_step"]
    assert "module_spec.yaml" in members, "the uploaded tree comes back, not only what was appended"

    drafted = {table["csv"]: table["added"] for table in report["tables"] if table["added"]}
    assert drafted, "nothing was drafted, so the rest of this test would prove nothing"
    assert set(drafted) <= set(DRAFT_SOURCES["clinvar"].produces)

    # **Not every drafted table needs a curator, and the report must not pretend otherwise.**
    # `studies.csv` gains citation rows that need no judgement; `variants.csv` gains rows whose
    # genotype and conclusion only a curator can decide. `needs_curation` is read off the bytes, so
    # it names the second and not the first — telling an author to fill cells that are already
    # complete is the same class of wrongness as not telling them at all.
    assert report["needs_curation"], "a draft with added rows and nothing to curate is suspicious"
    for csv_name in report["needs_curation"]:
        assert TEMPLATE_PLACEHOLDER.encode() in members[csv_name]
    for csv_name in set(drafted) - set(report["needs_curation"]):
        assert TEMPLATE_PLACEHOLDER.encode() not in members[csv_name], (
            f"{csv_name} holds a placeholder but was not listed as needing curation"
        )
    assert all(name in report["next_step"] for name in report["needs_curation"])


@pytest.mark.skipif(_CLINVAR is None, reason="this box has no ClinVar snapshot")
def test_a_dry_run_returns_the_report_and_writes_no_spec_files(tmp_path) -> None:
    """The documented first move, and it has to be observably different from a real draft."""
    client = _app(tmp_path, clinvar_cache=_CLINVAR)
    resp = client.post(
        _URL,
        params={"source": "clinvar", "gene": ["F5"], "dry_run": True},
        files=_parts(),
        headers=_AUTH,
    )

    assert resp.status_code == 200, resp.text
    members = _members(resp.content)
    assert set(members) == {DRAFT_REPORT_FILE}

    report = json.loads(members[DRAFT_REPORT_FILE])
    assert report["dry_run"] is True
    assert report["tables"], "a dry run that reports no table is not a preview of anything"
    assert all(table["written"] is False for table in report["tables"])
    assert any(table["added"] for table in report["tables"])

    # A dry run writes nothing, so `needs_curation` is empty for a reason that has nothing to do with
    # whether curation is owed. That is the one shape where the empty list would read as "all clear",
    # so `next_step` has to say which history produced it.
    assert report["needs_curation"] == []
    assert "dry_run" in report["next_step"] or "Preview" in report["next_step"]
    assert "will not pass /validate" not in report["next_step"]
