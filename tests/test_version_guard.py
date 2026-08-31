"""Server/client version-mismatch guard (0.7.1). The server advertises its API + contract versions
(endpoint + response headers); the client fetches them and fails fast — with an actionable message —
when the `just-dna-format` contract or the API version can't safely interoperate, instead of letting
a cryptic digest / shape collision surface on publish or download."""

import httpx
import pytest
from fastapi.testclient import TestClient

from just_dna_registry.client import RegistryClient, VersionMismatchError
from just_dna_registry.version import (
    VersionInfo,
    compatibility_error,
    contract_compatible,
    schema_gap_advisory,
)

# ── Pure compatibility logic ─────────────────────────────────────────────────────


def test_contract_compatible_rules() -> None:
    assert contract_compatible("0.3.0", "0.3.2")       # same 0.x minor → additive-only, ok
    assert not contract_compatible("0.2.0", "0.3.0")   # 0.x minor differs → the real collision
    assert contract_compatible("1.4.0", "1.2.0")       # >=1.0: same major is enough
    assert not contract_compatible("1.9.0", "2.0.0")   # major differs → breaking
    assert contract_compatible("0.3.0", None)          # unknown on a side → don't block


def test_compatibility_error_is_actionable() -> None:
    server = VersionInfo(api="v1", registry="0.7.1", format="0.3.0", compiler="0.3.0")
    assert compatibility_error(server, server) is None

    old_client = VersionInfo(api="v1", registry="0.6.0", format="0.2.0")
    msg = compatibility_error(server, old_client)
    assert msg is not None and "just-dna-format contract mismatch" in msg

    # A differing registry *app* version is not fatal — the API is path-versioned.
    diff_app = VersionInfo(api="v1", registry="0.6.0", format="0.3.0")
    assert compatibility_error(server, diff_app) is None

    # A differing API major is fatal.
    v2_client = VersionInfo(api="v2", registry="0.7.1", format="0.3.0")
    msg2 = compatibility_error(server, v2_client)
    assert msg2 is not None and "API version mismatch" in msg2


# ── Server advertises its versions ───────────────────────────────────────────────


def test_version_endpoint_and_response_headers(client: TestClient) -> None:
    body = client.get("/api/v1/version").json()
    assert body["api"] == "v1"
    assert body["registry"] and body["format"]  # both installed in the test env

    headers = client.get("/health").headers
    assert headers["X-API-Version"] == "v1"
    assert headers["X-Registry-Version"]
    assert "X-Format-Version" in headers


# ── Client guard ─────────────────────────────────────────────────────────────────
# The client is a sync httpx.Client (can't drive an async ASGI transport), so we exercise the guard
# logic by stubbing the network layer — the real `/version` HTTP path is covered above via TestClient.


def _mk(**kw) -> RegistryClient:
    return RegistryClient("http://testserver", **kw)


def _version_response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status, json=payload, request=httpx.Request("GET", "http://testserver/api/v1/version")
    )


def test_server_version_parses_and_handles_a_pre_0_7_1_server(monkeypatch) -> None:
    with _mk() as c:
        payload = {"api": "v1", "registry": "0.7.1", "format": "0.3.0", "compiler": "0.3.0"}
        monkeypatch.setattr(c._http, "get", lambda url, *a, **k: _version_response(200, payload))
        assert c.server_version().format == "0.3.0"
        # A server too old to expose /version 404s → None (not an error).
        monkeypatch.setattr(c._http, "get", lambda url, *a, **k: _version_response(404))
        assert c.server_version() is None


def test_client_passes_when_compatible(monkeypatch) -> None:
    with _mk() as c:
        monkeypatch.setattr(c, "server_version", lambda: c.local_version)
        c.assert_compatible()  # server == client → no raise


def test_client_raises_on_contract_mismatch(monkeypatch) -> None:
    with _mk() as c:
        bad = VersionInfo(api="v1", registry="9.9.9", format="0.99.0")
        monkeypatch.setattr(c, "server_version", lambda: bad)
        with pytest.raises(VersionMismatchError) as ei:
            c.assert_compatible()
        assert ei.value.status_code == 409
        assert "just-dna-format contract mismatch" in str(ei.value.detail)
        # A mismatch is not cached: re-checking still raises (didn't silently pass on retry).
        with pytest.raises(VersionMismatchError):
            c.assert_compatible()


def test_guard_is_skippable(monkeypatch) -> None:
    with _mk(check_version=False) as c:
        monkeypatch.setattr(
            c, "server_version", lambda: VersionInfo(api="v1", registry="9", format="0.99.0")
        )
        c.assert_compatible()  # disabled → no-op even against an incompatible server


def test_old_server_is_skipped_not_fatal(monkeypatch) -> None:
    with _mk() as c:
        monkeypatch.setattr(c, "server_version", lambda: None)
        c.assert_compatible()  # warns, no raise


# ── The residue the handshake does not cover (S18) ───────────────────────────────


def test_a_patch_gap_is_compatible_and_still_advised() -> None:
    """The two halves of S18 in one assertion: the pair certifies, and the row schema still differs.

    `contract_compatible` is right to pass — within a minor the parquet contract and the digest
    really do hold — so the advisory is the only thing that can carry the residue. Asserting them
    together is what stops a later reader "fixing" the first by narrowing it to patch grain, which
    would refuse every pair this project actually runs (0.6.6 client, 0.6.1 server).
    """
    assert contract_compatible("0.6.1", "0.6.6")
    assert compatibility_error(
        VersionInfo(api="v1", registry="0.18.2", format="0.6.1"),
        VersionInfo(api="v1", registry="0.21.1", format="0.6.6"),
    ) is None
    advisory = schema_gap_advisory("0.6.1", "0.6.6")
    assert advisory is not None
    assert "0.6.1" in advisory and "0.6.6" in advisory


def test_the_advisory_fires_only_on_a_newer_client_within_one_minor() -> None:
    """Every direction the gap can point, because each one means something different.

    The older-client case is the one worth stating: a patch release *adds* columns, so a spec
    written against 0.6.1 stays legal on a 0.6.6 instance and there is nothing to warn about. A
    minor gap is deliberately silent here too — `compatibility_error` refuses that pair outright,
    and two messages about one fact is how a caller learns to read neither.
    """
    assert schema_gap_advisory("0.6.1", "0.6.6") is not None    # client newer: the S18 case
    assert schema_gap_advisory("0.6.6", "0.6.1") is None        # client older: still legal
    assert schema_gap_advisory("0.6.6", "0.6.6") is None        # matched
    assert schema_gap_advisory("0.6.1", "0.7.0") is None        # minor gap → already fatal
    assert schema_gap_advisory("0.6.1", None) is None           # client sent no header
    assert schema_gap_advisory(None, "0.6.6") is None           # server cannot say
    assert schema_gap_advisory("0.6.1", "0.6.6.dev0") is None   # unparseable → no guess


def test_the_advisory_never_reads_the_findings() -> None:
    """It is a function of two version strings and nothing else — the property that keeps it honest.

    An unknown column and a misspelled one are the *same* finding (`test_preflight_api.py` proves
    it on the real validator), so any attempt to fire this only on the real cause would have to
    match pydantic's wording. Stating it as a signature test rather than a comment, so the day
    someone threads `errors` in here to "reduce noise", this fails.
    """
    import inspect

    params = list(inspect.signature(schema_gap_advisory).parameters)
    assert params == ["server_format", "client_format"]
