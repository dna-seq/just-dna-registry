"""RegistryClient SDK (0.8.1) — real, in-process coverage of the full REST surface it now wraps
(identity/profile, members, yank, stars, reviews, groups, aggregate stats).

The SDK is synchronous (the CLI depends on that), and a sync httpx client can't drive an async
ASGI transport — so each call is bridged onto a worker thread with `asyncio.to_thread` while the
FastAPI app is driven in-process through Starlette's ASGI transport. Real routers, DB, and auth —
no stubbed HTTP layer."""

import asyncio
import inspect
import io
from pathlib import Path

import pytest
import typer
from fastapi.testclient import TestClient
from test_import import _bare_parquet_zip

from just_dna_registry import client_cli
from just_dna_registry.client import (
    ModeMismatchError,
    RegistryClient,
    gather_spec_files,
    split_derived,
)
from just_dna_registry.specfiles import DERIVED_DIR, DERIVED_FILES, plan_layout

_NS, _NAME, _VER = "just-dna-seq", "coronary", "1.0.0"


@pytest.fixture
def sdk(app, api_key):
    """A real RegistryClient bound to the in-process app; token = the namespace-owner account."""
    tc = TestClient(app)
    client = RegistryClient(
        "http://testserver", token=api_key, transport=tc._transport, check_version=False
    )
    try:
        yield client
    finally:
        client.close()


def _seed_module(seed, name: str = _NAME, genes=("LPA",), created_at="2025-01-01T00:00:00Z"):
    return seed(_NS, name, _VER, genes=list(genes), categories=["cardio"], created_at=created_at)


async def test_download_latest_resolves(sdk, seed) -> None:
    _seed_module(seed)  # publishes _NAME @ _VER; latest_version == _VER
    assert await asyncio.to_thread(lambda: sdk.resolve_version(_NS, _NAME, "latest")) == _VER
    assert await asyncio.to_thread(lambda: sdk.resolve_version(_NS, _NAME, "9.9.9")) == "9.9.9"


async def test_whoami_and_profile(sdk) -> None:
    who = await asyncio.to_thread(sdk.whoami)
    assert who["account"] == "antonkulaga" and who["type"] == "user"
    updated = await asyncio.to_thread(
        lambda: sdk.update_profile(display_name="Anton", avatar_url="https://x/a.png")
    )
    assert updated["display_name"] == "Anton" and updated["avatar_url"] == "https://x/a.png"
    assert (await asyncio.to_thread(sdk.whoami))["display_name"] == "Anton"


async def test_members_roundtrip(sdk, app) -> None:
    app.state.repo.create_account("bob")
    roster = await asyncio.to_thread(lambda: sdk.add_member(_NS, "bob", "member"))
    assert {m["account"] for m in roster["members"]} >= {"antonkulaga", "bob"}
    listed = await asyncio.to_thread(lambda: sdk.members(_NS))
    assert any(m["account"] == "bob" for m in listed)
    after = await asyncio.to_thread(lambda: sdk.remove_member(_NS, "bob"))
    assert all(m["account"] != "bob" for m in after["members"])


async def test_stars(sdk, seed) -> None:
    _seed_module(seed)
    starred = await asyncio.to_thread(lambda: sdk.star(_NS, _NAME))
    assert starred["stars"] == 1 and starred["starred_by_me"] is True
    unstarred = await asyncio.to_thread(lambda: sdk.unstar(_NS, _NAME))
    assert unstarred["stars"] == 0


async def test_reviews_highlight_and_curated_stat(sdk, seed) -> None:
    _seed_module(seed)
    posted = await asyncio.to_thread(
        lambda: sdk.review(_NS, _NAME, _VER, rating=5, verdict="verified")
    )
    assert posted[0]["rating"] == 5 and posted[0]["highlighted"] is False
    highlighted = await asyncio.to_thread(
        lambda: sdk.highlight_review(_NS, _NAME, _VER, "antonkulaga")
    )
    assert highlighted[0]["highlighted"] is True
    # The highlight is what the `curated` group/stat keys on.
    curated = await asyncio.to_thread(lambda: sdk.catalog_stats(group="curated"))
    assert curated["curated"] == 1
    assert await asyncio.to_thread(lambda: sdk.delete_review(_NS, _NAME, _VER)) == []


async def test_yank_unyank(sdk, seed) -> None:
    _seed_module(seed)
    assert (await asyncio.to_thread(lambda: sdk.yank(_NS, _NAME, _VER)))["yanked"] is True
    assert (await asyncio.to_thread(lambda: sdk.unyank(_NS, _NAME, _VER)))["yanked"] is False


async def test_groups_and_catalog_stats(sdk, seed) -> None:
    _seed_module(seed)
    _seed_module(seed, name="cardio2", genes=("APOB", "PCSK9"), created_at="2025-02-01T00:00:00Z")
    keys = [g["key"] for g in await asyncio.to_thread(sdk.groups)]
    assert keys[0] == "all" and "curated" in keys
    stats = await asyncio.to_thread(sdk.catalog_stats)
    assert stats["modules"] >= 2 and stats["genes"] >= 3 and stats["namespaces"] == 1


# ── 0.11: pre-flight, and the two gaps that were open until now ───────────────


def _write_spec(tmp_path, name: str = _NAME):
    spec = tmp_path / "spec"
    spec.mkdir(exist_ok=True)
    (spec / "module_spec.yaml").write_text(
        f'schema_version: "1.0"\nmodule:\n  name: {name}\n  title: T\n'
        f"  description: d\n  report_title: R\ngenome_build: GRCh38\n"
    )
    (spec / "variants.csv").write_text(
        "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
        "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
    )
    (spec / "studies.csv").write_text(
        "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"
    )
    return spec


async def test_content_signature_is_computed_locally(sdk, tmp_path) -> None:
    """No HTTP at all — that is the point. A publisher can dedup before uploading anything."""
    spec = _write_spec(tmp_path)
    signature = await asyncio.to_thread(lambda: sdk.content_signature(spec))
    assert signature.startswith("sha256:")


async def test_is_published_reports_free_then_taken(sdk, tmp_path, app) -> None:
    spec = _write_spec(tmp_path)
    assert await asyncio.to_thread(lambda: sdk.is_published(spec)) == []

    published = await asyncio.to_thread(lambda: sdk.publish(_NS, _NAME, _VER, spec))
    taken = await asyncio.to_thread(lambda: sdk.is_published(spec))
    assert [(v.name, v.version) for v in taken] == [(_NAME, _VER)]
    assert published.content_signature == await asyncio.to_thread(
        lambda: sdk.content_signature(spec)
    )


async def test_is_published_answers_the_named_question_too(sdk, tmp_path) -> None:
    """S10's client half: the unfiltered call cannot tell "taken" from "mine".

    `is_published` is name-independent by design — the right shape for classifying a local corpus,
    the wrong one for a verdict, since publish allows a later version of the *same* module built from
    unchanged data. Naming the module you intend to publish under restores "empty list = free to
    publish", which is what the docstring had been claiming unconditionally.
    """
    spec = _write_spec(tmp_path)
    await asyncio.to_thread(lambda: sdk.publish(_NS, _NAME, _VER, spec))

    assert [v.name for v in await asyncio.to_thread(lambda: sdk.is_published(spec))] == [_NAME]
    assert await asyncio.to_thread(
        lambda: sdk.is_published(spec, namespace=_NS, name=_NAME)
    ) == []
    assert [
        v.name
        for v in await asyncio.to_thread(
            lambda: sdk.is_published(spec, namespace=_NS, name="rebranded")
        )
    ] == [_NAME]

    # Half a module name matches nothing, so it would silently answer the unfiltered question.
    with pytest.raises(ValueError):
        await asyncio.to_thread(lambda: sdk.is_published(spec, namespace=_NS))


async def test_validate_returns_a_typed_report(sdk, tmp_path) -> None:
    report = await asyncio.to_thread(lambda: sdk.validate(_NS, _NAME, _write_spec(tmp_path)))
    assert report.valid is True and report.strict is True
    assert report.stats.variant_count == 1
    assert report.content_signature is not None
    # The ceiling-free branchable field (S1). Typed through the SDK, not just present on the wire.
    assert report.would_publish_module_level is True


async def test_check_returns_a_typed_report(sdk, tmp_path) -> None:
    report = await asyncio.to_thread(
        lambda: sdk.check(_NS, _NAME, _write_spec(tmp_path), offline=True)
    )
    assert report.would_publish is True
    assert report.enrichment is not None and report.enrichment.offline is True


async def test_the_cli_prints_a_pass_that_reached_nothing(capsys, monkeypatch) -> None:
    """An outage must reach the screen, not just the JSON.

    The frequency, literature and ACMG passes print no summary line of their own, so a pass that
    reached nothing renders as an entirely clean check — the same empty-list trap one layer up. This
    is the only place `unreachable` becomes visible for three of the five, which is why it prints
    before any findings rather than beside them.
    """
    from just_dna_registry import client_cli
    from just_dna_registry.models.api import (
        CheckReport, EnrichmentReport, FrequencyCheck, ValidationReport,
    )

    report = CheckReport(
        validation=ValidationReport(valid=True, strict=False, would_publish_module_level=True),
        enrichment=EnrichmentReport(
            frequencies=FrequencyCheck(unreachable=["gnomad"], warnings=["gnomAD 503"]),
        ),
        would_publish=True,
        elapsed_seconds=0.1,
    )
    monkeypatch.setattr(client_cli, "_client", lambda *a, **k: _StubCheck(report))
    # Returns rather than exiting: `would_publish` is true, and an upstream outage is not a failed
    # check. Only `✗ would NOT publish` raises `typer.Exit(1)`.
    client_cli.check(
        _NS, _NAME, Path("."), strict=False, offline=False, frequencies=True, literature=False,
        identifiers=False, acmg=False, pgx=False, use=None, pack=False, url=None, token=None,
    )

    printed = capsys.readouterr().out
    assert "gnomad" in printed
    assert "unchecked, not clean" in printed
    assert "✓ would publish" in printed


class _StubCheck:
    """Returns one prepared report. The renderer is what is under test, not the transport."""

    def __init__(self, report) -> None:
        self._report = report

    def check(self, *_a, **_k):
        return self._report

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        pass


async def test_health_is_wrapped(sdk) -> None:
    """Mounted outside `/api/v1`, which is why it went unwrapped until 0.11."""
    health = await asyncio.to_thread(sdk.health)
    assert health["status"] == "ok"
    assert health["mode"] == "prod", "the test app builds default Settings, which are production"
    # S4's ops fields ride through untyped on purpose — `/health` is a dict, not a contract model.
    assert set(health["catalog"]) == {"modules", "versions", "yanked", "namespaces"}
    assert set(health["enrichment"]) == {"active", "queued", "limit"}


async def test_expect_mode_refuses_the_wrong_deployment(app, api_key, tmp_path) -> None:
    """S3: the guard that makes a rehearsal target verifiable rather than merely declared.

    The failure it exists for is the one the service cannot undo — a publish aimed at the polygon
    that lands on production spends a version number and claims the data's `content_hash` globally,
    and there is no delete verb there to take it back. So it has to raise before the first request
    that could spend anything, not after.
    """
    tc = TestClient(app)  # default Settings — a production instance
    spec = _write_spec(tmp_path)

    aiming_at_the_polygon = RegistryClient(
        "http://testserver", token=api_key, transport=tc._transport, expect_mode="test"
    )
    # Up front, and again on a call that would have spent something — the guard is worth nothing if
    # it only answers when asked directly.
    with pytest.raises(ModeMismatchError) as caught:
        await asyncio.to_thread(aiming_at_the_polygon.assert_compatible)
    assert caught.value.expected == "test" and caught.value.actual == "prod"
    with pytest.raises(ModeMismatchError):
        await asyncio.to_thread(lambda: aiming_at_the_polygon.validate(_NS, _NAME, spec))
    aiming_at_the_polygon.close()

    correct = RegistryClient(
        "http://testserver", token=api_key, transport=tc._transport, expect_mode="prod"
    )
    assert (await asyncio.to_thread(lambda: correct.validate(_NS, _NAME, spec))).valid is True
    correct.close()


async def test_expect_mode_survives_check_version_being_off(app, api_key) -> None:
    """The two guards answer different questions, so silencing one must not silence the other.

    A caller who turned off the contract check has not thereby agreed to publish on an instance
    whose identity nobody established. An older server that cannot report a mode fails the same way,
    for the same reason: asking for verification and getting silence is not a pass.
    """
    tc = TestClient(app)
    client = RegistryClient(
        "http://testserver",
        token=api_key,
        transport=tc._transport,
        check_version=False,
        expect_mode="test",
    )
    with pytest.raises(ModeMismatchError):
        await asyncio.to_thread(client.assert_compatible)
    client.close()


async def test_issue_jwt_token_is_wrapped(sdk, api_key) -> None:
    """501 when the server has no `jwt_secret` — which is the default, so that is the wired path."""
    from just_dna_registry.client import RegistryError

    with pytest.raises(RegistryError) as caught:
        await asyncio.to_thread(lambda: sdk.issue_jwt_token(api_key))
    assert caught.value.status_code == 501


async def test_check_threads_pgx_and_declared_use(sdk, tmp_path) -> None:
    """The two axes must reach the server, or the SDK quietly answers a different question."""
    report = await asyncio.to_thread(
        lambda: sdk.check(
            _NS, _NAME, _write_spec(tmp_path),
            offline=True, pgx=True, declared_use="non_commercial",
        )
    )
    assert report.enrichment is not None
    assert report.enrichment.pgx is not None
    assert report.enrichment.pgx.declared_use == "non_commercial"


async def test_versions_is_pageable(sdk, seed) -> None:
    """The listing is paged server-side, so an unpageable wrapper can only ever see the first page —
    which for a module with a long history is not the page you want."""
    for minor in range(3):
        seed(_NS, _NAME, f"1.{minor}.0", genes=["LPA"], categories=["cardio"],
             created_at=f"2025-0{minor + 1}-01T00:00:00Z")
    first = await asyncio.to_thread(lambda: sdk.versions(_NS, _NAME, page=1, per_page=2))
    second = await asyncio.to_thread(lambda: sdk.versions(_NS, _NAME, page=2, per_page=2))
    assert first["total"] == 3 and (first["page"], first["per_page"]) == (1, 2)
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    listed = {v["version"] for v in first["items"] + second["items"]}
    assert listed == {"1.0.0", "1.1.0", "1.2.0"}


async def test_import_module_threads_genome_build(sdk, tmp_path) -> None:
    """`genome_build` is the one importable form field that is *inside* `artifact.digest`, and the
    SDK dropped it — so an SDK import of a GRCh37 archive silently produced GRCh38 identity keys.
    The assertion is on the bytes, because a relabel would pass a metadata check: declaring the
    build has to reproduce the digest the module was compiled to.

    (`tests/test_import.py` proves the same over raw HTTP; this is the wrapper, which is the half
    the webui and the CLI actually call.)
    """
    archive, original_digest = _bare_parquet_zip(tmp_path, "GRCh37")
    zip_path = tmp_path / "legacy.zip"
    zip_path.write_bytes(archive)

    guessed = await asyncio.to_thread(
        lambda: sdk.import_module(_NS, "hfe_build", "1.0.0", zip_path)
    )
    assert guessed.artifact.digest != original_digest, "no manifest in the archive → GRCh38 default"

    declared = await asyncio.to_thread(
        lambda: sdk.import_module(
            _NS, "hfe_build", "1.0.1", zip_path, display={"genome_build": "GRCh37"}
        )
    )
    assert declared.artifact.digest == original_digest


# ── The parity guard: a route with no client method is an unfinished route ─────
#
# SDK↔API drift is what blocked webui publishing in 0.8.1, so the coverage is asserted structurally
# rather than trusted to review. The table is the contract: adding a route without wrapping it fails
# here with the route named, and so does renaming a client method out from under one.

_WRAPPED_ROUTES: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/health"): ("health",),
    ("GET", "/api/v1/version"): ("server_version",),
    ("GET", "/api/v1/pubkey"): ("pubkey",),
    ("POST", "/api/v1/auth/register"): ("register",),
    ("POST", "/api/v1/auth/tokens"): ("issue_jwt_token",),
    ("GET", "/api/v1/auth/whoami"): ("whoami",),
    ("PATCH", "/api/v1/auth/whoami"): ("update_profile",),
    # `list_modules` alone — `catalog_stats` merely pages it, and listing a roll-up here would let
    # its own `namespace=`/`group=` arguments stand in for filters the real wrapper had dropped.
    ("GET", "/api/v1/modules"): ("list_modules",),
    ("GET", "/api/v1/modules/groups"): ("groups",),
    ("GET", "/api/v1/modules/lookup"): ("lookup_by_digest", "lookup_by_signature"),
    ("POST", "/api/v1/modules/lookup"): ("lookup_by_digests", "lookup_by_signatures"),
    ("GET", "/api/v1/modules/{namespace}/{name}"): ("get_module", "resolve_version"),
    ("POST", "/api/v1/modules/{namespace}/{name}/validate"): ("validate",),
    ("POST", "/api/v1/modules/{namespace}/{name}/check"): ("check",),
    ("PUT", "/api/v1/modules/{namespace}/{name}/star"): ("star",),
    ("DELETE", "/api/v1/modules/{namespace}/{name}/star"): ("unstar",),
    ("GET", "/api/v1/modules/{namespace}/{name}/reviews"): ("reviews",),
    ("GET", "/api/v1/modules/{namespace}/{name}/versions"): ("versions",),
    ("POST", "/api/v1/modules/{namespace}/{name}/versions"): ("publish",),
    ("POST", "/api/v1/modules/{namespace}/{name}/versions/import"): ("import_module",),
    ("PATCH", "/api/v1/modules/{namespace}/{name}/versions/{version}"): ("amend_changelog",),
    ("GET", "/api/v1/modules/{namespace}/{name}/versions/{version}/manifest"): ("manifest",),
    ("GET", "/api/v1/modules/{namespace}/{name}/versions/{version}/logs"): ("logs",),
    ("GET", "/api/v1/modules/{namespace}/{name}/versions/{version}/download"): (
        "download", "get_tarball",
    ),
    ("GET", "/api/v1/modules/{namespace}/{name}/versions/{version}/files/{file_path}"): (
        "_fetch_file",
    ),
    ("POST", "/api/v1/modules/{namespace}/{name}/versions/{version}/logo"): ("amend_logo",),
    ("POST", "/api/v1/modules/{namespace}/{name}/versions/{version}/readme"): ("amend_readme",),
    ("POST", "/api/v1/modules/{namespace}/{name}/versions/{version}/yank"): ("yank", "unyank"),
    ("GET", "/api/v1/modules/{namespace}/{name}/versions/{version}/reviews"): ("reviews",),
    ("PUT", "/api/v1/modules/{namespace}/{name}/versions/{version}/reviews"): ("review",),
    ("DELETE", "/api/v1/modules/{namespace}/{name}/versions/{version}/reviews"): (
        "delete_review",
    ),
    ("PUT", "/api/v1/modules/{namespace}/{name}/versions/{version}/reviews/{reviewer}/highlight"): (
        "highlight_review",
    ),
    (
        "DELETE",
        "/api/v1/modules/{namespace}/{name}/versions/{version}/reviews/{reviewer}/highlight",
    ): ("highlight_review",),
    ("POST", "/api/v1/namespaces"): ("claim_namespace",),
    ("GET", "/api/v1/namespaces/{namespace}"): ("namespace_available",),
    ("GET", "/api/v1/namespaces/{namespace}/members"): ("members",),
    ("POST", "/api/v1/namespaces/{namespace}/members"): ("add_member",),
    ("DELETE", "/api/v1/namespaces/{namespace}/members/{member}"): ("remove_member",),
    ("POST", "/api/v1/orgs"): ("create_org",),
    ("GET", "/api/v1/orgs/{org}/members"): ("org_members",),
    ("POST", "/api/v1/orgs/{org}/members"): ("add_org_member",),
    ("DELETE", "/api/v1/orgs/{org}/members/{member}"): ("remove_org_member",),
    ("PUT", "/api/v1/orgs/{org}/members/{member}/role"): ("set_org_role",),
    ("POST", "/api/v1/orgs/{org}/namespaces"): ("create_org_namespace",),
    ("PATCH", "/api/v1/orgs/{org}/settings"): ("update_org_settings",),
    # Mounted only on a test instance (`REGISTRY_MODE=test`), and covered here anyway — see
    # `test_every_route_is_wrapped_by_a_client_method` for why the guard enumerates both modes.
    ("DELETE", "/api/v1/modules/{namespace}/{name}/versions/{version}"): ("delete_version",),
    ("DELETE", "/api/v1/modules/{namespace}/{name}"): ("delete_module",),
}


def _server_routes(app) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def test_every_route_is_wrapped_by_a_client_method(app, tmp_path) -> None:
    """Every served route has a client method — **in both deployment modes**.

    The `app` fixture is a production instance, and 0.12 added routes that only exist on the polygon
    (`DELETE` on a module/version). Enumerating one mode would have let those ship unwrapped: the guard
    would have passed while the SDK had no method for a live endpoint, which is exactly the drift that
    blocked webui publishing in 0.8.1. So the union of both modes' routes is compared against the table,
    and a mode-gated route is as much a route as any other.
    """
    from just_dna_registry.api.app import create_app
    from just_dna_registry.config import Settings

    polygon = create_app(Settings(
        mode="test",
        db_path=tmp_path / "polygon.db",
        local_storage_dir=tmp_path / "polygon-artifacts",
    ))
    served = _server_routes(app) | _server_routes(polygon)
    assert served == set(_WRAPPED_ROUTES), (
        "unwrapped routes: "
        f"{sorted(served - set(_WRAPPED_ROUTES))}; routes that no longer exist: "
        f"{sorted(set(_WRAPPED_ROUTES) - served)}"
    )
    # The polygon adds routes and never removes any: a mode must not be able to hide an endpoint.
    assert _server_routes(app) < _server_routes(polygon)


# The one query param the SDK deliberately spells as two methods rather than an argument: `format`
# selects between a file listing to walk and a single tarball, and the two return different types
# (`ModuleManifest` after verification vs a `Path`), so one method with a mode switch would have a
# return type that depends on a string.
_NOT_AN_ARGUMENT: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/modules/{namespace}/{name}/versions/{version}/download"): {"format"},
}


def test_every_query_param_is_spellable_from_the_sdk(app) -> None:
    """A server ignores a query param it does not know, so an unsendable filter is not an error —
    it is a *wider* result set that looks like a working search, or a check that silently never ran.
    Union across the wrappers, since some routes are split into several methods."""
    unreachable: dict[tuple[str, str], list[str]] = {}
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            route = (method.upper(), path)
            wanted = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter["in"] == "query"
            } - _NOT_AN_ARGUMENT.get(route, set())
            sendable: set[str] = set()
            for wrapper in _WRAPPED_ROUTES.get(route, ()):
                sendable |= set(inspect.signature(getattr(RegistryClient, wrapper)).parameters)
            if wanted - sendable:
                unreachable[route] = sorted(wanted - sendable)
    assert unreachable == {}


def test_the_wrapper_names_still_resolve() -> None:
    """The table is only worth having if a rename breaks it rather than the caller."""
    missing = [
        name
        for names in _WRAPPED_ROUTES.values()
        for name in names
        if not callable(getattr(RegistryClient, name, None))
    ]
    assert missing == []


@pytest.mark.parametrize(
    ("path", "sdk_method", "cli_command"),
    [
        ("/api/v1/modules/{namespace}/{name}/check", "check", "check"),
        ("/api/v1/modules/{namespace}/{name}/validate", "validate", "validate"),
    ],
)
def test_preflight_query_flags_reach_the_cli_too(
    app, path: str, sdk_method: str, cli_command: str
) -> None:
    """The pre-flight endpoints are held to the stricter bar: the CLI must expose every flag as well,
    not just the SDK. This is the drift that recurs — each new enrichment pass adds a flag, and one
    the CLI cannot pass reads as a clean report on a question nobody asked."""
    operation = app.openapi()["paths"][path]["post"]
    query_flags = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "query"
    }
    sdk_params = set(inspect.signature(getattr(RegistryClient, sdk_method)).parameters)
    assert query_flags <= sdk_params, f"SDK cannot send {sorted(query_flags - sdk_params)}"

    command = next(
        info.callback
        for info in client_cli.app.registered_commands
        if (info.name or info.callback.__name__.replace("_", "-")) == cli_command
    )
    cli_params = set(inspect.signature(command).parameters)
    # The CLI spells `declared_use` as `--use`, matching `just-dna-enricher`; everything else is 1:1.
    assert query_flags - {"declared_use"} <= cli_params, (
        f"CLI cannot send {sorted(query_flags - {'declared_use'} - cli_params)}"
    )


# ── The post-publish repair verbs must all be reachable without Python (S9) ───


def _cli_commands() -> set[str]:
    return {
        info.name or info.callback.__name__.replace("_", "-")
        for info in client_cli.app.registered_commands
    }


def test_every_amend_is_reachable_from_the_cli() -> None:
    """The amends are the only way to repair a published version, so a Python-less author needs all
    of them. `amend_readme` shipped in 0.14.0 with no command while `amend-changelog` and
    `amend-logo` both had one, which left exactly one repair — the card prose, the field a module
    uses to say what it is *not* — unreachable from a shell (S9).

    Discovered off `RegistryClient` rather than listed, so a fourth amend fails this on the day it is
    added instead of on the day a consumer reports it."""
    amends = {name for name in dir(RegistryClient) if name.startswith("amend_")}
    assert amends >= {"amend_changelog", "amend_logo", "amend_readme"}  # discovery still works
    commands = _cli_commands()
    missing = sorted(m for m in amends if m.replace("_", "-") not in commands)
    assert missing == [], f"no `registry-client` command for {missing}"


def _cli_bound_to(app, api_key: str, monkeypatch) -> None:
    """Point `registry-client`'s client factory at an in-process app, ignoring --url/--token."""
    transport = TestClient(app)._transport
    monkeypatch.setattr(
        client_cli,
        "_client",
        lambda url, token, need_token=False: RegistryClient(
            "http://testserver", token=api_key, transport=transport, check_version=False
        ),
    )


async def test_cli_amend_readme_sets_the_card_from_a_file(app, api_key, seed, tmp_path, monkeypatch):
    """The command driven end to end against the real routes — the reproduction for S9."""
    _seed_module(seed)
    _cli_bound_to(app, api_key, monkeypatch)
    prose = "# Coronary\n\nCandidate findings only; not a diagnosis.\n"
    readme = tmp_path / "README.md"
    readme.write_text(prose)

    await asyncio.to_thread(
        client_cli.amend_readme, _NS, _NAME, _VER, readme, clear=False, url=None, token=None
    )

    tc = TestClient(app)
    assert tc.get(f"/api/v1/modules/{_NS}/{_NAME}").json()["readme"] == prose


async def test_cli_amend_readme_reads_stdin_and_refuses_an_empty_file(
    app, api_key, seed, tmp_path, monkeypatch
):
    """`-` is how the CLI answers the client method's path-*or*-string shape; an empty file is
    refused because a blank card is the failure the amend exists to repair, not a plausible edit."""
    _seed_module(seed)
    _cli_bound_to(app, api_key, monkeypatch)
    piped = "Candidates only. The PMID 29165669 association was NOT significant.\n"
    monkeypatch.setattr(client_cli.sys, "stdin", io.StringIO(piped))

    await asyncio.to_thread(
        client_cli.amend_readme, _NS, _NAME, _VER, Path("-"), clear=False, url=None, token=None
    )
    tc = TestClient(app)
    assert tc.get(f"/api/v1/modules/{_NS}/{_NAME}").json()["readme"] == piped

    blank = tmp_path / "README.md"
    blank.write_text("   \n")
    with pytest.raises(typer.BadParameter):
        await asyncio.to_thread(
            client_cli.amend_readme, _NS, _NAME, _VER, blank, clear=False, url=None, token=None
        )
    # …and the prose that was there is still there.
    assert tc.get(f"/api/v1/modules/{_NS}/{_NAME}").json()["readme"] == piped

    await asyncio.to_thread(
        client_cli.amend_readme, _NS, _NAME, _VER, None, clear=True, url=None, token=None
    )
    assert tc.get(f"/api/v1/modules/{_NS}/{_NAME}").json()["readme"] == ""


# ── The delete verb: always on the client, only served by a polygon ────────────


def test_the_client_always_offers_delete_and_names_the_limitation() -> None:
    """The SDK is mode-free by design: the methods exist unconditionally.

    A client cannot know what mode a host runs in until it asks, and gating the methods on a guess would
    mean a `RegistryClient` that silently lacks a verb depending on where it was pointed. So both methods
    are always present and the *docstring* carries the limitation — which this asserts, because an
    undocumented `405` from a method that looks universal is the worst version of this.
    """
    for method in (RegistryClient.delete_version, RegistryClient.delete_module):
        doc = method.__doc__ or ""
        assert "Test instances only" in doc
        assert "405" in doc          # what production actually answers
        assert "yank" in doc.lower() # and what to use there instead


def test_delete_round_trips_against_a_polygon(tmp_path) -> None:
    """Driven through the real client against a real test-mode app, including the reason it exists:
    after a delete the same *data* is publishable again, not merely the same version number."""
    from just_dna_registry.api.app import create_app
    from just_dna_registry.config import Settings

    polygon = create_app(Settings(
        mode="test",
        db_path=tmp_path / "polygon.db",
        local_storage_dir=tmp_path / "artifacts",
        ensembl_cache=tmp_path / "empty",
        clinvar_cache=tmp_path / "empty",
        constraint_cache=tmp_path / "empty",
    ))
    repo = polygon.state.repo
    account = repo.create_account("antonkulaga")
    repo.add_namespace("test-sandbox", account)
    repo.add_api_key("mk_live_testkey", account)

    tc = TestClient(polygon)
    with RegistryClient(
        "http://testserver", token="mk_live_testkey", transport=tc._transport, check_version=False
    ) as sdk:
        def _spec(module_name: str) -> Path:
            """A spec dir whose module name differs but whose authored rows are byte-identical.

            `content_signature` is name-independent by design, so these two specs share a content claim —
            which is what makes the last assertion in this test mean something."""
            d = tmp_path / f"spec-{module_name}"
            d.mkdir()
            (d / "module_spec.yaml").write_text(
                f"schema_version: \"1.0\"\nmodule:\n  name: {module_name}\n  title: B\n"
                f"  report_title: B\n  description: A burner module for the delete round trip.\n"
                f"genome_build: GRCh38\n"
            )
            (d / "variants.csv").write_text(
                "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
                "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
            )
            (d / "studies.csv").write_text(
                "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"
            )
            return d

        spec = _spec("burner")
        sdk.publish("test-sandbox", "burner", "1.0.0", spec)
        assert [v["version"] for v in sdk.versions("test-sandbox", "burner")["items"]] == ["1.0.0"]

        assert sdk.delete_version("test-sandbox", "burner", "1.0.0") is None
        # The version number is free again, and so is the content claim under a new name.
        sdk.publish("test-sandbox", "burner", "1.0.0", spec)
        sdk.delete_module("test-sandbox", "burner")
        assert repo.get_module_row("test-sandbox", "burner") is None
        sdk.publish("test-sandbox", "reused", "1.0.0", _spec("reused"))  # same data, no 409


# ── Spec layout: `derived/` in, `derived/` out, one module either way ──────────


async def test_a_derived_subfolder_publishes_as_the_flat_spec(sdk, tmp_path) -> None:
    """The uploader flattens, so a legible tree and a compiler-shaped one are the same module.

    `content_signature` is the assertion that matters: it is what `409 duplicate_content` gates on,
    and none of the files that may sit in `derived/` is in `SIGNATURE_INPUTS` — which is exactly why
    the folder is safe to offer at all.
    """
    (tmp_path / "flat").mkdir()
    flat = _write_spec(tmp_path / "flat", name="layout")
    (flat / "sources.csv").write_text("source,layer\nensembl,resolution\n")

    (tmp_path / "split").mkdir()
    split = _write_spec(tmp_path / "split", name="layout")
    (split / "derived").mkdir()
    (split / "derived" / "sources.csv").write_text("source,layer\nensembl,resolution\n")

    flat_signature = await asyncio.to_thread(lambda: sdk.content_signature(flat))
    published = await asyncio.to_thread(lambda: sdk.publish(_NS, "layout", _VER, split))
    assert published.content_signature == flat_signature
    assert {e.name for e in published.inputs} == {
        "module_spec.yaml", "variants.csv", "studies.csv"
    }, "the hoisted table has to reach the root the manifest names"


async def test_download_split_separates_the_machine_written_tables(sdk, tmp_path) -> None:
    """`layout="split"` is applied after verification, never before.

    The manifest attests flat names, so a tree split first is a tree that fails to verify — and
    `download` verifies unconditionally. Asserted by the fact that this call returns at all.
    """
    spec = _write_spec(tmp_path, name="split_dl")
    await asyncio.to_thread(lambda: sdk.publish(_NS, "split_dl", _VER, spec))

    dest = tmp_path / "dl"
    await asyncio.to_thread(
        lambda: sdk.download(_NS, "split_dl", _VER, dest, include_inputs=True, layout="split")
    )
    # A bare download is the compiled parquets and nothing else — `/download` lists `artifact.files`
    # only — so `include_inputs` is what puts an authored set on disk for the split to be about.
    assert (dest / "module_spec.yaml").is_file() and (dest / "variants.csv").is_file()
    assert (dest / "weights.parquet").is_file()
    assert (dest / "manifest.json").is_file()

    bare = tmp_path / "bare"
    await asyncio.to_thread(lambda: sdk.download(_NS, "split_dl", _VER, bare))
    assert not (bare / "variants.csv").exists(), "unchanged default: artifact only"

    with pytest.raises(ValueError, match="layout must be"):
        await asyncio.to_thread(
            lambda: sdk.download(_NS, "split_dl", _VER, dest, layout="derived")
        )


def test_split_and_flatten_are_inverses(tmp_path) -> None:
    """The round-trip, at the level where both halves are actually visible today.

    A downloader receives no derived CSV yet (the manifest attests none of them — filed upstream), so
    this drives `split_derived` over a tree that has them and checks that the uploader's own planner
    puts every one back exactly where it came from. If the two ever disagree, a downloaded module
    stops being republishable.
    """
    module_dir = tmp_path / "module"
    module_dir.mkdir()
    for name in ("module_spec.yaml", "variants.csv", "studies.csv", *DERIVED_FILES):
        (module_dir / name).write_text("x\n")
    (module_dir / "logs").mkdir()
    (module_dir / "logs" / "reviewer.log").write_text("reviewed\n")

    assert set(split_derived(module_dir)) == set(DERIVED_FILES)
    assert not (module_dir / "resolution.csv").exists()
    assert (module_dir / DERIVED_DIR / "resolution.csv").is_file()

    uploaded = dict(gather_spec_files(module_dir))
    assert "derived/WHERE-THIS-CAME-FROM.md" not in uploaded, "our note is not the author's file"

    plan = plan_layout(uploaded)
    assert plan.conflicts == []
    assert {src: dest for src, dest in plan.renames.items()} == {
        f"{DERIVED_DIR}/{name}": name for name in DERIVED_FILES
    }
    assert "logs/reviewer.log" not in plan.renames, "the one subtree the manifest attests by path"


async def test_the_fact_table_filters_are_reachable_from_the_sdk(sdk, client, api_key) -> None:
    """SDK↔API parity for the 0.17 filters, which the route table cannot catch.

    `_WRAPPED_ROUTES` pairs every *route* with a client method, and it stays green here because
    `/modules` gained no new route — only five new query parameters. That is the drift this test
    exists for: `list_modules` names every filter explicitly rather than sweeping `**kwargs`,
    precisely because the server ignores a parameter it does not know, so a filter the client
    forgot to forward comes back as a *wider* result set that looks like a working search.

    Driven through the real client against the real app, so a typo in either spelling fails.
    """
    yaml = (
        'schema_version: "1.0"\n'
        "module:\n  name: weighted\n  title: W\n  description: d\n  report_title: R\n"
        "genome_build: GRCh38\n"
        'weighting:\n  scale: "0-1, curator-set"\n'
    )
    variants = (
        "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
        "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
    )
    studies = (
        "rsid,pmid,population,p_value,conclusion,study_design\n"
        "rs4244285,[PMID: 29165669],T,0.05,E,U\n"
    )
    resp = client.post(
        f"/api/v1/modules/{_NS}/weighted/versions",
        data={"version": _VER},
        files=[
            ("files", ("module_spec.yaml", yaml.encode(), "text/yaml")),
            ("files", ("variants.csv", variants.encode(), "text/csv")),
            ("files", ("studies.csv", studies.encode(), "text/csv")),
        ],
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text

    async def names(**filters) -> set[str]:
        page = await asyncio.to_thread(lambda: sdk.list_modules(**filters))
        return {item["name"] for item in page["items"]}

    assert "weighted" in await names()
    assert await names(weighting_declared=True) == {"weighted"}
    assert "weighted" not in await names(weighting_declared=False)
    # A module with no GWAS sidecar must not answer the positive filter — the failure mode of a
    # dropped parameter is the filter silently matching everything.
    assert await names(has_gwas_effects=True) == set()
    assert "weighted" in await names(has_gwas_effects=False)

    detail = await asyncio.to_thread(lambda: sdk.get_module(_NS, "weighted"))
    assert detail["weighting"]["scale"] == "0-1, curator-set"
    assert detail["facts"]["weighting_declared"] is True
    assert detail["verification"] is not None and detail["verification"]["closed"] is False
