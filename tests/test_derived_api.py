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
