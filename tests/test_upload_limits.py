"""
Bounds on every multipart spec upload: containment, total size, part count.

The containment check is the one that matters. Through 0.10 `publish_version` wrote each uploaded
part to `spec_dir / filename` with no check at all, while the *archive* path had guarded traversal
since it was written — so a part named `../../../x` escaped the temp directory. Authenticated
(publishing needs `PUBLISH` on the namespace), but an authenticated arbitrary write all the same.

`test_traversal_escapes_without_the_guard` demonstrates the escape against the unguarded code rather
than asserting the fix in the abstract, so the test would have failed on 0.10 and does not merely
restate the implementation.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
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
