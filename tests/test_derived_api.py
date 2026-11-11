"""`POST .../derived` — the enriched tables handed back to a client that holds no snapshots.

The point of the route is that the compiler never fetches, so `resolution.csv` has to *travel* with a
spec for that spec to compile anywhere but on a provisioned box. What is worth pinning is therefore
not "did it return 200" but: are the bytes the caller gets the ones the report describes, does the
folder appear only when something is in it, and does a spec too broken to enrich fail like a publish
rather than succeed with an empty archive.

Egress is asserted rather than assumed: `no_network` is imported from the pre-flight suite, so a
claim that this route reached nothing would fail loudly if the enricher ever slipped in a lookup.
"""

import hashlib
import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient
from test_preflight_api import (  # noqa: F401 — the two autouse fixtures register for this module
    _AUTH,
    _BAD_STUDIES,
    _YAML,
    _app,
    _parts,
    no_network,
    pinned_environment,
)

from just_dna_registry.specfiles import DERIVED_DIR, DERIVED_NOTE_FILE, DERIVED_REPORT_FILE

_URL = "/api/v1/modules/just-dna-seq/coronary/derived"


def _post(client: TestClient, **kw):
    return client.post(_URL, files=_parts(**kw), headers=_AUTH)


def _members(blob: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        out = {}
        for member in tar.getmembers():
            handle = tar.extractfile(member)
            if handle is not None:
                out[member.name] = handle.read()
        return out


def test_the_archive_carries_a_report_and_a_note_whatever_else_it_holds(tmp_path) -> None:
    """Two files are unconditional: a caller must never get bytes with nothing describing them."""
    client = _app(tmp_path)
    resp = _post(client)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/gzip"
    assert "coronary-derived.tar.gz" in resp.headers["content-disposition"]

    members = _members(resp.content)
    assert DERIVED_REPORT_FILE in members
    assert DERIVED_NOTE_FILE in members
    report = json.loads(members[DERIVED_REPORT_FILE])
    assert report["namespace"] == "just-dna-seq"
    assert report["name"] == "coronary"
    assert report["validation"]["valid"] is True


def test_every_digest_in_the_report_describes_the_bytes_beside_it(tmp_path) -> None:
    """The claim the report makes about the archive, recomputed rather than trusted.

    These digests are what let a caller check what arrived without compiling anything, so a report
    that described a different tree would be worse than one carrying no digests at all.
    """
    client = _app(tmp_path)
    members = _members(_post(client).content)
    listing = json.loads(members[DERIVED_REPORT_FILE])["files"]

    assert {entry["name"] for entry in listing} == {
        name for name in members if name.startswith(f"{DERIVED_DIR}/")
    }
    for entry in listing:
        data = members[entry["name"]]
        assert entry["sha256"] == f"sha256:{hashlib.sha256(data).hexdigest()}"
        assert entry["size"] == len(data)


def test_the_derived_folder_appears_only_when_something_lands_in_it(tmp_path) -> None:
    """The folder is a consequence of the contents, never a promise made ahead of them.

    Same rule `download(layout="split")` follows. An archive advertising an empty `derived/` would
    tell a caller a pass ran and found nothing, when in fact nothing ran.
    """
    client = _app(tmp_path)
    members = _members(_post(client).content)

    derived = {name for name in members if name.startswith(f"{DERIVED_DIR}/")}
    listing = json.loads(members[DERIVED_REPORT_FILE])["files"]
    assert derived == {entry["name"] for entry in listing}
    assert all(members[name] for name in derived), "an empty member is not a derived table"


def test_a_table_that_was_not_produced_is_named_rather_than_simply_missing(tmp_path) -> None:
    """Absence has two histories and the archive cannot show which, so it enumerates rather than hides.

    A derived table this run did not produce is indistinguishable from one the module has nothing to
    say about: there is simply no member. `files_absent` makes the first fact readable;
    `enrichment.notes` carries the reason wherever a pass recorded one. Some skips leave no note at
    all — a gated source whose credential this deployment lacks writes nothing and says nothing —
    which is exactly why the list says *not produced here* rather than *this module has none*.

    Reported by `just-module-creator`, whose displacement diff went silent on precisely this shape.
    """
    from just_dna_registry.specfiles import DERIVED_FILES

    client = _app(tmp_path)
    members = _members(_post(client).content)
    report = json.loads(members[DERIVED_REPORT_FILE])

    produced = {name.split("/", 1)[-1] for name in members if name.startswith(f"{DERIVED_DIR}/")}
    assert set(report["files_absent"]) == set(DERIVED_FILES) - produced
    assert report["files_absent"], "every derived table was produced, so this proved nothing"
    # The two halves partition the roster: nothing is both produced and absent, nothing is neither.
    assert produced | set(report["files_absent"]) == set(DERIVED_FILES)
    assert not (produced & set(report["files_absent"]))

    note = members[DERIVED_NOTE_FILE].decode()
    assert "files_absent" in note
    assert "not produced here" in note


def test_the_note_tells_a_merger_which_sidecar_spelling_to_drop(tmp_path) -> None:
    """`DERIVED_FILES` emits `licensing.csv` and never `sources.csv`, which is a trap for a merger.

    A consumer resolving the archive's member name against a spec that still carries the deprecated
    spelling finds nothing and reports no change, while the write lands under the other name — the
    bug `just-module-creator` hit and filed upstream as their S96. Our side cannot fix their
    resolution, but it can say plainly which name arrives and which to delete.
    """
    from just_dna_registry.specfiles import DERIVED_FILES

    assert "licensing.csv" in DERIVED_FILES and "sources.csv" not in DERIVED_FILES

    client = _app(tmp_path)
    note = _members(_post(client).content)[DERIVED_NOTE_FILE].decode()

    assert "sources.csv" in note and "licensing.csv" in note
    assert "delete it" in note

    # **A symbol the reader does not have yet is advice that cannot be followed.** The first version
    # of this note named `layout.sidecar_key` flatly; it arrives with format 0.7.0 and is absent from
    # the wheels this branch pins, so every consumer reading the note today would have gone looking
    # for a function that is not there. Whatever the note names must either exist on the format we
    # run, or be marked with the release it arrives in.
    from just_dna_format import layout

    for symbol in ("SIDECAR_SPELLINGS", "DEPRECATED_SPELLINGS", "sidecar_key"):
        if symbol not in note:
            continue
        if not hasattr(layout, symbol):
            assert "0.7.0" in note, f"the note names {symbol}, which this format lacks, and does not say so"

    assert "SIDECAR_SPELLINGS" in note, "the note should name a helper the pinned format actually has"


def test_a_spec_too_broken_to_enrich_fails_like_a_publish(tmp_path) -> None:
    """A 422 with the reasons, not a 200 with an empty archive.

    Deliberately the opposite of `/validate` and `/check`, and not a contradiction of them: their
    contract is to *report* a finding, so a finding is a 200. This route's contract is to *produce*,
    and a spec that cannot be enriched produces nothing.
    """
    client = _app(tmp_path)
    resp = _post(client, studies=_BAD_STUDIES)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_spec"
    assert detail["errors"], "a refusal with no reason is worse than no refusal"


def test_the_route_needs_publish_rights_on_the_namespace(tmp_path) -> None:
    """Same cost to this deployment as `/check`, so the same gate in front of it."""
    client = _app(tmp_path)

    anon = client.post(_URL, files=_parts())
    assert anon.status_code == 401

    other = client.post(
        "/api/v1/modules/someone-else/coronary/derived", files=_parts(), headers=_AUTH
    )
    assert other.status_code == 403


def test_both_wire_forms_reach_the_same_answer(tmp_path) -> None:
    """A route offering only loose parts silently excludes the largest specs — the 0.17 lesson.

    Compared by the *report*, not the archive bytes: `sources.csv` carries a `fetched_at` stamped at
    second resolution, so two runs that straddle a second differ legitimately. That is the digest
    doing its job and is exactly why the publish gate keys on `content_signature` instead.
    """
    import tarfile as _tarfile

    client = _app(tmp_path)
    loose = _post(client)
    assert loose.status_code == 200

    buf = io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for _field, (filename, data, _ctype) in _parts():
            info = _tarfile.TarInfo(filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    packed = client.post(
        _URL,
        files={"archive": ("spec.tar.gz", buf.getvalue(), "application/gzip")},
        headers=_AUTH,
    )

    assert packed.status_code == 200, packed.text
    a = json.loads(_members(loose.content)[DERIVED_REPORT_FILE])
    b = json.loads(_members(packed.content)[DERIVED_REPORT_FILE])
    assert a["validation"]["valid"] == b["validation"]["valid"]
    assert {e["name"] for e in a["files"]} == {e["name"] for e in b["files"]}


def test_sending_both_wire_forms_at_once_is_refused(tmp_path) -> None:
    """Only the author knows which copy is current, so a guess would publish the wrong tree."""
    client = _app(tmp_path)
    resp = client.post(
        _URL,
        files=[*_parts(), ("archive", ("spec.tar.gz", b"\x1f\x8b", "application/gzip"))],
        headers=_AUTH,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "ambiguous_upload"


def test_a_full_gate_is_a_503_rather_than_a_queue(tmp_path) -> None:
    """Interactive, like `/check`: a caller is waiting, so a fast refusal beats a slow timeout."""
    client = _app(tmp_path)
    gate = client.app.state.enrichment_gate
    assert gate.try_acquire(), "the fixture gate should start free"
    try:
        resp = _post(client)
    finally:
        gate.release()

    assert resp.status_code == 503
    assert resp.json()["detail"] == "enrichment_busy"
    assert resp.headers["Retry-After"] == "60"


def test_the_note_names_the_collision_a_caller_is_about_to_hit(tmp_path) -> None:
    """The likeliest support ticket, answered inside the archive rather than in an issue tracker.

    A derived `licensing.csv` beside an authored `sources.csv` is two spellings of one fact table,
    and `layout.resolve_sidecar` raises rather than preferring one — so the next upload is a 422, not
    a publish.
    """
    client = _app(tmp_path)
    note = _members(_post(client).content)[DERIVED_NOTE_FILE].decode()

    assert "licensing.csv" in note and "sources.csv" in note
    assert DERIVED_REPORT_FILE in note
    assert "just-dna-seq" in note and "coronary" in note


@pytest.mark.parametrize("field", ["ran", "offline", "fully_resolved", "unresolved", "notes"])
def test_the_report_says_what_the_enrichment_actually_did(tmp_path, field: str) -> None:
    """A tree with no account of the pass that made it is a tree a caller has to guess about."""
    client = _app(tmp_path)
    enrichment = json.loads(_members(_post(client).content)[DERIVED_REPORT_FILE])["enrichment"]

    assert field in enrichment


# ── 0.30: upstream's other passes, through `pass=` ────────────────────────────────────────────────────

_CACHE = __import__("pathlib").Path("/data/just-dna-cache")
_SNAPSHOT_PASSES = ("opentargets enrich", "assertions", "gene-metrics")


def _post_passes(client: TestClient, passes: tuple[str, ...], **query):
    return client.post(
        _URL, files=_parts(), headers=_AUTH,
        params=[("passes", p) for p in passes] + list(query.items()),
    )


def test_an_unknown_pass_is_refused_naming_what_is_served(tmp_path) -> None:
    client = _app(tmp_path)
    resp = _post_passes(client, ("enrich-everything",))
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "unknown_pass" and set(_SNAPSHOT_PASSES) <= set(detail["served"])


def test_a_pass_with_no_snapshot_says_so_and_never_reads_as_ran(tmp_path) -> None:
    """The empty-list trap one level up: a table missing from the archive is either nothing to say or a
    pass that could not ask, and `passes` names which."""
    client = _app(tmp_path, opentargets_cache=tmp_path / "no-cache")
    resp = _post_passes(client, _SNAPSHOT_PASSES)
    assert resp.status_code == 200, resp.text
    report = json.loads(_members(resp.content)[DERIVED_REPORT_FILE])
    outcomes = {p["command"]: p for p in report["passes"]}
    assert set(outcomes) == set(_SNAPSHOT_PASSES)
    assert outcomes["assertions"]["status"] == "skipped", outcomes["assertions"]
    assert outcomes["opentargets enrich"]["status"] in {"skipped", "failed"}, outcomes["opentargets enrich"]
    assert "gene_metrics.csv" in outcomes["gene-metrics"]["tables"]
    # No path of this box in any detail (the scrubber's backstop).
    assert str(tmp_path) not in json.dumps(report["passes"])


def test_no_pass_runs_unless_asked(tmp_path) -> None:
    report = json.loads(_members(_post(_app(tmp_path)).content)[DERIVED_REPORT_FILE])
    assert report["passes"] == []


@pytest.mark.skipif(
    not all((_CACHE / d).is_dir() for d in ("clinvar", "opentargets", "gnomad_constraint")),
    reason="needs this machine's ClinVar, Open Targets and constraint snapshots",
)
def test_the_snapshot_passes_run_from_this_boxs_snapshots_with_no_egress(tmp_path) -> None:
    """Served from snapshots, the passes spend nothing upstream: `no_network` (autouse) fails any socket."""
    client = _app(
        tmp_path, clinvar_cache=_CACHE / "clinvar", opentargets_cache=_CACHE / "opentargets",
        constraint_cache=_CACHE / "gnomad_constraint",
    )
    resp = _post_passes(client, _SNAPSHOT_PASSES)
    assert resp.status_code == 200, resp.text
    members = _members(resp.content)
    report = json.loads(members[DERIVED_REPORT_FILE])
    outcomes = {p["command"]: p for p in report["passes"]}
    for command in _SNAPSHOT_PASSES:
        assert outcomes[command]["status"] == "ran", outcomes[command]
    # Every table a pass that ran says it produced either arrived or is named absent, never neither.
    produced = {name.split("/", 1)[1] for name in members if name.startswith(f"{DERIVED_DIR}/")}
    for outcome in outcomes.values():
        for table in outcome["tables"]:
            assert table in produced or table in report["files_absent"], table


_ALL_PASSES = (
    "gwas", "opentargets enrich", "assertions", "frequencies", "gene-metrics", "dosage", "gene-validity",
    "ld-pairs", "literature",
)


def test_every_served_pass_answers_offline_with_no_egress_and_says_what_it_did(tmp_path) -> None:
    """Offline (the default, the free tier) every pass either answers from a snapshot or says it could not
    ask; none reads as ran-with-nothing when it never asked. `no_network` fails any socket."""
    client = _app(tmp_path, opentargets_cache=tmp_path / "no-cache")
    resp = _post_passes(client, _ALL_PASSES)
    assert resp.status_code == 200, resp.text
    outcomes = {p["command"]: p for p in json.loads(_members(resp.content)[DERIVED_REPORT_FILE])["passes"]}
    assert set(outcomes) == set(_ALL_PASSES)
    for command in ("gwas", "dosage", "gene-validity", "ld-pairs"):
        assert outcomes[command]["status"] == "skipped" and "offline" in outcomes[command]["detail"], (
            outcomes[command]
        )
    assert all(o["status"] in {"ran", "skipped", "unavailable", "failed"} for o in outcomes.values())


def test_an_online_pass_is_charged_before_it_runs(tmp_path, monkeypatch) -> None:
    """Charged on the same ledger `/hint/*` spends, per upstream, from the spec, before the gate."""
    from just_dna_registry.services import derived as derived_service
    from just_dna_registry.services.publish import PublishError

    client = _app(tmp_path, enrich_offline=False)

    def stop(**_kw):  # after the charge, before any enrichment: nothing egresses
        raise PublishError("stopped_by_test", errors=["the run itself is not under test"])

    monkeypatch.setattr(derived_service, "build_derived_tree", stop)
    resp = _post_passes(client, ("gwas", "gene-validity", "literature"), offline="false")
    assert resp.status_code == 422 and "stopped_by_test" in resp.text, resp.text
    ledger = client.app.state.pace_ledger
    spent = {up: e.spent for (who, up), e in ledger._entries.items()}
    assert spent.get("gwas_catalog") == 1 and spent.get("clingen") == 1 and spent.get("gencc") == 1, spent


def test_gnomad_stays_shut_to_the_proxy_unless_the_operator_opened_it(tmp_path) -> None:
    from just_dna_registry.config import Settings
    from just_dna_registry.services.passes import estimate_charges

    uploads = {"variants.csv": b"rsid,gene\nrs1,A\nrs2,B\n"}
    assert "gnomad" not in estimate_charges(uploads, ["frequencies", "gene-metrics"], Settings())
    opened = estimate_charges(uploads, ["frequencies", "gene-metrics"], Settings(hint_allow_gnomad=True))
    assert opened == {"gnomad": 4}


_EXPR = ("alphagenome expression",)
_INTERVAL = {"gene": "CYP2C19", "chrom": "10", "start": "94762000", "end": "94772000"}


def test_alphagenome_is_shut_unless_the_operator_opened_it(tmp_path) -> None:
    resp = _post_passes(_app(tmp_path), _EXPR, offline="false", **_INTERVAL)
    assert resp.status_code == 200, resp.text
    [outcome] = json.loads(_members(resp.content)[DERIVED_REPORT_FILE])["passes"]
    assert outcome["status"] == "skipped" and "REGISTRY_PROXY_ALPHAGENOME" in outcome["detail"]


def test_an_expression_request_names_one_bounded_interval(tmp_path) -> None:
    client = _app(tmp_path, proxy_alphagenome=True, proxy_alphagenome_max_bp=5_000)
    missing = _post_passes(client, _EXPR, offline="false", gene="CYP2C19")
    assert missing.status_code == 422 and missing.json()["detail"]["error"] == "expression_needs_interval"
    wide = _post_passes(client, _EXPR, offline="false", **_INTERVAL)  # 10 kb against a 5 kb bound
    assert wide.status_code == 422 and wide.json()["detail"]["error"] == "expression_interval_too_large"


def test_an_opened_atlas_runs_the_pass_and_reports_upstreams_result(tmp_path, monkeypatch) -> None:
    """Stub the Atlas, never the report: the adapter reads upstream's own `ExpressionResult`."""
    import just_dna_enricher.expression as expression

    seen: list[tuple] = []

    def atlas(spec_dir, gene, *, chrom, start, end, **_kw):
        seen.append((gene, chrom, start, end))
        return expression.ExpressionResult(gene=gene, interval=(chrom, start, end), candidates=3, written=0)

    from just_dna_registry.services import derived as derived_service

    monkeypatch.setattr(expression, "enrich_expression", atlas)
    # An online deployment, with enrich() itself kept on the snapshot so nothing else egresses here.
    client = _app(tmp_path, proxy_alphagenome=True, enrich_offline=False)
    real_enrich = derived_service.enrich_spec
    monkeypatch.setattr(
        derived_service, "enrich_spec",
        lambda spec_dir, settings: real_enrich(spec_dir, settings.model_copy(update={"enrich_offline": True})),
    )
    monkeypatch.setattr(derived_service, "shared_lookup_clients", lambda *a, **k: None)
    resp = _post_passes(client, _EXPR, offline="false", **_INTERVAL)
    assert resp.status_code == 200, resp.text
    [outcome] = json.loads(_members(resp.content)[DERIVED_REPORT_FILE])["passes"]
    assert outcome["status"] == "ran" and seen == [("CYP2C19", "10", 94762000, 94772000)], outcome
    spent = {up: e.spent for (_who, up), e in client.app.state.pace_ledger._entries.items()}
    assert spent.get("alphagenome") == 1, spent


def test_every_served_pass_has_a_place_in_the_run_order() -> None:
    """A pass the route accepts and `run_passes` never reaches would answer 200 with nothing said."""
    from just_dna_registry.services.passes import PASS_ORDER, SERVED_PASSES

    assert len(SERVED_PASSES) >= 5 and set(SERVED_PASSES) <= set(PASS_ORDER)
