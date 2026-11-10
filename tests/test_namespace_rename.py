"""Namespace rename (0.29): a namespace's owner renames it, a site admin renames any, and an account
rename carries the namespace spelled like its old handle. Every version moves (files copied to the new
storage path, `identity.namespace` and `canonical_id` amended, which moves no identity because both are
outside the digest, the content signature and the signature), and the old name stays an alias that
reads and publishes follow and that no door lets anyone claim. The old copies are kept."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from just_dna_format.integrity import verify_manifest, verify_signature
from just_dna_format.manifest import ModuleManifest
from sdk_transport import sdk_transport
from test_handle_rename import _auth, _publish, _user, signing_app  # noqa: F401 - fixture re-export
from typer.testing import CliRunner

from just_dna_registry.cli import app as cli
from just_dna_registry.client import RegistryClient, RegistryError
from just_dna_registry.config import Settings, get_settings
from just_dna_registry.db.repository import NamespaceReserved, Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.models.api import ALIAS_HEADER
from just_dna_registry.services.namespaces import NamespaceRenameRefused, rename_namespace
from just_dna_registry.storage.base import version_key

_OLD, _NEW = "sheep-space", "lamb-space"


def _seed_two(seed: Callable, ns: str = "just-dna-seq") -> None:
    for version in ("1.0.0", "1.0.1"):
        seed(ns, "coronary", version, genes=["CYP2C19"], categories=["x"],
             created_at="2026-01-01T00:00:00Z", owner="antonkulaga")


def _stored(app, ns: str, name: str, version: str) -> dict:
    return json.loads(app.state.storage.read_file(version_key(ns, name, version), "manifest.json"))


def test_a_rename_moves_every_version_keeps_the_old_copies_and_moves_no_identity(
    signing_app, tmp_path: Path  # noqa: F811 - the imported fixture
) -> None:
    app, client = signing_app, TestClient(signing_app)
    repo: Repository = app.state.repo
    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    first = _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.1")
    old_files = app.state.storage.list_files(version_key("just-dna-seq", "coronary", "1.0.0"))
    assert old_files, "the premise: a published version has files under its key"

    dry = client.post("/api/v1/namespaces/just-dna-seq/rename", json={"name": "dna-seq"}, headers=_auth(key))
    assert dry.status_code == 200, dry.text
    assert dry.json()["applied"] is False and dry.json()["copied"] == 0
    assert [v["to"] for v in dry.json()["versions"]] == ["dna-seq/coronary@1.0.0", "dna-seq/coronary@1.0.1"]
    assert dry.json()["versions"][0]["files"] == len(old_files)
    assert not app.state.storage.list_files(version_key("dna-seq", "coronary", "1.0.0"))

    done = client.post(
        "/api/v1/namespaces/just-dna-seq/rename", json={"name": "dna-seq", "dry_run": False},
        headers=_auth(key),
    ).json()
    assert (done["namespace"], done["name"], done["applied"], done["copied"]) == ("just-dna-seq", "dna-seq", True, 2)
    assert done["aliases"] == ["just-dna-seq"] and done["modules"] == ["dna-seq/coronary"] and done["snapshot"]

    for version in ("1.0.0", "1.0.1"):
        stored = _stored(app, "dna-seq", "coronary", version)
        projected = json.loads(repo.get_manifest_json("dna-seq", "coronary", version))
        for m in (stored, projected):
            assert m["identity"]["namespace"] == "dna-seq"
            assert m["identity"]["canonical_id"] == f"dna-seq/coronary@{version}"
        # The old copy is kept, byte for byte (3a: nothing is deleted).
        assert _stored(app, "just-dna-seq", "coronary", version)["identity"]["namespace"] == "just-dna-seq"
    assert app.state.storage.list_files(version_key("dna-seq", "coronary", "1.0.0")) == old_files

    # Identity did not move: same digest, same signature, and both still verify against the bytes.
    base = "/api/v1/modules/dna-seq/coronary/versions/1.0.0"
    amended = ModuleManifest.model_validate(client.get(f"{base}/manifest").json())
    assert amended.artifact.digest == first["artifact"]["digest"]
    assert amended.content_signature == first["content_signature"]
    assert amended.signature.model_dump() == first["signature"]
    verify_signature(amended.artifact.digest, amended.signature, trusted_public_key=app.state.test_pubkey)
    module_dir = tmp_path / "install"
    module_dir.mkdir()
    for f in client.get(f"{base}/download").json()["files"]:
        (module_dir / f["name"]).write_bytes(client.get(f"{base}/files/{f['name']}").content)
    verify_manifest(module_dir, amended)


def test_the_old_name_resolves_for_reads_and_publishes(app, client: TestClient, repo: Repository) -> None:
    key = _user(repo, "sheep", namespace=_OLD)
    _publish(client, key, _OLD, "coronary", "1.0.0")
    report = rename_namespace(repo, app.state.storage, app.state.settings, _OLD, _NEW, apply=True)
    assert report.copied == 1

    read = client.get(f"/api/v1/modules/{_OLD}/coronary")
    assert read.status_code == 200 and read.json()["namespace"] == _NEW, read.text
    assert read.headers[ALIAS_HEADER] == _NEW
    manifest = client.get(f"/api/v1/modules/{_OLD}/coronary/versions/1.0.0/manifest")
    assert manifest.json()["identity"]["canonical_id"] == f"{_NEW}/coronary@1.0.0"
    # A current name carries no header; a listing filter names either.
    assert ALIAS_HEADER not in client.get(f"/api/v1/modules/{_NEW}/coronary").headers
    listed = client.get("/api/v1/modules", params={"namespace": _OLD, "group": "all"}).json()["items"]
    assert [(m["namespace"], m["name"]) for m in listed] == [(_NEW, "coronary")]

    # A publish addressed to the old name lands on the new one.
    published = _publish(client, key, _OLD, "coronary", "1.0.1", weight="-0.7")
    assert published["identity"]["canonical_id"] == f"{_NEW}/coronary@1.0.1"
    assert repo.namespace_versions(_OLD) == []
    assert [v["version"] for v in repo.namespace_versions(_NEW)] == ["1.0.0", "1.0.1"]

    available = client.get(f"/api/v1/namespaces/{_OLD}")
    assert available.json()["namespace"] == _NEW and available.json()["available"] is False
    assert available.json()["aliases"] == [_OLD]


def test_the_old_name_is_refused_at_every_door_that_claims_a_namespace(
    app, client: TestClient, repo: Repository, tmp_path: Path, monkeypatch
) -> None:
    _user(repo, "sheep", namespace=_OLD)
    other = _user(repo, "wolf")
    rename_namespace(repo, app.state.storage, app.state.settings, _OLD, _NEW, apply=True)

    claim = client.post("/api/v1/namespaces", json={"namespace": _OLD}, headers=_auth(other))
    assert claim.status_code == 409 and claim.json()["detail"] == "namespace_taken", claim.text
    assert claim.headers[ALIAS_HEADER] == _NEW
    sdk = RegistryClient("http://testserver", token=other, transport=sdk_transport(client), check_version=False)
    with pytest.raises(RegistryError) as refused:
        sdk.claim_namespace(_OLD)
    assert refused.value.detail == "namespace_taken" and refused.value.namespace_current == _NEW
    assert f"resolves to {_NEW}" in str(refused.value)

    org = repo.create_account("acme")
    repo.set_account_type(org, "org")
    repo.add_org_member(org, int(repo.account_by_name("wolf")["id"]), "owner")
    org_claim = client.post("/api/v1/orgs/acme/namespaces", json={"namespace": _OLD}, headers=_auth(other))
    assert org_claim.status_code == 409 and org_claim.headers[ALIAS_HEADER] == _NEW, org_claim.text

    with pytest.raises(NamespaceReserved):
        repo.add_namespace(_OLD, int(repo.account_by_name("wolf")["id"]))
    assert repo.resolve_namespace(_OLD) == _NEW

    monkeypatch.setenv("REGISTRY_DB_PATH", str(app.state.settings.db_path))
    get_settings.cache_clear()
    try:
        issued = CliRunner().invoke(cli, ["issue-key", "erin", "-n", _OLD])
    finally:
        get_settings.cache_clear()
    assert issued.exit_code != 0 and f"renamed to {_NEW}" in issued.output, issued.output


def test_only_an_owner_or_a_site_admin_renames(client: TestClient, repo: Repository) -> None:
    owner = _user(repo, "sheep", namespace=_OLD)
    member = _user(repo, "lamb")
    admin = _user(repo, "ops", admin=True)
    repo.add_member(_OLD, int(repo.account_by_name("lamb")["id"]), "admin")
    body = {"name": _NEW, "dry_run": True}
    assert client.post(f"/api/v1/namespaces/{_OLD}/rename", json=body, headers=_auth(member)).status_code == 403
    assert client.post(f"/api/v1/namespaces/{_OLD}/rename", json=body, headers=_auth(owner)).status_code == 200
    assert client.post(f"/api/v1/namespaces/{_OLD}/rename", json=body, headers=_auth(admin)).status_code == 200


def test_renames_chain_in_one_hop_renaming_back_reclaims_and_the_cap_binds_self_service(
    app, repo: Repository, seed: Callable
) -> None:
    repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", int(repo.account_by_name("antonkulaga")["id"]))
    _seed_two(seed)
    storage, settings = app.state.storage, app.state.settings
    for new in ("seq-a", "seq-b"):
        rename_namespace(repo, storage, settings, repo.resolve_namespace("just-dna-seq"), new, apply=True)
    assert repo.namespace_aliases_of("seq-b") == ["just-dna-seq", "seq-a"]
    assert repo.resolve_namespace("just-dna-seq") == "seq-b" == repo.resolve_namespace("seq-a")

    back = rename_namespace(repo, storage, settings, "seq-b", "just-dna-seq", apply=True)
    assert back.aliases == ["seq-a", "seq-b"] and repo.resolve_namespace("seq-b") == "just-dna-seq"

    capped = Settings(**{**settings.model_dump(), "max_handle_aliases": 2})
    with pytest.raises(NamespaceRenameRefused) as refused:
        rename_namespace(repo, storage, capped, "just-dna-seq", "seq-c", apply=False)
    assert refused.value.code == "alias_limit_reached"
    assert rename_namespace(repo, storage, capped, "just-dna-seq", "seq-c", apply=False, by_admin=True).versions


def test_a_taken_name_and_a_test_name_on_production_are_refused(app, repo: Repository, seed: Callable) -> None:
    for name, ns in (("antonkulaga", "just-dna-seq"), ("wolf", "elsewhere")):
        repo.add_namespace(ns, repo.create_account(name))
    storage, settings = app.state.storage, app.state.settings
    with pytest.raises(NamespaceRenameRefused) as taken:
        rename_namespace(repo, storage, settings, "just-dna-seq", "elsewhere", apply=False)
    assert (taken.value.code, taken.value.conflict) == ("namespace_taken", True)
    with pytest.raises(NamespaceRenameRefused) as invalid:
        rename_namespace(repo, storage, settings, "just-dna-seq", "Not_Valid", apply=False)
    assert invalid.value.code == "invalid_namespace"
    assert not settings.is_test_instance
    with pytest.raises(NamespaceRenameRefused) as test_name:
        rename_namespace(repo, storage, settings, "just-dna-seq", "test-seq", apply=False)
    assert test_name.value.code == "test_data_on_prod"
    allowed = rename_namespace(repo, storage, settings, "just-dna-seq", "test-seq", apply=False, allow_test_data=True)
    assert allowed.warnings


def test_a_storage_failure_moves_nothing_and_running_it_again_converges(
    app, repo: Repository, seed: Callable, monkeypatch
) -> None:
    repo.add_namespace("just-dna-seq", repo.create_account("antonkulaga"))
    _seed_two(seed)
    storage, settings = app.state.storage, app.state.settings
    real = storage.copy_module
    broken = version_key("seq-new", "coronary", "1.0.1")

    def flaky(src: str, dst: str, overrides) -> int:
        if dst == broken:
            raise OSError("the bucket said no")
        return real(src, dst, overrides)

    monkeypatch.setattr(storage, "copy_module", flaky)
    first = rename_namespace(repo, storage, settings, "just-dna-seq", "seq-new", apply=True)
    assert first.copied == 1 and first.failed == ["just-dna-seq/coronary@1.0.1: OSError"]
    assert repo.namespace_owner("seq-new") is None and repo.resolve_namespace("just-dna-seq") == "just-dna-seq"
    assert len(repo.namespace_versions("just-dna-seq")) == 2

    monkeypatch.setattr(storage, "copy_module", real)
    again = rename_namespace(repo, storage, settings, "just-dna-seq", "seq-new", apply=True)
    assert (again.copied, again.failed) == (2, [])
    assert repo.resolve_namespace("just-dna-seq") == "seq-new"
    assert _stored(app, "seq-new", "coronary", "1.0.1")["identity"]["namespace"] == "seq-new"


def test_a_version_published_during_the_copy_stops_the_move(app, repo: Repository, seed: Callable, monkeypatch) -> None:
    repo.add_namespace("just-dna-seq", repo.create_account("antonkulaga"))
    _seed_two(seed)
    storage, settings = app.state.storage, app.state.settings
    real = storage.copy_module
    landed: list[bool] = []

    def racing(src: str, dst: str, overrides) -> int:
        copied = real(src, dst, overrides)
        if not landed:  # a publish under the old name lands between the copy and the transaction
            landed.append(True)
            seed("just-dna-seq", "coronary", "1.0.2", genes=["CYP2C19"], categories=["x"],
                 created_at="2026-01-02T00:00:00Z", owner="antonkulaga")
        return copied

    monkeypatch.setattr(storage, "copy_module", racing)
    with pytest.raises(NamespaceRenameRefused) as changed:
        rename_namespace(repo, storage, settings, "just-dna-seq", "seq-new", apply=True)
    assert changed.value.code == "namespace_changed" and "coronary@1.0.2" in str(changed.value)
    assert repo.namespace_owner("seq-new") is None and len(repo.namespace_versions("just-dna-seq")) == 3
    # The copies the stopped attempt made under the new name are its own; the re-run overwrites them.

    monkeypatch.setattr(storage, "copy_module", real)
    assert rename_namespace(repo, storage, settings, "just-dna-seq", "seq-new", apply=True).copied == 3


def test_an_account_rename_carries_the_namespace_spelled_like_its_handle(
    app, client: TestClient, repo: Repository
) -> None:
    key = _user(repo, "sheep", namespace="sheep")
    repo.add_namespace("test-sheep", int(repo.account_by_name("sheep")["id"]))
    _publish(client, key, "sheep", "coronary", "1.0.0")

    dry = client.post("/api/v1/auth/rename", json={"name": "lamb", "dry_run": True}, headers=_auth(key)).json()
    assert dry["namespaces_renamed"] == ["sheep -> lamb"] and repo.namespace_owner("lamb") is None

    done = client.post("/api/v1/auth/rename", json={"name": "lamb"}, headers=_auth(key)).json()
    assert done["namespaces_renamed"] == ["sheep -> lamb"] and done["namespaces_kept"] == []
    assert repo.resolve_namespace("sheep") == "lamb"
    stored = _stored(app, "lamb", "coronary", "1.0.0")
    assert (stored["owner"], stored["identity"]["namespace"]) == ("lamb", "lamb")
    # A namespace not spelled like the handle stays where it is; it has its own rename.
    assert repo.namespace_owner("test-sheep") is not None


def test_an_account_rename_keeps_a_namespace_another_account_owns(client: TestClient, repo: Repository) -> None:
    key = _user(repo, "sheep")
    _user(repo, "wolf", namespace="sheep")
    done = client.post("/api/v1/auth/rename", json={"name": "lamb"}, headers=_auth(key)).json()
    assert done["namespaces_renamed"] == [] and done["namespaces_kept"] == ["sheep: owned by another account"]
    assert repo.resolve_namespace("sheep") == "sheep"


def test_a_hard_delete_removes_the_copies_kept_under_the_old_name(tmp_path: Path) -> None:
    from just_dna_registry.api.app import create_app

    test_app = create_app(Settings(
        mode="test", db_path=tmp_path / "r.db", storage_backend="local", local_storage_dir=tmp_path / "art",
    ))
    client, repo = TestClient(test_app), test_app.state.repo
    key = _user(repo, "sheep", namespace=_OLD)
    _publish(client, key, _OLD, "coronary", "1.0.0")
    rename_namespace(repo, test_app.state.storage, test_app.state.settings, _OLD, _NEW, apply=True)
    storage = test_app.state.storage
    assert storage.list_files(f"{_OLD}/coronary") and storage.list_files(f"{_NEW}/coronary")

    gone = client.delete(f"/api/v1/modules/{_NEW}/coronary", headers=_auth(key))
    assert gone.status_code == 204, gone.text
    assert storage.list_files(f"{_OLD}/coronary") == [] == storage.list_files(f"{_NEW}/coronary")


def test_remove_namespace_keeps_its_old_names_reserved_and_refuses_an_old_name(
    app, repo: Repository, seed: Callable, monkeypatch
) -> None:
    repo.add_namespace("just-dna-seq", repo.create_account("antonkulaga"))
    _seed_two(seed)
    rename_namespace(repo, app.state.storage, app.state.settings, "just-dna-seq", "seq-new", apply=True)
    monkeypatch.setenv("REGISTRY_DB_PATH", str(app.state.settings.db_path))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(app.state.settings.local_storage_dir))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        refused = runner.invoke(cli, ["remove-namespace", "just-dna-seq", "--yes"])
        assert refused.exit_code == 1 and "renamed to seq-new" in refused.output, refused.output
        done = runner.invoke(cli, ["remove-namespace", "seq-new", "--yes"])
        assert done.exit_code == 0, done.output
    finally:
        get_settings.cache_clear()
    # The freed name is claimable; the old one stays reserved and resolves to nothing, so an old link
    # 404s rather than reaching whoever claims `seq-new` next.
    assert repo.namespace_name_taken("seq-new") is None
    assert repo.resolve_namespace("just-dna-seq") == "just-dna-seq"
    assert repo.namespace_name_taken("just-dna-seq") == "alias"
    assert app.state.storage.list_files("just-dna-seq") == [] == app.state.storage.list_files("seq-new")


def test_a_name_holding_somebody_elses_files_or_modules_is_not_free(
    app, repo: Repository, seed: Callable
) -> None:
    repo.add_namespace("just-dna-seq", repo.create_account("antonkulaga"))
    _seed_two(seed)
    seed("orphaned", "other", "1.0.0", genes=["X"], categories=["x"], created_at="2026-01-01T00:00:00Z")
    with pytest.raises(NamespaceRenameRefused) as refused:
        rename_namespace(repo, app.state.storage, app.state.settings, "just-dna-seq", "orphaned", apply=False)
    assert refused.value.code == "namespace_taken" and "without an owner" in str(refused.value)


def test_export_and_import_carry_the_namespace_aliases(tmp_path: Path) -> None:
    src = Repository(connect(tmp_path / "src.db"))
    init_db(src.conn)
    src.add_namespace("just-dna-seq", src.create_account("antonkulaga"))
    src.rename_namespace_rows("just-dna-seq", "seq-new", {}, retired_at="2026-11-10T00:00:00Z")
    dump = src.export_auth()
    assert dump["namespace_aliases"] == [
        {"name": "just-dna-seq", "target": "seq-new", "retired_at": "2026-11-10T00:00:00Z"}
    ]
    dst = Repository(connect(tmp_path / "dst.db"))
    init_db(dst.conn)
    assert dst.import_auth(dump)["namespace_aliases"] == 1
    assert dst.resolve_namespace("just-dna-seq") == "seq-new"

    clash = Repository(connect(tmp_path / "clash.db"))
    init_db(clash.conn)
    clash.import_auth(dump)
    with pytest.raises(NamespaceReserved):
        clash.import_auth({"accounts": [], "namespaces": [
            {"name": "just-dna-seq", "account_id": 1, "featured": 0, "blacklisted": 0}
        ]})


def test_the_sdk_and_both_clis_rename(app, client: TestClient, repo: Repository, seed: Callable, monkeypatch) -> None:
    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    _seed_two(seed)
    sdk = RegistryClient("http://testserver", token=key, transport=sdk_transport(client), check_version=False)
    assert sdk.rename_namespace("just-dna-seq", "seq-a")["applied"] is False
    assert sdk.rename_namespace("just-dna-seq", "seq-a", dry_run=False)["copied"] == 2

    monkeypatch.setenv("REGISTRY_DB_PATH", str(app.state.settings.db_path))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(app.state.settings.local_storage_dir))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        dry = runner.invoke(cli, ["rename-namespace", "just-dna-seq", "seq-b"])
        assert dry.exit_code == 0 and "dry run" in dry.stdout and "seq-a/coronary@1.0.0 -> seq-b" in dry.stdout, dry.output
        done = runner.invoke(cli, ["rename-namespace", "seq-a", "seq-b", "--apply", "--yes"])
        assert done.exit_code == 0 and "renamed seq-a to seq-b: 2 version(s) moved" in done.stdout, done.output
    finally:
        get_settings.cache_clear()
    assert repo.namespace_aliases_of("seq-b") == ["just-dna-seq", "seq-a"]


def test_a_delete_never_follows_an_old_name(tmp_path: Path) -> None:
    from just_dna_registry.api.app import create_app

    test_app = create_app(Settings(
        mode="test", db_path=tmp_path / "r.db", storage_backend="local", local_storage_dir=tmp_path / "art",
    ))
    client, repo = TestClient(test_app), test_app.state.repo
    key = _user(repo, "sheep", namespace=_OLD)
    _publish(client, key, _OLD, "coronary", "1.0.0")
    rename_namespace(repo, test_app.state.storage, test_app.state.settings, _OLD, _NEW, apply=True)
    assert client.delete(f"/api/v1/modules/{_OLD}/coronary", headers=_auth(key)).status_code in (403, 404)
    assert client.get(f"/api/v1/modules/{_NEW}/coronary").status_code == 200


def test_the_alias_middleware_leaves_route_segments_alone() -> None:
    from just_dna_registry.api.namespace_alias import split_namespace

    assert split_namespace("/api/v1/modules/lookup") is None
    assert split_namespace("/api/v1/modules/groups") is None
    # A namespace may be named so; only the exact route paths are routes.
    assert split_namespace("/api/v1/modules/groups/coronary") == ("/api/v1/modules/", "groups", "/coronary")
    assert split_namespace("/api/v1/modules") is None
    assert split_namespace("/api/v1/modules/ns/name/versions") == ("/api/v1/modules/", "ns", "/name/versions")
    assert split_namespace("/api/v1/namespaces/ns") == ("/api/v1/namespaces/", "ns", "")
    assert split_namespace("/api/v1/auth/whoami") is None
