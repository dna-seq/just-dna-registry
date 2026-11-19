"""Key rotation (0.34.1): a key holder trades the key for a new one, and the old one dies at once.

The person, 2026-11-18: "Don't bug me with rotating keys. Implement rotation. I thought we had it already."
Through 0.34.0 a leaked key took an operator on the box (`issue-key`, then `revoke-key`), and a holder who
could not reach the box could not rotate at all."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sdk_transport import sdk_transport
from typer.testing import CliRunner

from just_dna_registry import client_cli
from just_dna_registry.api.app import create_app
from just_dna_registry.client import RegistryClient, RegistryError
from just_dna_registry.config import Settings
from just_dna_registry.jwtauth import issue_jwt


@pytest.fixture
def app(tmp_path: Path):
    return create_app(Settings(
        db_path=tmp_path / "registry.db", storage_backend="local", local_storage_dir=tmp_path / "artifacts",
        jwt_secret="rotation-test-secret-at-least-32-bytes-long",
    ))


def _keys(app, name: str, count: int) -> list[str]:
    repo = app.state.repo
    account_id = repo.create_account(name)
    keys = [f"mk_live_{name}_{n}" for n in range(count)]
    for key in keys:
        repo.add_api_key(key, account_id)
    return keys


def _whoami(client: TestClient, key: str) -> int:
    return client.get("/api/v1/auth/whoami", headers={"Authorization": f"Bearer {key}"}).status_code


def test_rotation_kills_the_calling_key_and_leaves_the_others(app) -> None:
    client = TestClient(app)
    old, other = _keys(app, "alice", 2)
    _keys(app, "bob", 1)

    answer = client.post("/api/v1/auth/rotate", json={}, headers={"Authorization": f"Bearer {old}"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["account"], body["revoked"]) == ("alice", 1)
    new = body["token"]
    assert new.startswith("mk_live_") and new not in (old, other)

    assert _whoami(client, old) == 401
    assert _whoami(client, other) == 200
    assert _whoami(client, new) == 200
    assert app.state.repo.api_keys_for_account(int(app.state.repo.account_by_name("alice")["id"])) == [other, new]
    assert _whoami(client, "mk_live_bob_0") == 200


def test_revoke_others_leaves_the_new_key_as_the_only_one(app) -> None:
    client = TestClient(app)
    old, *rest = _keys(app, "alice", 3)
    body = client.post(
        "/api/v1/auth/rotate", json={"revoke_others": True}, headers={"Authorization": f"Bearer {old}"}
    ).json()
    assert body["revoked"] == 3
    assert all(_whoami(client, key) == 401 for key in (old, *rest))
    alice = int(app.state.repo.account_by_name("alice")["id"])
    assert app.state.repo.api_keys_for_account(alice) == [body["token"]]


def test_a_session_token_or_no_token_cannot_rotate(app) -> None:
    client = TestClient(app)
    (key,) = _keys(app, "alice", 1)
    alice = app.state.repo.account_by_name("alice")
    session, _ = issue_jwt(app.state.settings, account_id=int(alice["id"]), name="alice")

    refused = client.post("/api/v1/auth/rotate", json={}, headers={"Authorization": f"Bearer {session}"})
    assert (refused.status_code, refused.json()["detail"]) == (422, "rotate_needs_api_key")
    assert client.post("/api/v1/auth/rotate", json={}).status_code == 401
    assert _whoami(client, key) == 200  # nothing moved


def test_the_sdk_switches_to_the_new_key_itself(app) -> None:
    client = TestClient(app)
    (old,) = _keys(app, "alice", 1)
    sdk = RegistryClient("http://testserver", token=old, transport=sdk_transport(client), check_version=False)
    rotated = sdk.rotate_key()
    assert sdk.whoami()["account"] == "alice"  # the next call already uses the new key
    with pytest.raises(RegistryError) as dead:
        RegistryClient("http://testserver", token=old, transport=sdk_transport(client), check_version=False).whoami()
    assert dead.value.status_code == 401
    assert rotated["token"] != old


def test_the_cli_rewrites_the_env_file_and_never_prints_a_key(app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    (old,) = _keys(app, "alice", 1)
    env = tmp_path / ".env"
    env.write_text(f"REGISTRY_URL=http://testserver\nREGISTRY_TOKEN_PROD={old}\nOTHER=kept\n")
    monkeypatch.setattr(client_cli, "_client", lambda url, token, **kw: client_cli._CliClient(
        "http://testserver", token, transport=sdk_transport(client), check_version=False))

    result = CliRunner().invoke(
        client_cli.app, ["rotate-key", "--env-file", str(env), "--env-var", "REGISTRY_TOKEN_PROD"]
    )
    assert result.exit_code == 0, result.output
    lines = dict(line.split("=", 1) for line in env.read_text().splitlines())
    new = lines["REGISTRY_TOKEN_PROD"]
    assert new.startswith("mk_live_") and new != old
    assert lines["OTHER"] == "kept" and lines["REGISTRY_URL"] == "http://testserver"
    assert "mk_live_" not in result.output  # neither key reached the terminal
    assert "rotated for account alice; 1 key(s) revoked" in result.output
    assert _whoami(client, old) == 401 and _whoami(client, new) == 200


def test_the_cli_refuses_a_missing_variable_before_asking_the_server(app, tmp_path: Path) -> None:
    (old,) = _keys(app, "alice", 1)
    env = tmp_path / ".env"
    env.write_text("REGISTRY_TOKEN_SANDBOX=x\n")
    result = CliRunner().invoke(
        client_cli.app, ["rotate-key", "--env-file", str(env), "--env-var", "REGISTRY_TOKEN_PROD"]
    )
    assert result.exit_code == 2
    assert _whoami(TestClient(app), old) == 200
