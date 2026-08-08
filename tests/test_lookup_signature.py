"""
Content-signature lookup: the pre-check that predicts `409 duplicate_content`.

Two identities sit on `/modules/lookup` and they answer different questions. `digest` names the
compiled bytes — it moves when the same spec is recompiled against a different reference, and it
embeds the module name, so it moves on a rename too. `signature` names the authored rows, and is
what publish actually gates duplicates on.

The test that matters is `test_the_precheck_agrees_with_the_publish_gate`: a pre-check that
disagreed with the gate would be worse than none, because it would give a publisher confidence
before taking it away.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from just_dna_compiler.compiler import content_signature

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.services.publish import normalize_module_block

_AUTH = {"Authorization": "Bearer mk_live_testkey"}

_YAML = """\
schema_version: "1.0"
module:
  name: {name}
  title: {title}
  description: d
  report_title: R
  icon: {icon}
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _app(tmp_path: Path) -> TestClient:
    empty = tmp_path / "no-cache"
    client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "m.db",
                local_storage_dir=tmp_path / "a",
                ensembl_cache=empty,
                clinvar_cache=empty,
                constraint_cache=empty,
            )
        )
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    return client


def _parts(name: str = "coronary", title: str = "Coronary", icon: str = "heart") -> list:
    yaml = _YAML.format(name=name, title=title, icon=icon)
    return [
        ("files", ("module_spec.yaml", yaml.encode(), "text/yaml")),
        ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
        ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
    ]


def _publish(client: TestClient, name: str, **kw) -> int:
    return client.post(
        f"/api/v1/modules/just-dna-seq/{name}/versions",
        data={"version": "1.0.0"},
        files=_parts(name=name, **kw),
        headers=_AUTH,
    ).status_code


def _local_signature(tmp_path: Path, **kw) -> str:
    """Compute the signature the way a client would — locally, from the spec, without uploading."""
    spec = tmp_path / f"spec-{kw.get('name', 'coronary')}-{kw.get('icon', 'heart')}"
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "module_spec.yaml").write_text(
        _YAML.format(name=kw.get("name", "coronary"), title=kw.get("title", "Coronary"),
                     icon=kw.get("icon", "heart"))
    )
    (spec / "variants.csv").write_text(_VARIANTS)
    (spec / "studies.csv").write_text(_STUDIES)
    normalize_module_block(spec)
    return content_signature(spec)


def test_lookup_finds_a_published_version_by_signature(tmp_path: Path) -> None:
    client = _app(tmp_path)
    assert _publish(client, "coronary") == 201

    signature = _local_signature(tmp_path)
    body = client.get("/api/v1/modules/lookup", params={"signature": signature}).json()
    assert [(m["name"], m["version"]) for m in body["matches"]] == [("coronary", "1.0.0")]


def test_the_precheck_agrees_with_the_publish_gate(tmp_path: Path) -> None:
    """The pre-check must predict the rejection, not merely resemble it."""
    client = _app(tmp_path)
    assert _publish(client, "coronary") == 201

    # Same data, different name: the lookup says it is taken...
    signature = _local_signature(tmp_path, name="rebranded")
    matches = client.get("/api/v1/modules/lookup", params={"signature": signature}).json()["matches"]
    assert matches, "the pre-check should have seen the collision"

    # ...and publishing it is indeed refused, for the same reason.
    assert _publish(client, "rebranded") == 409


def test_the_signature_ignores_name_and_branding(tmp_path: Path) -> None:
    """Name- and metadata-independence is the property that makes this catch a rebrand at all — the
    artifact digest cannot, because the module name is baked into the compiled parquet."""
    plain = _local_signature(tmp_path, name="coronary", title="Coronary", icon="heart")
    rebranded = _local_signature(tmp_path, name="cardiac", title="Cardiac Risk", icon="database")
    assert plain == rebranded


def test_a_different_data_row_moves_the_signature(tmp_path: Path) -> None:
    """The other half of the property: it must not be so insensitive that distinct data collides."""
    spec = tmp_path / "other"
    spec.mkdir()
    (spec / "module_spec.yaml").write_text(_YAML.format(name="coronary", title="C", icon="heart"))
    (spec / "variants.csv").write_text(_VARIANTS.replace("-0.8", "-0.4"))
    (spec / "studies.csv").write_text(_STUDIES)
    assert content_signature(spec) != _local_signature(tmp_path)


def test_lookup_requires_exactly_one_key(tmp_path: Path) -> None:
    client = _app(tmp_path)
    assert client.get("/api/v1/modules/lookup").status_code == 422
    both = client.get(
        "/api/v1/modules/lookup", params={"digest": "sha256:x", "signature": "sha256:y"}
    )
    assert both.status_code == 422
    assert both.json()["detail"] == "lookup_needs_one_key"


def test_batch_lookup_mixes_digests_and_signatures(tmp_path: Path) -> None:
    """A client classifying a local corpus holds both compiled modules and unpublished specs."""
    client = _app(tmp_path)
    assert _publish(client, "coronary") == 201
    digest = client.get("/api/v1/modules/just-dna-seq/coronary/versions").json()["items"][0][
        "artifact_digest"
    ]
    signature = _local_signature(tmp_path)

    results = client.post(
        "/api/v1/modules/lookup",
        json={"digests": [digest, "sha256:absent"], "signatures": [signature]},
    ).json()["results"]

    by_key = {(r["digest"], r["signature"]): r["matches"] for r in results}
    assert by_key[(digest, None)]
    assert by_key[("sha256:absent", None)] == []
    assert by_key[(None, signature)]


def test_an_empty_signature_never_matches(tmp_path: Path) -> None:
    """Rows predating 0.5 carry `''` until re-derivation. Without this guard every one of them would
    collide with every other and the gate would 409 the whole catalog mid-migration."""
    client = _app(tmp_path)
    assert _publish(client, "coronary") == 201
    client.app.state.repo.conn.execute("UPDATE versions SET content_hash = ''")
    client.app.state.repo.conn.commit()

    body = client.get("/api/v1/modules/lookup", params={"signature": ""}).json()
    assert body["matches"] == []
