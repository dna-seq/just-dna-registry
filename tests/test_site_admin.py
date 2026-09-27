"""Registry-wide admin (0.28): an account flag that acts as `owner` on every existing namespace and
org, so an operator can repair a namespace whose owner lost their key — yank, amend, grant members —
over HTTP. It reaches no namespace nobody claimed and no hard delete on production."""

import logging
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sdk_transport import sdk_transport
from typer.testing import CliRunner

from just_dna_registry import client_cli
from just_dna_registry.api.app import create_app
from just_dna_registry.cli import app as cli
from just_dna_registry.client import RegistryClient, RegistryError
from just_dna_registry.config import Settings, get_settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.services.accounts import merge_accounts


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _account(repo: Repository, name: str, *, namespace: str | None = None, admin: bool = False) -> str:
    account_id = repo.create_account(name)
    if namespace is not None:
        repo.add_namespace(namespace, account_id)
    repo.set_site_admin(account_id, admin)
    repo.add_api_key(f"mk_live_{name}", account_id)
    return f"mk_live_{name}"


def _seed_old(seed: Callable, repo: Repository) -> None:
    """The lost-key shape: `old-handle` owns `nam1` holding a published module, and nobody can
    present its key any more."""
    repo.add_namespace("nam1", repo.create_account("old-handle"))
    seed("nam1", "modul", "1.0.0", genes=["CYP2C19"], categories=["pgx"], created_at="2026-01-01T00:00:00Z")


def test_site_admin_repairs_a_namespace_it_holds_no_role_in(
    client: TestClient, repo: Repository, seed: Callable
) -> None:
    _seed_old(seed, repo)
    admin = _account(repo, "ops", admin=True)
    stranger = _account(repo, "stranger")
    new_self = _account(repo, "name2", namespace="name2")
    base = "/api/v1/modules/nam1/modul/versions/1.0.0"

    # Without the flag every one of these is refused: the baseline the elevation is measured against.
    assert client.post(f"{base}/yank", json={"yanked": True}, headers=_auth(stranger)).status_code == 403
    assert client.patch(base, json={"changelog": "x"}, headers=_auth(stranger)).status_code == 403
    grant = {"account": "name2", "role": "owner"}
    assert client.post("/api/v1/namespaces/nam1/members", json=grant, headers=_auth(stranger)).status_code == 403

    assert client.post(f"{base}/yank", json={"yanked": True}, headers=_auth(admin)).status_code == 200
    assert client.post(f"{base}/yank", json={"yanked": False}, headers=_auth(admin)).status_code == 200
    assert client.patch(base, json={"changelog": "by ops"}, headers=_auth(admin)).status_code == 200

    # The actual remedy: the person's new account becomes an owner of the old namespace, after which
    # they need no admin at all.
    resp = client.post("/api/v1/namespaces/nam1/members", json=grant, headers=_auth(admin))
    assert resp.status_code == 201
    assert {m["account"]: m["role"] for m in resp.json()["members"]} == {"old-handle": "owner", "name2": "owner"}
    assert client.post(f"{base}/yank", json={"yanked": True}, headers=_auth(new_self)).status_code == 200


def test_site_admin_cannot_reach_an_unclaimed_namespace(client: TestClient, repo: Repository) -> None:
    admin = _account(repo, "ops", admin=True)
    resp = client.get("/api/v1/namespaces/nobody-claimed/members", headers=_auth(admin))
    assert resp.status_code == 403  # would be 200 if the flag answered `owner` for any name


def test_revoking_the_flag_binds_an_existing_jwt(tmp_path: Path) -> None:
    app = create_app(Settings(
        db_path=tmp_path / "r.db", local_storage_dir=tmp_path / "a",
        jwt_secret="test-secret-at-least-32-bytes-long!!",
    ))
    repo: Repository = app.state.repo
    client = TestClient(app)
    repo.add_namespace("nam1", repo.create_account("old-handle"))
    _account(repo, "ops", admin=True)
    jwt = client.post("/api/v1/auth/tokens", json={"api_key": "mk_live_ops"}).json()["token"]

    assert client.get("/api/v1/auth/whoami", headers=_auth(jwt)).json()["site_admin"] is True
    assert client.get("/api/v1/namespaces/nam1/members", headers=_auth(jwt)).status_code == 200

    repo.set_site_admin(int(repo.account_by_name("ops")["id"]), False)
    assert client.get("/api/v1/auth/whoami", headers=_auth(jwt)).json()["site_admin"] is False
    assert client.get("/api/v1/namespaces/nam1/members", headers=_auth(jwt)).status_code == 403


def test_production_mounts_no_delete_for_a_site_admin(
    client: TestClient, repo: Repository, seed: Callable
) -> None:
    _seed_old(seed, repo)
    admin = _account(repo, "ops", admin=True)
    resp = client.delete("/api/v1/modules/nam1/modul/versions/1.0.0", headers=_auth(admin))
    assert resp.status_code in (404, 405)
    assert repo.version_exists("nam1", "modul", "1.0.0")


def test_every_elevated_answer_is_logged(client: TestClient, repo: Repository, caplog) -> None:
    repo.add_namespace("nam1", repo.create_account("old-handle"))
    admin = _account(repo, "ops", admin=True)
    with caplog.at_level(logging.WARNING, logger="registry.auth"):
        client.get("/api/v1/namespaces/nam1/members", headers=_auth(admin))
    assert [r.getMessage() for r in caplog.records if r.name == "registry.auth"] == [
        "site admin ops acting as owner on namespace nam1"
    ]


def test_export_import_carries_the_flag(tmp_path: Path) -> None:
    src = Repository(connect(tmp_path / "src.db"))
    init_db(src.conn)
    _account(src, "ops", admin=True)
    _account(src, "plain")
    dump = src.export_auth()
    assert {a["name"]: a["site_admin"] for a in dump["accounts"]} == {"ops": 1, "plain": 0}

    dst = Repository(connect(tmp_path / "dst.db"))
    init_db(dst.conn)
    dst.import_auth(dump)
    assert dst.is_site_admin(int(dst.account_by_name("ops")["id"]))
    assert not dst.is_site_admin(int(dst.account_by_name("plain")["id"]))

    # An export taken before the column existed imports as not-admin rather than failing.
    for a in dump["accounts"]:
        del a["site_admin"]
    old = Repository(connect(tmp_path / "old.db"))
    init_db(old.conn)
    old.import_auth(dump)
    assert not old.is_site_admin(int(old.account_by_name("ops")["id"]))


# ── Account merge: fold the lost account into the one its owner carried on with ─────────────────


def _lost_and_found(client: TestClient, repo: Repository, seed: Callable) -> None:
    """`old-handle` owns `nam1`, authored its version, starred and reviewed it and sits in an org.
    `name2` is the same person later: it also starred the module and reviewed the same version."""
    old = _account(repo, "old-handle", namespace="nam1")
    seed("nam1", "modul", "1.0.0", genes=["CYP2C19"], categories=["pgx"], created_at="2026-01-01T00:00:00Z")
    old_id = int(repo.account_by_name("old-handle")["id"])
    repo.conn.execute("UPDATE versions SET published_by = ?", (old_id,))
    repo.conn.commit()
    new = _account(repo, "name2", namespace="name2")
    for key in (old, new):
        assert client.put("/api/v1/modules/nam1/modul/star", headers=_auth(key)).status_code == 200
        review = client.put(
            "/api/v1/modules/nam1/modul/versions/1.0.0/reviews", json={"rating": 5}, headers=_auth(key)
        )
        assert review.status_code == 200, review.text
    org_id = repo.create_account("lab")
    repo.set_account_type(org_id, "org")
    repo.add_org_member(org_id, old_id, "admin")
    repo.add_org_member(org_id, int(repo.account_by_name("name2")["id"]), "member")


def _state(repo: Repository) -> dict:
    """Everything a merge may touch, as one comparable value."""
    q = lambda sql: [tuple(r) for r in repo.conn.execute(sql).fetchall()]  # noqa: E731
    return {
        table: q(f"SELECT * FROM {table} ORDER BY 1, 2")
        for table in ("namespaces", "namespace_members", "org_members", "module_stars", "reviews", "api_keys")
    } | {"versions": q("SELECT id, published_by FROM versions"), "stars": q("SELECT id, stars FROM modules")}


def test_merge_dry_run_reports_and_changes_nothing(
    client: TestClient, repo: Repository, seed: Callable
) -> None:
    _lost_and_found(client, repo, seed)
    admin = _account(repo, "ops", admin=True)
    before = _state(repo)
    sdk = RegistryClient("http://testserver", token=admin, transport=sdk_transport(client), check_version=False)

    report = sdk.merge_accounts("old-handle", "name2")

    assert _state(repo) == before
    assert report["applied"] is False and report["snapshot"] is None
    assert report["namespaces"] == ["nam1"]
    assert (report["versions"], report["keys_revoked"]) == (1, 1)
    assert (report["stars_collapsed"], report["stars_moved"]) == (1, 0)
    assert (report["reviews_moved"], report["reviews_kept_on_source"]) == (0, 1)
    assert (report["namespace_memberships"], report["org_memberships"]) == (1, 1)


def test_merge_moves_everything_and_revokes_the_lost_key(
    client: TestClient, repo: Repository, seed: Callable
) -> None:
    _lost_and_found(client, repo, seed)
    admin = _account(repo, "ops", admin=True)
    sdk = RegistryClient("http://testserver", token=admin, transport=sdk_transport(client), check_version=False)
    dry = sdk.merge_accounts("old-handle", "name2")

    done = sdk.merge_accounts("old-handle", "name2", apply=True)

    # The apply does what the dry run said, because they are the same statements.
    assert {k: v for k, v in done.items() if k not in ("applied", "snapshot")} == {
        k: v for k, v in dry.items() if k not in ("applied", "snapshot")
    }
    assert done["applied"] is True
    assert done["snapshot"] and "/" not in done["snapshot"]  # a file name, never a path

    new_id = int(repo.account_by_name("name2")["id"])
    old_id = int(repo.account_by_name("old-handle")["id"])
    assert int(repo.namespace_owner("nam1")["account_id"]) == new_id
    assert repo.namespace_role("nam1", new_id) == "owner"
    assert repo.org_role(int(repo.account_by_name("lab")["id"]), new_id) == "admin"  # the higher role
    assert {r[0] for r in repo.conn.execute("SELECT published_by FROM versions")} == {new_id}
    assert repo.get_module_row("nam1", "modul")["stars"] == 1  # two stars from one person are one
    # Both reviews survive: the colliding one stays under the old handle rather than being dropped.
    assert {r[0] for r in repo.conn.execute("SELECT account_id FROM reviews")} == {old_id, new_id}

    # The lost key is dead; the new one now manages the old namespace without any admin.
    assert client.get("/api/v1/auth/whoami", headers=_auth("mk_live_old-handle")).status_code == 401
    yank = client.post(
        "/api/v1/modules/nam1/modul/versions/1.0.0/yank", json={"yanked": True}, headers=_auth("mk_live_name2")
    )
    assert yank.status_code == 200


def test_the_merge_never_runs_on_the_apps_connection(repo: Repository, settings: Settings) -> None:
    """The app shares one connection across threads, and a dry run rolls back its whole connection:
    on the shared one it would also undo another request's uncommitted write (a publish mid-insert).
    So the service opens its own. Pinned structurally, because the behavioural version cannot be
    staged: an uncommitted write holds sqlite's file lock, and the merge correctly waits it out."""

    class SharedConnection(Repository):
        def merge_accounts(self, *args: object, **kwargs: object) -> dict:
            raise AssertionError("merge ran on the app's shared connection")

    _account(repo, "old-handle", namespace="nam1")
    _account(repo, "name2")
    report = merge_accounts(SharedConnection(repo.conn), settings, "old-handle", "name2", apply=False)
    assert report.namespaces == ["nam1"] and report.applied is False


def test_merge_does_not_carry_the_admin_flag(client: TestClient, repo: Repository) -> None:
    _account(repo, "old-ops", admin=True)
    _account(repo, "name2")
    admin = _account(repo, "ops", admin=True)
    resp = client.post(
        "/api/v1/admin/accounts/old-ops/merge", json={"into": "name2", "apply": True}, headers=_auth(admin)
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/api/v1/auth/whoami", headers=_auth("mk_live_name2")).json()["site_admin"] is False
    assert not repo.is_site_admin(int(repo.account_by_name("old-ops")["id"]))  # nor keep it


def test_merge_refusals(client: TestClient, repo: Repository) -> None:
    _account(repo, "old-handle")
    plain = _account(repo, "name2")
    admin = _account(repo, "ops", admin=True)
    org_id = repo.create_account("lab")
    repo.set_account_type(org_id, "org")
    sdk = RegistryClient("http://testserver", token=admin, transport=sdk_transport(client), check_version=False)

    cases = {
        ("old-handle", "name2", plain): (403, "site_admin_required"),
        ("old-handle", "nobody", admin): (404, "account_not_found"),
        ("name2", "name2", admin): (422, "same_account"),
        ("lab", "name2", admin): (422, "not_a_user_account"),
        ("name2", "lab", admin): (422, "not_a_user_account"),
    }
    for (source, into, key), (code, detail) in cases.items():
        resp = client.post(
            f"/api/v1/admin/accounts/{source}/merge", json={"into": into, "apply": True}, headers=_auth(key)
        )
        assert (resp.status_code, resp.json()["detail"]) == (code, detail), (source, into)
    try:
        sdk.merge_accounts("old-handle", "nobody")
    except RegistryError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("the SDK swallowed a 404")
    # Nothing above applied: the old key still works.
    assert client.get("/api/v1/auth/whoami", headers=_auth("mk_live_old-handle")).status_code == 200


def test_cli_grants_the_flag_and_merges_after_a_dry_run(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "r.db"
    monkeypatch.setenv("REGISTRY_DB_PATH", str(db))
    monkeypatch.setenv("REGISTRY_STORAGE_BACKEND", "local")
    monkeypatch.setenv("REGISTRY_LOCAL_STORAGE_DIR", str(tmp_path / "art"))
    get_settings.cache_clear()
    repo = Repository(connect(db))
    init_db(repo.conn)
    _account(repo, "old-handle", namespace="nam1")
    _account(repo, "name2")
    runner = CliRunner()
    try:
        granted = runner.invoke(cli, ["site-admin", "name2", "--grant"])
        assert granted.exit_code == 0 and "site_admin=yes" in granted.stdout, granted.output
        assert runner.invoke(cli, ["site-admin", "name2", "--revoke"]).stdout.strip() == "name2: site_admin=no"

        dry = runner.invoke(cli, ["merge-accounts", "old-handle", "name2"])
        assert dry.exit_code == 0 and "dry run" in dry.stdout, dry.output
        assert int(repo.namespace_owner("nam1")["account_id"]) == int(repo.account_by_name("old-handle")["id"])

        done = runner.invoke(cli, ["merge-accounts", "old-handle", "name2", "--apply", "--yes"])
        assert done.exit_code == 0 and "snapshot:" in done.stdout, done.output
        assert int(repo.namespace_owner("nam1")["account_id"]) == int(repo.account_by_name("name2")["id"])
        assert repo.account_for_key("mk_live_old-handle") is None

        missing = runner.invoke(cli, ["merge-accounts", "nobody", "name2"])
        assert missing.exit_code == 1 and "account not found: nobody" in missing.stdout
    finally:
        get_settings.cache_clear()


def test_registry_client_merges_over_http_after_a_dry_run(
    client: TestClient, repo: Repository, monkeypatch
) -> None:
    """`registry-client merge-accounts` is the no-shell path: a site admin's token, nothing on the box."""
    _account(repo, "old-handle", namespace="nam1")
    _account(repo, "name2")
    plain = _account(repo, "plain")
    admin = _account(repo, "ops", admin=True)
    token: dict[str, str] = {}
    monkeypatch.setattr(
        client_cli, "_client",
        lambda *a, **k: client_cli._CliClient(
            "http://testserver", token["value"], transport=sdk_transport(client), check_version=False
        ),
    )
    runner = CliRunner()
    old_owner = int(repo.account_by_name("old-handle")["id"])

    token["value"] = plain
    refused = runner.invoke(client_cli.app, ["merge-accounts", "old-handle", "name2", "--token", plain])
    assert refused.exit_code == 1 and "not a site admin" in refused.stdout, refused.output

    token["value"] = admin
    dry = runner.invoke(client_cli.app, ["merge-accounts", "old-handle", "name2", "--token", admin])
    assert dry.exit_code == 0 and "dry run" in dry.stdout and "keys_revoked" in dry.stdout, dry.output
    assert int(repo.namespace_owner("nam1")["account_id"]) == old_owner

    declined = runner.invoke(
        client_cli.app, ["merge-accounts", "old-handle", "name2", "--apply", "--token", admin], input="n\n"
    )
    assert declined.exit_code != 0
    assert int(repo.namespace_owner("nam1")["account_id"]) == old_owner

    done = runner.invoke(
        client_cli.app, ["merge-accounts", "old-handle", "name2", "--apply", "--yes", "--token", admin]
    )
    assert done.exit_code == 0 and "merged old-handle into name2" in done.stdout, done.output
    assert int(repo.namespace_owner("nam1")["account_id"]) == int(repo.account_by_name("name2")["id"])
    assert repo.account_for_key("mk_live_old-handle") is None

    missing = runner.invoke(client_cli.app, ["merge-accounts", "nobody", "name2", "--token", admin])
    assert missing.exit_code == 1 and "does not exist" in missing.stdout
