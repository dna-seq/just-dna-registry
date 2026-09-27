"""Registry-wide admin (0.28): an account flag that acts as `owner` on every existing namespace and
org, so an operator can repair a namespace whose owner lost their key — yank, amend, grant members —
over HTTP. It reaches no namespace nobody claimed and no hard delete on production."""

import logging
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db


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
