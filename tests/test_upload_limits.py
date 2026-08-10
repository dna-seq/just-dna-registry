"""
Bounds on every multipart spec upload: containment, total size, part count.

The containment check is the one that matters. Through 0.10 `publish_version` wrote each uploaded
part to `spec_dir / filename` with no check at all, while the *archive* path had guarded traversal
since it was written — so a part named `../../../x` escaped the temp directory. Authenticated
(publishing needs `PUBLISH` on the namespace), but an authenticated arbitrary write all the same.

`test_traversal_escapes_without_the_guard` demonstrates the escape against the unguarded code rather
than asserting the fix in the abstract, so the test would have failed on 0.10 and does not merely
restate the implementation.

The 0.11.1 half is the *expansion* bound and the two transfer forms. 0.11 bounded the compressed
size of an archive and nothing about what it became on disk, and it gave `/versions/import` an
archive form that `/validate` and `/check` did not have — so the large ClinVar panels (34-180 MiB
authored, 2-10 MB packed) could be published but never rehearsed. `test_a_large_spec_is_refused_raw_
and_accepted_packed` is that blocker, reproduced and closed.
"""

import io
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.client import RegistryClient, RegistryError, pack_spec
from just_dna_registry.config import Settings
from just_dna_registry.services.publish import PublishError, reject_unsafe_relpath

_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  title: Coronary
  description: d
  report_title: R
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _app(tmp_path: Path, **over) -> TestClient:
    client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "m.db",
                local_storage_dir=tmp_path / "a",
                ensembl_cache=tmp_path / "nc",
                clinvar_cache=tmp_path / "nc",
                constraint_cache=tmp_path / "nc",
                **over,
            )
        )
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    return client


_AUTH = {"Authorization": "Bearer mk_live_testkey"}


def _parts(*extra: tuple[str, bytes]) -> list:
    base = [
        ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
        ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
        ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
    ]
    return base + [("files", (n, d, "application/octet-stream")) for n, d in extra]


# ── The traversal, demonstrated then fixed ────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["../escape.csv", "../../../etc/escape.csv", "/absolute.csv", "..\\windows.csv"],
)
def test_reject_unsafe_relpath_refuses_every_escape_shape(name: str) -> None:
    with pytest.raises(PublishError) as caught:
        reject_unsafe_relpath(name)
    assert caught.value.detail == "unsafe_filename"


def test_traversal_escapes_without_the_guard(tmp_path: Path) -> None:
    """The 0.10 behaviour, reproduced: the unguarded write is `spec_dir / name`, and that escapes.

    Asserting the vulnerability exists in the naive construction is what makes the guard above a fix
    rather than a claim — remove `reject_unsafe_relpath` and the traversal test below starts passing
    a file into this directory again.
    """
    spec_dir = tmp_path / "sandbox" / "spec"
    spec_dir.mkdir(parents=True)
    escaped = spec_dir / "../../../pwned.csv"  # what the old code computed
    assert not escaped.resolve().is_relative_to(tmp_path.resolve())


def test_publish_refuses_a_traversing_part(tmp_path: Path) -> None:
    client = _app(tmp_path)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"},
        files=_parts(("../../../pwned.csv", b"x")),
        headers=_AUTH,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "unsafe_filename"
    # And nothing landed anywhere it should not have.
    assert not (tmp_path / "pwned.csv").exists()
    assert not Path("/tmp/pwned.csv").exists()


# ── Size and count ────────────────────────────────────────────────────────────


def test_oversized_upload_is_413(tmp_path: Path) -> None:
    client = _app(tmp_path, max_upload_bytes=1024)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"},
        files=_parts(("big.csv", b"x" * 4096)),
        headers=_AUTH,
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "upload_too_large"


def test_too_many_parts_is_422(tmp_path: Path) -> None:
    """A thousand tiny parts must not stand in for one large one."""
    client = _app(tmp_path, max_spec_files=4)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"},
        files=_parts(*[(f"extra{i}.csv", b"x") for i in range(8)]),
        headers=_AUTH,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "too_many_files"


def test_oversized_archive_is_413(tmp_path: Path) -> None:
    """The archive route is bounded too — the guards live on every upload path, not just one."""
    client = _app(tmp_path, max_upload_bytes=1024)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions/import",
        data={"version": "1.0.0"},
        files={"archive": ("m.zip", b"x" * 4096, "application/zip")},
        headers=_AUTH,
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "upload_too_large"


# ── Expansion, and the two transfer forms (0.11.1) ────────────────────────────


def _spec_tar(*extra: tuple[str, bytes], prefix: str = "") -> bytes:
    """A real spec archive: the three core files, plus whatever the caller adds."""
    members = [
        ("module_spec.yaml", _YAML.encode()),
        ("variants.csv", _VARIANTS.encode()),
        ("studies.csv", _STUDIES.encode()),
        *extra,
    ]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_a_highly_compressible_archive_expands_far_past_its_transfer_size() -> None:
    """The premise of the bound, measured rather than asserted.

    A transfer bound says nothing about disk: this archive is a rounding error on the wire and
    tens of megabytes extracted. Through 0.11 that ratio was entirely unchecked.
    """
    blob = _spec_tar(("big.csv", b"x" * (32 * 1024 * 1024)))
    assert len(blob) < 64 * 1024  # compressed: trivially under any sane transfer bound
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        assert sum(m.size for m in tar.getmembers()) > 32 * 1024 * 1024  # extracted: not


def test_import_refuses_an_over_expanding_archive(tmp_path: Path) -> None:
    client = _app(tmp_path, max_extracted_bytes=1024)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions/import",
        data={"version": "1.0.0"},
        files={"archive": ("m.tar.gz", _spec_tar(("big.csv", b"x" * 65536)), "application/gzip")},
        headers=_AUTH,
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "archive_too_large"


def test_nothing_is_written_when_expansion_is_refused(tmp_path: Path) -> None:
    """Refused before a byte lands — the check reads member headers, it does not extract-then-count."""
    client = _app(tmp_path, max_extracted_bytes=1024)
    client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions/import",
        data={"version": "1.0.0"},
        files={"archive": ("m.tar.gz", _spec_tar(("big.csv", b"x" * 65536)), "application/gzip")},
        headers=_AUTH,
    )
    assert client.get("/api/v1/modules/just-dna-seq/coronary").status_code == 404
    assert not list((tmp_path / "a").rglob("big.csv"))


def _stats(endpoint: str, body: dict) -> dict:
    """`/validate` returns the report; `/check` nests it under `validation`."""
    return (body if endpoint == "validate" else body["validation"])["stats"]


@pytest.mark.parametrize("endpoint", ["validate", "check"])
def test_preflight_accepts_an_archive(tmp_path: Path, endpoint: str) -> None:
    """The fix: both dry runs take the same compressed form `/versions/import` takes."""
    client = _app(tmp_path, enrich_enabled=False)
    resp = client.post(
        f"/api/v1/modules/just-dna-seq/coronary/{endpoint}",
        params={"offline": True},  # zero egress: the archive form is the subject, not the network
        files={"archive": ("spec.tar.gz", _spec_tar(), "application/gzip")},
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert _stats(endpoint, resp.json())["variant_count"] == 1


@pytest.mark.parametrize("endpoint", ["validate", "check"])
def test_preflight_accepts_an_archive_with_a_directory_prefix(tmp_path: Path, endpoint: str) -> None:
    """`tar czf spec.tar.gz spec/` is what a human types; the module root is found inside."""
    client = _app(tmp_path, enrich_enabled=False)
    resp = client.post(
        f"/api/v1/modules/just-dna-seq/coronary/{endpoint}",
        params={"offline": True},
        files={"archive": ("spec.tar.gz", _spec_tar(prefix="spec/"), "application/gzip")},
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert _stats(endpoint, resp.json())["variant_count"] == 1


def test_preflight_refuses_both_forms_at_once(tmp_path: Path) -> None:
    client = _app(tmp_path)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/validate",
        files=_parts() + [("archive", ("spec.tar.gz", _spec_tar(), "application/gzip"))],
        headers=_AUTH,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "ambiguous_upload"


def test_a_large_spec_is_refused_raw_and_accepted_packed(tmp_path: Path) -> None:
    """The reported blocker, end to end.

    A spec whose authored bytes exceed the transfer bound is a `413` sent raw — correct, and what
    the panels hit — and goes through compressed, on the *validation* route that previously had no
    compressed form at all. Same spec, same server, same bound: only the wire form differs.
    """
    filler = ("notes.csv", b"n" * 8192)
    client = _app(tmp_path, max_upload_bytes=4096, enrich_enabled=False)

    raw = client.post(
        "/api/v1/modules/just-dna-seq/coronary/validate",
        files=_parts(filler),
        headers=_AUTH,
    )
    assert raw.status_code == 413
    assert raw.json()["detail"]["error"] == "upload_too_large"

    packed_bytes = _spec_tar(filler)
    assert len(packed_bytes) < 4096  # the same spec, under the same bound, compressed
    packed = client.post(
        "/api/v1/modules/just-dna-seq/coronary/validate",
        files={"archive": ("spec.tar.gz", packed_bytes, "application/gzip")},
        headers=_AUTH,
    )
    assert packed.status_code == 200, packed.text
    assert packed.json()["stats"]["variant_count"] == 1


def _spec_on_disk(tmp_path: Path, *extra: tuple[str, bytes]) -> Path:
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "module_spec.yaml").write_text(_YAML)
    (spec / "variants.csv").write_text(_VARIANTS)
    (spec / "studies.csv").write_text(_STUDIES)
    for name, data in extra:
        (spec / name).write_bytes(data)
    return spec


def test_sdk_pack_is_the_way_through_the_transfer_bound(tmp_path: Path) -> None:
    """The client half of the fix, against the real server.

    A route method the caller cannot reach is not parity, so this asserts the whole path: the same
    `RegistryClient.validate` over the same directory is a `413` raw and a `200` packed.
    """
    client = _app(tmp_path, max_upload_bytes=4096, enrich_enabled=False)
    spec = _spec_on_disk(tmp_path, ("notes.csv", b"n" * 8192))
    sdk = RegistryClient(
        "http://testserver", token="mk_live_testkey",
        transport=client._transport, check_version=False,
    )
    try:
        with pytest.raises(RegistryError) as refused:
            sdk.validate("just-dna-seq", "coronary", spec)
        assert refused.value.status_code == 413

        report = sdk.validate("just-dna-seq", "coronary", spec, pack=True)
        assert report.stats.variant_count == 1
    finally:
        sdk.close()


def test_sdk_sends_an_archive_path_as_an_archive(tmp_path: Path) -> None:
    """Handing the client a `.tar.gz` sends it as one — no re-packing, no directory walk."""
    client = _app(tmp_path, max_upload_bytes=4096, enrich_enabled=False)
    packed = tmp_path / "spec.tar.gz"
    packed.write_bytes(_spec_tar(("notes.csv", b"n" * 8192)))
    sdk = RegistryClient(
        "http://testserver", token="mk_live_testkey",
        transport=client._transport, check_version=False,
    )
    try:
        assert sdk.validate("just-dna-seq", "coronary", packed).stats.variant_count == 1
    finally:
        sdk.close()


def test_pack_spec_excludes_compiled_outputs(tmp_path: Path) -> None:
    """`pack_spec` reuses `gather_spec_files`, so a parquet sitting beside the spec is not shipped —
    the server recompiles, and uploading its own output back would be nonsense the size of the data."""
    spec = _spec_on_disk(tmp_path)
    (spec / "weights.parquet").write_bytes(b"PAR1")
    (spec / "manifest.json").write_text("{}")
    with tarfile.open(fileobj=io.BytesIO(pack_spec(spec))) as tar:
        assert set(tar.getnames()) == {"module_spec.yaml", "variants.csv", "studies.csv"}


def test_the_bounds_do_not_reject_a_normal_publish(tmp_path: Path) -> None:
    """The guards must be invisible at real sizes, or they are a regression dressed as a fix."""
    client = _app(tmp_path, compile_strict=False)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.status_code == 201, resp.text
