"""Format 0.8 records the toolchain that wrote a version's bytes (RM342). Where a version's digest
moved while its content did not, the version list says whether a toolchain change explains it,
through upstream's three-valued `toolchains_differ`."""

from conftest import _make_manifest
from fastapi.testclient import TestClient
from just_dna_format.integrity import sha256_bytes

from just_dna_registry.services.ingest import ingest_manifest

_SAME = "sha256:" + "a" * 64


def _version(app, version: str, *, toolchain: dict | None, signature: str = _SAME, digest_seed: str) -> None:
    manifest, _ = _make_manifest("ns1", "modul", version, genes=["G"], categories=["x"])
    manifest.content_signature = signature
    manifest.compilation.toolchain = toolchain
    manifest.artifact.digest = sha256_bytes(digest_seed.encode())
    ingest_manifest(app.state.repo, manifest, created_at=f"2026-01-0{version[-1]}T00:00:00Z")


def test_the_version_list_says_when_a_toolchain_moved_the_digest(app, client: TestClient) -> None:
    py, old, new = {"python": "3.14.8"}, {"polars": "1.44.2"}, {"polars": "2.1.0"}
    _version(app, "1.0.0", toolchain=None, digest_seed="a")                   # compiled before 0.8
    _version(app, "1.0.1", toolchain={**py, **old}, digest_seed="b")          # unknown before: cannot say
    _version(app, "1.0.2", toolchain={**py, **new}, digest_seed="c")          # polars moved: explained
    _version(app, "1.0.3", toolchain={**py, **new}, digest_seed="d")          # same toolchain: not it
    _version(app, "1.0.4", toolchain={**py, **old}, digest_seed="e", signature="sha256:" + "b" * 64)
    versions = client.get("/api/v1/modules/ns1/modul").json()["versions"]
    moved = {v["version"]: v["digest_moved_by_toolchain"] for v in versions}
    assert moved == {"1.0.0": None, "1.0.1": None, "1.0.2": True, "1.0.3": False, "1.0.4": None}
    assert {v["version"]: v["toolchain"] for v in versions}["1.0.2"] == {**py, **new}

    # The paged list reads each version against its predecessor even across a page boundary.
    page = client.get("/api/v1/modules/ns1/modul/versions", params={"page": 2, "per_page": 2}).json()
    assert {v["version"]: v["digest_moved_by_toolchain"] for v in page["items"]} == {"1.0.2": True, "1.0.3": False}
