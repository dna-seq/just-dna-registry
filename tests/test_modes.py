"""
Deployment modes (0.12): production refuses test data, the polygon can delete it.

Three behaviours differ by mode and nothing else does. Each is tested from both sides, because a mode
switch whose effect is only asserted in one direction is half a switch — and the half that matters is
usually "production still refuses".
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from just_dna_registry.api.app import create_app
from just_dna_registry.config import DEFAULT_PORTS, Settings

_YAML = """\
schema_version: "1.0"
module:
  name: {name}
  title: A module
  report_title: A module
  description: Fixture module for the mode tests.
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,{weight},risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _parts(name: str, *, data: str = "") -> list:
    weight = f"-0.{abs(hash(data or name)) % 89 + 10}"
    return [
        ("files", ("module_spec.yaml", _YAML.format(name=name).encode(), "text/yaml")),
        ("files", ("variants.csv", _VARIANTS.format(weight=weight).encode(), "text/csv")),
        ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
    ]


def _client(tmp_path: Path, mode: str) -> TestClient:
    empty = tmp_path / "no-cache"
    client = TestClient(create_app(Settings(
        mode=mode,
        db_path=tmp_path / "registry.db",
        local_storage_dir=tmp_path / "artifacts",
        ensembl_cache=empty, clinvar_cache=empty, constraint_cache=empty,
    )))
    repo = client.app.state.repo
    account = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account)
    repo.add_namespace("test-sandbox", account)
    repo.add_api_key("mk_live_testkey", account)
    return client


_AUTH = {"Authorization": "Bearer mk_live_testkey"}


# ── The mode itself ───────────────────────────────────────────────────────────


def test_an_unknown_mode_refuses_to_boot() -> None:
    """A typo must not resolve to either mode.

    Falling back to prod would silently deny the polygon its delete verb; falling back to test would arm
    a delete endpoint on production data. Neither is visible from a running server, so it fails here.
    """
    for bad in ("testing", "staging", "PROD ", ""):
        if bad.strip().lower() in ("prod", "test"):
            continue
        with pytest.raises(ValidationError):
            Settings(mode=bad)
    # The two real ones, including tolerated casing/whitespace.
    assert Settings(mode="TEST ").is_test_instance is True
    assert Settings(mode="prod").is_test_instance is False


def test_the_default_is_production() -> None:
    """The strict side is the default, so a missing REGISTRY_MODE cannot arm the polygon behaviours."""
    assert Settings().mode == "prod"
    assert Settings().is_test_instance is False


def test_the_ports_are_a_hundred_apart() -> None:
    """Far enough apart that a misdirected client is refused rather than answered by the wrong catalog."""
    assert DEFAULT_PORTS["test"] - DEFAULT_PORTS["prod"] == 100


def test_an_empty_test_prefix_is_refused() -> None:
    """It would make the production guard match every publish."""
    with pytest.raises(ValidationError):
        Settings(test_data_prefix="   ")


# ── The mode over the wire (0.13, S3) ─────────────────────────────────────────


def test_both_ops_endpoints_report_the_mode(tmp_path: Path) -> None:
    """S3: a rehearsal has to be able to prove which instance answered, before it spends anything.

    Both endpoints, because they serve different callers: `/health` needs no token and is what an
    operator or a proxy check curls, `/api/v1/version` is what the SDK already fetches for its
    contract guard. Asserted as the two modes disagreeing, not as one literal, so a hardcoded
    constant could not pass this.
    """
    seen = {}
    for mode in ("prod", "test"):
        client = _client(tmp_path / mode, mode)
        health = client.get("/health").json()
        version = client.get("/api/v1/version").json()
        assert health["mode"] == version["mode"], "one deployment cannot answer two modes"
        seen[mode] = health["mode"]
    assert seen == {"prod": "prod", "test": "test"}


def test_the_reported_mode_agrees_with_the_delete_verb(tmp_path: Path) -> None:
    """The property the field stands in for: the consumer was inferring mode from the route table.

    If the advertised mode and the mounted routes could disagree, the field would be worse than the
    probe it replaces — so the two are asserted together rather than separately.
    """
    for mode, deletes_mounted in (("prod", False), ("test", True)):
        client = _client(tmp_path / f"agree-{mode}", mode)
        assert client.get("/health").json()["mode"] == mode
        resp = client.delete(
            "/api/v1/modules/test-sandbox/burner/versions/1.0.0", headers=_AUTH
        )
        assert (resp.status_code != 405) is deletes_mounted


# ── The override: production accepts test data when asked explicitly (0.14) ───
#
# The guard stopped being absolute and became a default. Every test below is about the same pair of
# properties: a caller who says nothing still cannot put test data on production by accident, and a
# caller who says so explicitly is not blocked from a thing they have a real reason to want.


def test_the_default_is_still_a_refusal_and_the_message_names_the_way_through(
    tmp_path: Path,
) -> None:
    """The half that must not regress. The guard exists for a typo, and a typo passes no flags."""
    prod = _client(tmp_path, "prod")
    refused = prod.post("/api/v1/modules/test-sandbox/burner/versions",
                        data={"version": "1.0.0"}, files=_parts("burner"), headers=_AUTH)
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "test_data_on_prod"
    # A dead end an author cannot navigate is what makes a guard feel arbitrary.
    assert "allow_test_data=true" in " ".join(refused.json()["detail"]["errors"])


def test_prod_accepts_a_test_namespace_publish_when_asked_explicitly(tmp_path: Path) -> None:
    prod = _client(tmp_path, "prod")
    resp = prod.post(
        "/api/v1/modules/test-sandbox/burner/versions",
        data={"version": "1.0.0", "allow_test_data": "true"},
        files=_parts("burner"),
        headers=_AUTH,
    )
    assert resp.status_code == 201, resp.text


def test_prod_accepts_a_test_prefixed_module_name_when_asked_explicitly(tmp_path: Path) -> None:
    """The other spelling — `test_` with an underscore — goes through the same one flag."""
    prod = _client(tmp_path, "prod")
    resp = prod.post(
        "/api/v1/modules/just-dna-seq/test_panel/versions",
        data={"version": "1.0.0", "allow_test_data": "true"},
        files=_parts("test_panel"),
        headers=_AUTH,
    )
    assert resp.status_code == 201, resp.text


def test_claiming_a_test_namespace_on_prod_needs_the_flag_and_then_warns(tmp_path: Path) -> None:
    """Accepted is not silent: production is now holding test-prefixed data and says so.

    The warning names the purge on purpose — `purge-test-data` selects on exactly this prefix, so
    data kept here deliberately is data a routine cleanup would remove.
    """
    prod = _client(tmp_path, "prod")
    assert prod.post(
        "/api/v1/namespaces", json={"namespace": "test-sheep"}, headers=_AUTH
    ).status_code == 422
    assert prod.app.state.repo.namespace_owner("test-sheep") is None

    ok = prod.post(
        "/api/v1/namespaces",
        json={"namespace": "test-sheep", "allow_test_data": True},
        headers=_AUTH,
    )
    assert ok.status_code == 201, ok.text
    assert prod.app.state.repo.namespace_owner("test-sheep") is not None
    warnings = " ".join(ok.json()["warnings"])
    assert "allow_test_data=true" in warnings and "purge-test-data" in warnings


def test_availability_warns_about_the_rule_the_claim_will_apply(tmp_path: Path) -> None:
    """S6: the read-only pre-flight for an irreversible act used to report the opposite of it.

    `available` stays `true` (nobody holds the name) and `valid` stays `true` (since 0.14 the name
    genuinely is claimable here, with the flag) — the missing rule arrives as a warning plus a
    machine-readable field, rather than by making one of the other two lie in a new direction.
    """
    prod = _client(tmp_path, "prod")
    body = prod.get("/api/v1/namespaces/test-sheep").json()
    assert body["available"] is True and body["valid"] is True
    assert body["requires_allow_test_data"] is True
    assert "allow_test_data=true" in " ".join(body["warnings"])

    # And the pre-flight agrees with what the claim actually does, which is the whole point.
    assert prod.post(
        "/api/v1/namespaces", json={"namespace": "test-sheep"}, headers=_AUTH
    ).status_code == 422
    assert prod.post(
        "/api/v1/namespaces",
        json={"namespace": "test-sheep", "allow_test_data": True},
        headers=_AUTH,
    ).status_code == 201


def test_availability_says_nothing_extra_for_an_ordinary_name(tmp_path: Path) -> None:
    prod = _client(tmp_path, "prod")
    body = prod.get("/api/v1/namespaces/longevity").json()
    assert body["requires_allow_test_data"] is False and body["warnings"] == []


def test_the_polygon_never_needed_the_flag(tmp_path: Path) -> None:
    """On the test box this is the data the instance exists to hold, so there is nothing to wave."""
    polygon = _client(tmp_path, "test")
    body = polygon.get("/api/v1/namespaces/test-sheep").json()
    assert body["requires_allow_test_data"] is False and body["warnings"] == []
    assert polygon.post(
        "/api/v1/namespaces", json={"namespace": "test-sheep"}, headers=_AUTH
    ).status_code == 201


# ── Production refuses test data ──────────────────────────────────────────────


def test_prod_refuses_a_test_namespace_publish_and_the_polygon_accepts_it(tmp_path: Path) -> None:
    prod = _client(tmp_path / "p", "prod")
    refused = prod.post("/api/v1/modules/test-sandbox/burner/versions",
                        data={"version": "1.0.0"}, files=_parts("burner"), headers=_AUTH)
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "test_data_on_prod"
    # The message has to say what to do about it, not just that it was refused.
    assert "test instance" in " ".join(refused.json()["detail"]["errors"])

    polygon = _client(tmp_path / "t", "test")
    assert polygon.post("/api/v1/modules/test-sandbox/burner/versions",
                        data={"version": "1.0.0"}, files=_parts("burner"),
                        headers=_AUTH).status_code == 201


def test_prod_refuses_a_test_prefixed_module_name_in_a_real_namespace(tmp_path: Path) -> None:
    """The other spelling: `test_` with an underscore, which is the only form a module name allows."""
    prod = _client(tmp_path, "prod")
    refused = prod.post("/api/v1/modules/just-dna-seq/test_panel/versions",
                        data={"version": "1.0.0"}, files=_parts("test_panel"), headers=_AUTH)
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "test_data_on_prod"


def test_prod_refuses_to_even_claim_a_test_namespace(tmp_path: Path) -> None:
    """Blocking only the publish would leave the name claimed and the caller's quota spent on a
    namespace nothing could ever be pushed to."""
    prod = _client(tmp_path, "prod")
    resp = prod.post("/api/v1/namespaces", json={"namespace": "test-else"}, headers=_AUTH)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "test_data_on_prod"
    assert prod.app.state.repo.namespace_owner("test-else") is None  # nothing was claimed

    polygon = _client(tmp_path / "t", "test")
    assert polygon.post(
        "/api/v1/namespaces", json={"namespace": "test-else"}, headers=_AUTH
    ).status_code == 201


# ── The polygon's delete verb ─────────────────────────────────────────────────


def test_delete_is_not_mounted_on_production(tmp_path: Path) -> None:
    """Refused by the *router*, not by a handler: on production nothing is listening for the verb, so a
    client holding a valid token cannot delete published data even by accident.

    **405, not 404** — the paths themselves exist (they serve GET and POST), so the honest answer is
    "method not allowed" rather than "no such module". Asserted as 405 because that is what a client will
    actually see, and a test written against the wrong code would pass for the wrong reason the day
    somebody mounts the router unconditionally on a path that has no other verbs.
    """
    prod = _client(tmp_path, "prod")
    assert prod.post("/api/v1/modules/just-dna-seq/coronary/versions",
                     data={"version": "1.0.0"}, files=_parts("coronary"),
                     headers=_AUTH).status_code == 201

    for path in (
        "/api/v1/modules/just-dna-seq/coronary/versions/1.0.0",
        "/api/v1/modules/just-dna-seq/coronary",
    ):
        assert prod.delete(path, headers=_AUTH).status_code == 405
    # ...and the version is still there.
    assert prod.app.state.repo.get_module_row("just-dna-seq", "coronary") is not None


def test_the_polygon_delete_frees_the_version_and_its_content_claim(tmp_path: Path) -> None:
    """The whole reason the verb exists: a rehearsal must be repeatable.

    A published version is immutable and its data is claimed by a `content_hash` that `yank` does not
    release, so without delete every rehearsal permanently burns both a version number and the right to
    publish that data anywhere else. Both are asserted here, because freeing only the version number
    would leave the more annoying half of the problem in place.
    """
    polygon = _client(tmp_path, "test")
    url = "/api/v1/modules/test-sandbox/burner/versions"
    assert polygon.post(url, data={"version": "1.0.0"}, files=_parts("burner", data="x"),
                        headers=_AUTH).status_code == 201
    # Same version number again → refused while it exists.
    assert polygon.post(url, data={"version": "1.0.0"}, files=_parts("burner", data="x"),
                        headers=_AUTH).status_code == 409

    assert polygon.delete(f"{url}/1.0.0", headers=_AUTH).status_code == 204

    # The version number is reusable...
    assert polygon.post(url, data={"version": "1.0.0"}, files=_parts("burner", data="x"),
                        headers=_AUTH).status_code == 201
    # ...and after removing it again, the same *data* publishes under a different name (the claim went).
    assert polygon.delete(f"{url}/1.0.0", headers=_AUTH).status_code == 204
    assert polygon.post("/api/v1/modules/test-sandbox/other/versions",
                        data={"version": "1.0.0"}, files=_parts("other", data="x"),
                        headers=_AUTH).status_code == 201


def test_the_polygon_delete_still_needs_the_namespace(tmp_path: Path) -> None:
    """"Open" means the verb is available, never that it is unauthenticated — the polygon answers on a
    public DNS name."""
    polygon = _client(tmp_path, "test")
    assert polygon.post("/api/v1/modules/test-sandbox/burner/versions",
                        data={"version": "1.0.0"}, files=_parts("burner"),
                        headers=_AUTH).status_code == 201

    repo = polygon.app.state.repo
    stranger = repo.create_account("stranger")
    repo.add_api_key("mk_live_stranger", stranger)

    assert polygon.delete("/api/v1/modules/test-sandbox/burner/versions/1.0.0").status_code == 401
    assert polygon.delete(
        "/api/v1/modules/test-sandbox/burner/versions/1.0.0",
        headers={"Authorization": "Bearer mk_live_stranger"},
    ).status_code == 403
    assert repo.get_module_row("test-sandbox", "burner") is not None


def test_deleting_a_missing_version_is_a_404_not_a_silent_success(tmp_path: Path) -> None:
    polygon = _client(tmp_path, "test")
    assert polygon.delete(
        "/api/v1/modules/test-sandbox/nope/versions/1.0.0", headers=_AUTH
    ).status_code == 404
    assert polygon.delete("/api/v1/modules/test-sandbox/nope", headers=_AUTH).status_code == 404


# ── Setting the mode from the CLI ──────────────────────────────────────────────


def test_serve_mode_flag_exports_the_env_var_the_worker_will_read(monkeypatch) -> None:
    """`--mode test` has to reach a *different process*, so it works by exporting REGISTRY_MODE.

    uvicorn imports the app by string, so `create_app()` runs in the worker and builds its own
    `Settings` from the environment — and with `--reload` that worker is a separate process entirely.
    Handing a value to a `Settings` object here would configure the CLI and nothing that serves a
    request, which is a bug that would look like the flag being ignored at runtime only.
    """
    import uvicorn as uvicorn_module

    from just_dna_registry import cli
    from just_dna_registry.config import get_settings

    monkeypatch.delenv("REGISTRY_MODE", raising=False)
    get_settings.cache_clear()
    captured: dict = {}
    monkeypatch.setattr(uvicorn_module, "run", lambda *a, **kw: captured.update(kw))

    try:
        cli.serve(host="127.0.0.1", port=None, mode="test", reload=False)
        assert os.environ["REGISTRY_MODE"] == "test"   # what the worker will actually read
        assert captured["port"] == DEFAULT_PORTS["test"]  # and the port followed the flag
        assert get_settings().is_test_instance is True    # this process agrees with the worker
    finally:
        # `os.environ.pop`, NOT `monkeypatch.delenv`. `cli.serve` sets this behind monkeypatch's
        # back, so a delenv here would *record* "test" as the value to restore and teardown would
        # put it back — leaking a polygon default into every test that runs after this file, which
        # is how `create_app` on default Settings silently gained the delete routes.
        os.environ.pop("REGISTRY_MODE", None)
        get_settings.cache_clear()


def test_serve_rejects_an_unknown_mode_before_starting_anything(monkeypatch) -> None:
    """A typo fails at the CLI with the valid values named, rather than deep in a worker import."""
    import typer
    import uvicorn as uvicorn_module

    from just_dna_registry import cli

    started: list = []
    monkeypatch.setattr(uvicorn_module, "run", lambda *a, **kw: started.append(kw))
    with pytest.raises(typer.BadParameter) as excinfo:
        cli.serve(host="127.0.0.1", port=None, mode="testing", reload=False)
    assert "prod" in str(excinfo.value) and "test" in str(excinfo.value)
    assert started == []  # nothing was launched


def test_no_flag_leaves_the_environment_alone(monkeypatch) -> None:
    """Omitting `--mode` must not stamp a value: a deployment sets REGISTRY_MODE in its unit file, and
    the CLI silently exporting `prod` over it would override the operator's own configuration."""
    import uvicorn as uvicorn_module

    from just_dna_registry import cli
    from just_dna_registry.config import get_settings

    monkeypatch.setenv("REGISTRY_MODE", "test")
    get_settings.cache_clear()
    captured: dict = {}
    monkeypatch.setattr(uvicorn_module, "run", lambda *a, **kw: captured.update(kw))
    try:
        cli.serve(host="127.0.0.1", port=None, mode=None, reload=False)
        assert os.environ["REGISTRY_MODE"] == "test"      # untouched
        assert captured["port"] == DEFAULT_PORTS["test"]  # and honoured
    finally:
        get_settings.cache_clear()
