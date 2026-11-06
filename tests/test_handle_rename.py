"""Handle rename (0.28): an account renames its own handle, a site admin renames any. The old handle
stays reserved to the account at every door, and `owner` is amended on every stored manifest naming
any handle of the account, which moves no identity because `owner` is outside the digest, the
content signature and the signature."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from just_dna_format.integrity import verify_manifest, verify_signature
from just_dna_format.manifest import ModuleManifest
from just_dna_format.signing import generate_private_key_pem, public_key_b64_from_pem
from sdk_transport import sdk_transport
from typer.testing import CliRunner

from just_dna_registry.api.app import create_app
from just_dna_registry.cli import app as cli
from just_dna_registry.client import RegistryClient
from just_dna_registry.config import Settings, get_settings
from just_dna_registry.db.repository import HandleReserved, Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.installid import generate_install_id
from just_dna_registry.services.accounts import rename_account
from just_dna_registry.services.publish import publish_version
from just_dna_registry.services.purge import apply_purge, plan_purge
from just_dna_registry.storage.base import version_key

_MODULE_YAML = """\
schema_version: "1.0"
module:
  name: {name}
  title: Coronary
  description: Coronary artery disease risk
  report_title: Coronary
  icon: heart
  color: "#db2828"
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,{weight},risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _spec(name: str, weight: str = "-0.8") -> dict[str, bytes]:
    return {
        "module_spec.yaml": _MODULE_YAML.format(name=name).encode(),
        "variants.csv": _VARIANTS.format(weight=weight).encode(),
        "studies.csv": _STUDIES.encode(),
    }


def _publish(client: TestClient, key: str, ns: str, name: str, version: str, weight: str = "-0.8"):
    resp = client.post(
        f"/api/v1/modules/{ns}/{name}/versions",
        data={"version": version, "changelog": "initial"},
        files=[("files", (n, d, "text/plain")) for n, d in _spec(name, weight).items()],
        headers=_auth(key),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _user(repo: Repository, name: str, *, namespace: str | None = None, admin: bool = False) -> str:
    account_id = repo.create_account(name)
    if namespace is not None:
        repo.add_namespace(namespace, account_id)
    repo.set_site_admin(account_id, admin)
    repo.add_api_key(f"mk_live_{name}", account_id)
    return f"mk_live_{name}"


def _projected_owner(app, ns: str, name: str, version: str) -> str:
    """`owner` as the projection holds it (the `seed` fixture stores no `manifest.json`)."""
    return json.loads(app.state.repo.get_manifest_json(ns, name, version))["owner"]


def _stored_owner(app, ns: str, name: str, version: str) -> tuple[str, str]:
    """`owner` as storage holds it and as the projection holds it."""
    raw = app.state.storage.read_file(version_key(ns, name, version), "manifest.json")
    projected = app.state.repo.get_manifest_json(ns, name, version)
    return json.loads(raw)["owner"], json.loads(projected)["owner"]


@pytest.fixture
def signing_app(tmp_path: Path):
    pem = generate_private_key_pem()
    (tmp_path / "signing_key.pem").write_bytes(pem)
    app = create_app(Settings(
        db_path=tmp_path / "r.db", storage_backend="local", local_storage_dir=tmp_path / "art",
        signing_key=tmp_path / "signing_key.pem",
        jwt_secret="test-secret-at-least-32-bytes-long!!",
    ))
    app.state.test_pubkey = public_key_b64_from_pem(pem)
    return app


def test_a_rename_amends_every_manifest_naming_the_account_and_moves_no_identity(
    signing_app, tmp_path: Path
) -> None:
    app, client = signing_app, TestClient(signing_app)
    repo: Repository = app.state.repo
    key = _user(repo, "antonkulaga", namespace="just-dna-seq")
    other = _user(repo, "someone", namespace="elsewhere")
    first = _publish(client, key, "just-dna-seq", "coronary", "1.0.0")
    _publish(client, key, "just-dna-seq", "coronary", "1.0.1")
    _publish(client, other, "elsewhere", "coronary_two", "1.0.0", weight="-0.7")
    # What `registry upgrade` leaves behind: a successor with no recorded publisher.
    repo.conn.execute(
        "UPDATE versions SET published_by = NULL WHERE version = '1.0.1' AND module_id = "
        "(SELECT id FROM modules WHERE namespace = 'just-dna-seq')"
    )
    repo.conn.commit()

    dry = client.post("/api/v1/auth/rename", json={"name": "anton", "dry_run": True}, headers=_auth(key))
    assert dry.status_code == 200, dry.text
    assert dry.json()["applied"] is False and dry.json()["amended"] == 0
    assert set(dry.json()["versions"]) == {"just-dna-seq/coronary@1.0.0", "just-dna-seq/coronary@1.0.1"}
    assert dry.json()["versions_unattributed"] == ["just-dna-seq/coronary@1.0.1"]
    assert _stored_owner(app, "just-dna-seq", "coronary", "1.0.0") == ("antonkulaga", "antonkulaga")

    done = client.post("/api/v1/auth/rename", json={"name": "anton"}, headers=_auth(key)).json()
    assert (done["account"], done["name"], done["applied"]) == ("antonkulaga", "anton", True)
    assert done["amended"] == 2 and done["failed"] == [] and done["aliases"] == ["antonkulaga"]
    assert done["modules"] == ["just-dna-seq/coronary"] and done["snapshot"]
    for version in ("1.0.0", "1.0.1"):
        assert _stored_owner(app, "just-dna-seq", "coronary", version) == ("anton", "anton")
    assert _stored_owner(app, "elsewhere", "coronary_two", "1.0.0") == ("someone", "someone")
    card = client.get("/api/v1/modules/just-dna-seq/coronary").json()
    assert card["owner"] == "anton"
    assert client.get("/api/v1/auth/whoami", headers=_auth(key)).json()["account"] == "anton"

    # Identity did not move: same digest, same signature, and both still verify against the bytes.
    base = "/api/v1/modules/just-dna-seq/coronary/versions/1.0.0"
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


def test_a_session_minted_before_the_rename_publishes_under_the_new_handle(signing_app) -> None:
    app, client = signing_app, TestClient(signing_app)
    key = _user(app.state.repo, "antonkulaga", namespace="just-dna-seq")
    jwt = client.post("/api/v1/auth/tokens", json={"api_key": key}).json()["token"]
    assert client.post("/api/v1/auth/rename", json={"name": "anton"}, headers=_auth(key)).status_code == 200
    assert client.get("/api/v1/auth/whoami", headers=_auth(jwt)).json()["account"] == "anton"
    assert _publish(client, jwt, "just-dna-seq", "coronary", "1.0.0")["owner"] == "anton"


def test_a_publish_handed_a_retired_handle_stamps_the_current_one(app, repo: Repository) -> None:
    """`registry upgrade` passes the predecessor's stored `owner`, and a route may have read the
    handle before a rename landed; `_finalize` maps either through the aliases."""
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.rename_handle(account_id, "anton", retired_at="2026-11-06T00:00:00Z")
    manifest = publish_version(
        repo=repo, storage=app.state.storage, settings=app.state.settings,
        namespace="just-dna-seq", name="coronary", version="1.0.0", changelog="late",
        owner="antonkulaga", files=_spec("coronary"),
    )
    assert manifest.owner == "anton"


def test_the_retired_handle_is_refused_at_every_door(tmp_path: Path, monkeypatch) -> None:
    app = create_app(Settings(
        db_path=tmp_path / "r.db", local_storage_dir=tmp_path / "a", install_id_difficulty=4,
    ))
    repo: Repository = app.state.repo
    client = TestClient(app)
    key = _user(repo, "antonkulaga")
    assert client.post("/api/v1/auth/rename", json={"name": "anton"}, headers=_auth(key)).status_code == 200

    reg = client.post(
        "/api/v1/auth/register", json={"install_id": generate_install_id(4), "account": "antonkulaga"}
    )
    assert (reg.status_code, reg.json()["detail"]) == (409, "account_taken")
    org = client.post("/api/v1/orgs", json={"name": "antonkulaga"}, headers=_auth(key))
    assert (org.status_code, org.json()["detail"]) == (409, "name_taken")
    with pytest.raises(HandleReserved) as reserved:
        repo.create_account("antonkulaga")
    assert reserved.value.current == "anton"

    # The import door: an export naming another account with that handle would hand it over.
    foreign = {"accounts": [{"id": 999, "name": "antonkulaga", "email": None, "display_name": None,
                             "avatar_url": None, "type": "user", "install_id": None}]}
    with pytest.raises(HandleReserved):
        repo.import_auth(foreign)
    assert repo.get_account(999) is None

    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(tmp_path / "a"))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        issued = runner.invoke(cli, ["issue-key", "antonkulaga"])
        assert issued.exit_code == 1 and "renamed to anton" in issued.stdout, issued.output
        made = runner.invoke(cli, ["create-org", "antonkulaga"])
        assert made.exit_code == 1 and "taken" in made.stdout, made.output
    finally:
        get_settings.cache_clear()
    assert [r["name"] for r in repo.conn.execute("SELECT name FROM accounts")] == ["anton"]


def test_renaming_back_reclaims_an_own_alias_and_another_accounts_alias_is_taken(
    client: TestClient, repo: Repository
) -> None:
    key = _user(repo, "first")
    other = _user(repo, "second")
    assert client.post("/api/v1/auth/rename", json={"name": "renamed"}, headers=_auth(key)).status_code == 200
    taken = client.post("/api/v1/auth/rename", json={"name": "first"}, headers=_auth(other))
    assert (taken.status_code, taken.json()["detail"]["error"]) == (409, "account_taken")
    taken = client.post("/api/v1/auth/rename", json={"name": "renamed"}, headers=_auth(other))
    assert taken.status_code == 409

    back = client.post("/api/v1/auth/rename", json={"name": "first"}, headers=_auth(key))
    assert back.status_code == 200 and back.json()["aliases"] == ["renamed"]
    account_id = int(repo.account_by_name("first")["id"])
    assert repo.aliases_of(account_id) == ["renamed"]


def test_the_alias_cap_binds_self_service_and_not_a_site_admin(
    client: TestClient, repo: Repository, settings: Settings
) -> None:
    key = _user(repo, "h0")
    admin = _user(repo, "ops", admin=True)
    cap = settings.max_handle_aliases
    for i in range(1, cap + 1):
        resp = client.post("/api/v1/auth/rename", json={"name": f"h{i}"}, headers=_auth(key))
        assert resp.status_code == 200, resp.text
    refused = client.post("/api/v1/auth/rename", json={"name": "hx"}, headers=_auth(key))
    assert (refused.status_code, refused.json()["detail"]["error"]) == (409, "alias_limit_reached")
    # Going back to an alias keeps the count where it is, so it stays open.
    assert client.post("/api/v1/auth/rename", json={"name": "h0"}, headers=_auth(key)).status_code == 200

    by_admin = client.post(
        "/api/v1/admin/accounts/h1/rename", json={"name": "hx", "apply": True}, headers=_auth(admin)
    )  # `h1` is a retired handle: the admin route resolves it
    assert by_admin.status_code == 200, by_admin.text
    assert by_admin.json()["account"] == "h0" and len(by_admin.json()["aliases"]) == cap + 1


def test_only_a_site_admin_renames_another_account_or_an_org(client: TestClient, repo: Repository) -> None:
    plain = _user(repo, "plain")
    admin = _user(repo, "ops", admin=True)
    assert client.post("/api/v1/orgs", json={"name": "the-lab"}, headers=_auth(plain)).status_code == 201
    refused = client.post(
        "/api/v1/admin/accounts/the-lab/rename", json={"name": "lab", "apply": True}, headers=_auth(plain)
    )
    assert refused.status_code == 403

    dry = client.post("/api/v1/admin/accounts/the-lab/rename", json={"name": "lab"}, headers=_auth(admin))
    assert dry.status_code == 200 and dry.json()["applied"] is False
    assert repo.account_by_name("the-lab") is not None
    done = client.post(
        "/api/v1/admin/accounts/the-lab/rename", json={"name": "lab", "apply": True}, headers=_auth(admin)
    )
    assert done.status_code == 200 and done.json()["aliases"] == ["the-lab"]
    roster = client.get("/api/v1/orgs/the-lab/members", headers=_auth(plain))
    assert roster.status_code == 200 and roster.json()["org"] == "lab"  # old link works, current name shown
    missing = client.post("/api/v1/admin/accounts/nobody/rename", json={"name": "x"}, headers=_auth(admin))
    assert missing.status_code == 404

    # An org's own key cannot rename it through the self route.
    org_key = "mk_live_lab"
    repo.add_api_key(org_key, int(repo.account_by_name("lab")["id"]))
    own = client.post("/api/v1/auth/rename", json={"name": "lab2"}, headers=_auth(org_key))
    assert (own.status_code, own.json()["detail"]) == (403, "org_rename_is_admin_only")


def test_a_test_handle_is_refused_on_production_unless_asked_for(tmp_path: Path) -> None:
    for mode in ("prod", "test"):
        app = create_app(Settings(
            db_path=tmp_path / f"{mode}.db", local_storage_dir=tmp_path / mode, mode=mode,
        ))
        client = TestClient(app)
        key = _user(app.state.repo, "person")
        resp = client.post("/api/v1/auth/rename", json={"name": "test-person"}, headers=_auth(key))
        if mode == "test":
            assert resp.status_code == 200 and resp.json()["warnings"] == []
            continue
        assert (resp.status_code, resp.json()["detail"]["error"]) == (422, "test_data_on_prod")
        resp = client.post(
            "/api/v1/auth/rename", json={"name": "test-person", "allow_test_data": True}, headers=_auth(key)
        )
        assert resp.status_code == 200 and resp.json()["warnings"], resp.text


def test_a_storage_failure_mid_sweep_is_reported_and_running_it_again_converges(
    app, repo: Repository, seed: Callable, monkeypatch
) -> None:
    repo.create_account("antonkulaga")
    for version in ("1.0.0", "1.0.1"):
        seed("just-dna-seq", "coronary", version, genes=["CYP2C19"], categories=["x"],
             created_at="2026-01-01T00:00:00Z", owner="antonkulaga")
    storage, settings = app.state.storage, app.state.settings
    real = storage.store_module
    broken = version_key("just-dna-seq", "coronary", "1.0.1")

    def flaky(key: str, files) -> None:
        if key == broken:
            raise OSError("the bucket said no")
        real(key, files)

    monkeypatch.setattr(storage, "store_module", flaky)
    first = rename_account(repo, storage, settings, "antonkulaga", "anton", apply=True)
    assert first.amended == 1 and first.failed == ["just-dna-seq/coronary@1.0.1: OSError"]
    assert _projected_owner(app, "just-dna-seq", "coronary", "1.0.1") == "antonkulaga"
    assert not storage.exists(broken, "manifest.json")

    monkeypatch.setattr(storage, "store_module", real)
    again = rename_account(repo, storage, settings, "antonkulaga", "anton", apply=True)  # an alias resolves
    assert (again.account, again.versions, again.amended, again.failed) == (
        "anton", ["just-dna-seq/coronary@1.0.1"], 1, []
    )
    assert _stored_owner(app, "just-dna-seq", "coronary", "1.0.1") == ("anton", "anton")
    assert rename_account(repo, storage, settings, "anton", "anton", apply=True).versions == []


def test_a_version_another_account_published_is_listed_and_left_alone(
    app, repo: Repository, seed: Callable
) -> None:
    repo.create_account("antonkulaga")
    publisher = repo.create_account("someone")
    seed("ns1", "modul", "1.0.0", genes=["G"], categories=["x"], created_at="2026-01-01T00:00:00Z",
         owner="antonkulaga")
    repo.conn.execute("UPDATE versions SET published_by = ?", (publisher,))
    repo.conn.commit()
    report = rename_account(repo, app.state.storage, app.state.settings, "antonkulaga", "anton", apply=True)
    assert report.versions == [] and report.conflicts == ["ns1/modul@1.0.0"]
    assert _projected_owner(app, "ns1", "modul", "1.0.0") == "antonkulaga"
    assert not app.state.storage.exists(version_key("ns1", "modul", "1.0.0"), "manifest.json")


def test_a_dry_run_changes_nothing(app, client: TestClient, repo: Repository, seed: Callable) -> None:
    key = _user(repo, "antonkulaga")
    seed("ns1", "modul", "1.0.0", genes=["G"], categories=["x"], created_at="2026-01-01T00:00:00Z",
         owner="antonkulaga")
    stored = version_key("ns1", "modul", "1.0.0")

    def state() -> tuple:
        return (
            [tuple(r) for r in repo.conn.execute("SELECT id, name FROM accounts ORDER BY id")],
            [tuple(r) for r in repo.conn.execute("SELECT * FROM account_aliases")],
            [tuple(r) for r in repo.conn.execute("SELECT id, manifest_json FROM versions")],
            [tuple(r) for r in repo.conn.execute("SELECT id, owner FROM modules")],
            app.state.storage.exists(stored, "manifest.json"),
        )

    before = state()
    assert before[2] and before[3]  # a haystack to compare, not an empty one
    resp = client.post("/api/v1/auth/rename", json={"name": "anton", "dry_run": True}, headers=_auth(key))
    assert resp.status_code == 200 and resp.json()["versions"] == ["ns1/modul@1.0.0"]
    assert state() == before


def test_the_owner_filter_follows_a_retired_handle(
    client: TestClient, repo: Repository, seed: Callable
) -> None:
    key = _user(repo, "antonkulaga")
    seed("ns1", "modul", "1.0.0", genes=["G"], categories=["x"], created_at="2026-01-01T00:00:00Z",
         owner="antonkulaga")
    assert client.post("/api/v1/auth/rename", json={"name": "anton"}, headers=_auth(key)).status_code == 200
    for asked in ("anton", "antonkulaga"):
        items = client.get("/api/v1/modules", params={"owner": asked}).json()["items"]
        assert [(i["name"], i["owner"]) for i in items] == [("modul", "anton")], asked


def test_export_and_import_carry_the_retired_handles(tmp_path: Path) -> None:
    src = Repository(connect(tmp_path / "src.db"))
    init_db(src.conn)
    account_id = src.create_account("antonkulaga")
    src.rename_handle(account_id, "anton", retired_at="2026-11-06T00:00:00Z")
    dump = src.export_auth()
    assert dump["aliases"] == [
        {"name": "antonkulaga", "account_id": account_id, "retired_at": "2026-11-06T00:00:00Z"}
    ]

    dst = Repository(connect(tmp_path / "dst.db"))
    init_db(dst.conn)
    assert dst.import_auth(dump)["aliases"] == 1
    assert dst.handle_taken("antonkulaga") == account_id
    with pytest.raises(HandleReserved):
        dst.create_account("antonkulaga")


def test_the_sdk_and_both_clis_rename(app, client: TestClient, repo: Repository, tmp_path: Path, monkeypatch) -> None:
    key = _user(repo, "antonkulaga")
    admin = _user(repo, "ops", admin=True)
    sdk = RegistryClient("http://testserver", token=key, transport=sdk_transport(client), check_version=False)
    assert sdk.rename_account("anton", dry_run=True)["applied"] is False
    assert sdk.rename_account("anton")["name"] == "anton"
    ops = RegistryClient("http://testserver", token=admin, transport=sdk_transport(client), check_version=False)
    assert ops.admin_rename_account("antonkulaga", "anton2", apply=True)["account"] == "anton"

    monkeypatch.setenv("REGISTRY_DB_PATH", str(app.state.settings.db_path))
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(app.state.settings.local_storage_dir))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        dry = runner.invoke(cli, ["rename-account", "anton", "anton3"])
        assert dry.exit_code == 0 and "dry run" in dry.stdout, dry.output
        assert repo.account_by_name("anton2") is not None
        done = runner.invoke(cli, ["rename-account", "anton", "anton3", "--apply", "--yes"])
        assert done.exit_code == 0 and "renamed anton2 to anton3" in done.stdout, done.output
        refused = runner.invoke(cli, ["rename-account", "anton3", "ops"])
        assert refused.exit_code == 1 and "account_taken" in refused.stdout, refused.output
    finally:
        get_settings.cache_clear()
    assert repo.aliases_of(int(repo.account_by_name("anton3")["id"])) == ["antonkulaga", "anton", "anton2"]


def test_purge_lists_an_account_renamed_into_test_with_its_old_handle(repo: Repository) -> None:
    """The purge selects on the current handle, so an account renamed into `test-` on production
    (admitted with the flag) is deleted by it, retired handles with it. The listing names the old
    handle, which is the one an operator recognises; an alias alone never selects."""
    kept = repo.create_account("person")
    repo.rename_handle(kept, "test-person", retired_at="2026-11-06T00:00:00Z")
    other = repo.create_account("test-was")
    repo.rename_handle(other, "plain", retired_at="2026-11-06T00:00:00Z")
    plan = plan_purge(repo, prefix="test-", include_prod_namespaces=False)
    assert plan.accounts == [(kept, "test-person")]
    assert [line for line in plan.describe() if line.startswith("account")] == [
        "account     test-person (keys, memberships, org links, retired handles; renamed from person)"
    ]
    apply_purge(repo, None, plan)
    assert repo.handle_taken("person") is None and repo.handle_taken("test-was") == other


def test_a_conflicts_card_keeps_naming_its_publisher(app, repo: Repository, seed: Callable) -> None:
    """The card's `owner` is re-read from each touched module's latest manifest, not rewritten in bulk:
    a module whose latest version another account published keeps naming that account's handle as
    its manifest does."""
    repo.create_account("antonkulaga")
    publisher = repo.create_account("someone")
    seed("ns1", "modul", "1.0.0", genes=["G"], categories=["x"], created_at="2026-01-01T00:00:00Z",
         owner="antonkulaga")
    seed("ns1", "modul", "1.0.1", genes=["G"], categories=["x"], created_at="2026-01-02T00:00:00Z",
         owner="antonkulaga")
    repo.conn.execute(
        "UPDATE versions SET published_by = ? WHERE version = '1.0.1'", (publisher,)
    )
    repo.conn.commit()
    report = rename_account(repo, app.state.storage, app.state.settings, "antonkulaga", "anton", apply=True)
    assert report.versions == ["ns1/modul@1.0.0"] and report.conflicts == ["ns1/modul@1.0.1"]
    assert repo.get_module_row("ns1", "modul")["owner"] == "antonkulaga"  # the latest's, untouched


def test_a_merge_amends_owner_from_the_lost_handle_to_the_kept_one(
    app, client: TestClient, repo: Repository, seed: Callable
) -> None:
    lost = repo.create_account("old-handle")
    repo.add_namespace("nam1", lost)
    seed("nam1", "modul", "1.0.0", genes=["G"], categories=["x"], created_at="2026-01-01T00:00:00Z",
         owner="old-handle")
    repo.conn.execute("UPDATE versions SET published_by = ?", (lost,))
    repo.conn.commit()
    _user(repo, "name2")
    admin = _user(repo, "ops", admin=True)

    dry = client.post("/api/v1/admin/accounts/old-handle/merge", json={"into": "name2"}, headers=_auth(admin))
    assert dry.json()["owner_versions"] == ["nam1/modul@1.0.0"] and dry.json()["owner_amended"] == 0
    assert _projected_owner(app, "nam1", "modul", "1.0.0") == "old-handle"

    done = client.post(
        "/api/v1/admin/accounts/old-handle/merge", json={"into": "name2", "apply": True}, headers=_auth(admin)
    ).json()
    assert (done["owner_amended"], done["owner_failed"]) == (1, [])
    assert _stored_owner(app, "nam1", "modul", "1.0.0") == ("name2", "name2")
    assert client.get("/api/v1/modules/nam1/modul").json()["owner"] == "name2"
