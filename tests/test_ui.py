"""The console (0.23): served pages, not routes.

Three guards, each for a way this page could drift without anything else failing:

* it is served where the docs say (`/ui/`, with `/` and `/ui` redirecting there), and gone when the
  flag is off, so a deployment can opt out and a reader of `/openapi.json` never sees it;
* **every API path the page names is a route the server actually serves**. The SDK has
  `test_every_route_is_wrapped_by_a_client_method`; this is the same idea one consumer over. A
  path the page fetches that the server does not serve is a panel that renders "nothing here"
  forever, which is the failure that looks most like working. The page is TypeScript under
  `console/src/`, bundled into `static/app.js` and committed; the contract tests read the
  *sources*, a freshness test proves the committed bundle is built from them (when Node is on the
  box), and a types test proves `types.ts` names the same fields as `models/api.py`;
* the standalone proxy relays what the API needs and nothing it should not: the bearer, the
  multipart body, the registry's version headers, a streamed body, and an injected token.
"""

import gzip
import json
import re
import shutil
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn
from conftest import seed_into
from fastapi.testclient import TestClient

from just_dna_registry import __version__
from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.groups import GroupInfo
from just_dna_registry.models import api as api_models
from just_dna_registry.ui import standalone
from just_dna_registry.ui.assets import ASSET_NAMES, STATIC_DIR, index_html

CONSOLE_DIR = Path(__file__).resolve().parent.parent / "console"
CONSOLE_SRC = CONSOLE_DIR / "src"


def _source(name: str) -> str:
    return (CONSOLE_SRC / name).read_text(encoding="utf-8")


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(CONSOLE_SRC.glob("*.ts"))}

# ── the mount ────────────────────────────────────────────────────────────────────────────────────


def test_the_console_is_served_at_ui_and_the_root_redirects_there(client: TestClient) -> None:
    for entry in ("/", "/ui"):
        resp = client.get(entry, follow_redirects=False)
        assert resp.status_code == 307, entry
        assert resp.headers["location"] == "/ui/"
    page = client.get("/ui/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    body = page.text
    # The version is stamped into the asset URLs so a redeploy is a cache miss by construction.
    for name in ASSET_NAMES:
        assert f'"static/{name}?v={__version__}"' in body, name
        asset = client.get(f"/ui/static/{name}?v={__version__}")
        assert asset.status_code == 200, name
        assert asset.content == (STATIC_DIR / name).read_bytes()


def test_only_the_named_assets_are_served(client: TestClient) -> None:
    """The asset route takes a name, not a path: nothing under `static/` that is not ours resolves,
    and nothing outside it ever could."""
    assert client.get("/ui/static/index.html").status_code == 404
    assert client.get("/ui/static/..%2F__init__.py").status_code == 404
    assert client.get("/ui/static/nope.js").status_code == 404


def test_the_flag_turns_the_whole_surface_off(tmp_path: Path) -> None:
    app = create_app(Settings(
        db_path=tmp_path / "r.db", local_storage_dir=tmp_path / "a", ui_enabled=False,
    ))
    with TestClient(app) as c:
        assert c.get("/", follow_redirects=False).status_code == 404
        assert c.get("/ui/").status_code == 404
        assert c.get("/ui/static/app.js").status_code == 404
        # And the API underneath is untouched.
        assert c.get("/health").status_code == 200


def test_the_console_adds_nothing_to_the_openapi_schema(app) -> None:
    """The SDK parity guard enumerates the schema; a page in it would demand a client method for a
    thing that is not an API. `/docs` is the precedent: served, and not a route."""
    paths = app.openapi()["paths"]
    assert not [p for p in paths if p == "/" or p.startswith("/ui")]


# ── the page ↔ API contract ───────────────────────────────────────────────────────────────────────

_ROUTES_BLOCK = re.compile(r"export const ROUTES = \{(.*?)\n\} as const;", re.DOTALL)
_ROUTE_LINE = re.compile(r'^\s*(\w+):\s*"([^"]+)",?\s*$', re.MULTILINE)


def _script_routes() -> dict[str, str]:
    block = _ROUTES_BLOCK.search(_source("api.ts"))
    assert block, "api.ts must keep its API paths in one `export const ROUTES = {…} as const;` table"
    routes = dict(_ROUTE_LINE.findall(block.group(1)))
    assert routes, "the ROUTES table parsed empty"
    return routes


def _served_paths(app) -> set[str]:
    # `{file_path:path}` is spelled `{file_path}` in the schema, which is what the page uses.
    return set(app.openapi()["paths"])


def test_every_path_the_page_fetches_is_a_served_route(app, tmp_path: Path) -> None:
    """Both modes, like the SDK guard: the delete verb only exists on the polygon and the page
    renders it only when `/health` says `test`, but the path it would call still has to be real."""
    polygon = create_app(Settings(
        mode="test", db_path=tmp_path / "p.db", local_storage_dir=tmp_path / "p-art",
    ))
    served = _served_paths(app) | _served_paths(polygon)
    routes = _script_routes()
    unknown = {k: v for k, v in routes.items() if v not in served}
    assert not unknown, f"the page names paths the server does not serve: {unknown}"


def test_the_page_names_no_path_outside_its_routes_table() -> None:
    """A path written inline is a path the guard above cannot see. Every literal `/api/v1/…` in the
    sources has to be inside the ROUTES table in `api.ts` — and the bundle is built from exactly
    those sources, so the same holds of what ships."""
    for name, text in _sources().items():
        if name == "api.ts":
            text = text.replace(_ROUTES_BLOCK.search(text).group(0), "")
        stray = re.findall(r'["`\']/api/v1/[^"`\']*["`\']', text)
        assert not stray, f"{name}: API paths outside the ROUTES table: {stray}"


def test_the_route_params_are_the_servers_names(app) -> None:
    """`{namespace}`, `{name}`, `{version}`, `{reviewer}`, `{member}`, `{file_path}` — the page
    fills templates by name, so a renamed path parameter has to be renamed in both places."""
    served = _served_paths(app)
    for key, template in _script_routes().items():
        if template in served:
            continue
        # Not served in prod mode (the delete verbs); the previous test covers the union.
        assert key in ("module", "version"), key


def test_the_cache_renderer_keeps_the_three_states_apart() -> None:
    """The same rule one field over: "not provisioned" is several states with different remedies.

    A lane that is `partial` needs the directory moved aside — provisioning refuses to overwrite it,
    since it never deletes — and a lane whose `licence_skip` is set will never arrive from a pull
    however often one is run. A page that renders all three as one red cross tells an operator to do
    the one thing that cannot work, which is the terminal renderer's `✓ would publish` over an outage
    wearing different clothes.
    """
    script = _source("caches.ts")
    for field in (
        "partial", "absent", "present",
        "licence_skip", "route_reason", "release_unreadable", "build_command",
        "enricher_available", "read_here", "configured", "parents",
    ):
        assert re.search(rf"\b{field}\b", script), f"the cache renderer no longer reads `{field}`"


def test_the_check_renderer_reads_every_unchecked_sibling() -> None:
    """The renderer's half of the standing rule: a count whose absence could mean either "nothing
    was wrong" or "nothing was checked" is rendered beside the field that says which. These are
    the sibling fields the CLI renders (`client_cli._UNREACHABLE_PASSES` and friends); if the page
    stops reading one, an outage renders as a clean run in a browser exactly as it once did in a
    terminal."""
    script = _source("reports.ts")
    for field in (
        "unreachable", "unreachable_rsids", "clin_sig_not_checked", "gene_loci_not_checked",
        "quotes_unchecked", "titles_as_quotes", "skipped_offline", "skipped_reason",
        "format_version", "format_advisory",
    ):
        assert re.search(rf"\b{field}\b", script), f"the check renderer no longer reads `{field}`"


def test_the_markdown_renderer_escapes_before_it_renders() -> None:
    """Readmes, changelogs and review notes are publisher content. The renderer's first act on a
    line has to be escaping; a raw `<script>` in a readme must never reach `innerHTML`."""
    markdown = _source("markdown.ts")
    inline = re.search(r"export function inlineMd\(s: string\): string \{\n(.*?)\n\}", markdown, re.DOTALL).group(1)
    assert inline.strip().startswith("let t = esc(s);")
    # Links only to http(s) and fragments: a `javascript:` href would be an escaped string
    # rendered as a live attribute.
    for name, text in _sources().items():
        assert "javascript:" not in text, name
    assert re.search(r"\\\]\\\(\(https\?:", markdown), "link targets are constrained to http(s)"
    # Funding, avatar and logo URLs from the server pass a scheme gate before reaching an attribute.
    assert re.search(r"httpUrl\(m\.author_funding_url\)", _source("module.ts"))
    assert re.search(r"httpUrl\(m\.org_funding_url\)", _source("module.ts"))
    assert re.search(r"httpUrl\(me\.avatar_url\)", _source("account.ts"))
    assert re.search(r"servedUrl\(card\.logo_url\)", _source("catalog.ts"))


# ── types.ts ↔ models/api.py ──────────────────────────────────────────────────────────────────────

_INTERFACE = re.compile(r"export interface (\w+)(?: extends (\w+))? \{(.*?)\n\}", re.DOTALL)
_FIELD = re.compile(r"^\s+(\w+)\??:", re.MULTILINE)


def _ts_interfaces() -> dict[str, tuple[str | None, set[str]]]:
    return {
        name: (parent or None, set(_FIELD.findall(body)))
        for name, parent, body in _INTERFACE.findall(_source("types.ts"))
    }


def _ts_fields(name: str, interfaces: dict[str, tuple[str | None, set[str]]]) -> set[str]:
    parent, fields = interfaces[name]
    return fields | (_ts_fields(parent, interfaces) if parent else set())


def test_the_page_types_name_the_same_fields_as_the_response_models() -> None:
    """`types.ts` is hand-kept and mirrors `models/api.py` field for field. A field the server adds
    is a field the page cannot render until this fails; a field the server drops is a render of
    `undefined` nothing would report. Names, not types — the annotation mapping is a reading of the
    same source, and a wrong type shows up in `tsc`, which the freshness test runs behind."""
    interfaces = _ts_interfaces()
    checked = 0
    for name, (_, _) in interfaces.items():
        model = getattr(api_models, name, None) if name != "GroupInfo" else GroupInfo
        if model is None or not hasattr(model, "model_fields"):
            continue  # a page-only shape (Page, HealthBody, …): nothing to mirror
        assert _ts_fields(name, interfaces) == set(model.model_fields), name
        checked += 1
    # Every model the page reads is here; a loop over zero interfaces would pass vacuously.
    assert checked >= 30, checked


# ── the committed bundle is built from the sources ────────────────────────────────────────────────


def test_the_committed_bundle_is_built_from_the_sources() -> None:
    """`static/app.js` is what ships and `console/src` is what is edited; the two drift the moment
    someone forgets `npm run build`. esbuild is deterministic for a pinned version, so a byte
    comparison is the test. Skips without a Node toolchain rather than failing — the source-based
    guards above still hold there — which is also why a `console/src` change with no `app.js`
    diff in the same commit is a stale bundle, however green the suite looked."""
    esbuild = CONSOLE_DIR / "node_modules" / ".bin" / "esbuild"
    node = shutil.which("node")
    if node is None or not esbuild.exists():
        pytest.skip("no Node toolchain: run `cd console && npm ci && npm run build` to verify the bundle")
    result = subprocess.run(
        [node, "build.mjs", "--check"], cwd=CONSOLE_DIR, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert (STATIC_DIR / "app.js").read_text(encoding="utf-8").startswith("/* Built from console/src")


def test_index_html_stamps_the_version_and_nothing_else() -> None:
    raw = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    stamped = index_html("9.9.9").decode()
    assert stamped.count("?v=9.9.9") == len(ASSET_NAMES)
    assert stamped.replace("?v=9.9.9", "") == raw


# ── the standalone proxy ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def live_registry(tmp_path: Path):
    """A real uvicorn server on a free port, with one key minted — the proxy needs a socket, not an
    ASGI app."""
    settings = Settings(db_path=tmp_path / "live.db", local_storage_dir=tmp_path / "live-art")
    app = create_app(settings)
    account_id = app.state.repo.create_account("proxy-tester")
    app.state.repo.add_api_key("mk_live_proxytest", account_id)
    app.state.repo.add_namespace("proxied", account_id)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def _proxy(upstream: str, token: str | None = None):
    server = standalone.ConsoleProxy(("127.0.0.1", 0), upstream=upstream, token=token, timeout=30)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _stop(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def test_the_proxy_serves_the_page_and_relays_the_api(live_registry, seed_into_live) -> None:
    _app, upstream = live_registry
    server, origin = _proxy(upstream)
    try:
        with httpx.Client(base_url=origin) as c:
            page = c.get("/")
            assert page.status_code == 200 and "just-dna" in page.text
            assert c.get("/static/app.js").content == (STATIC_DIR / "app.js").read_bytes()
            # Both entry paths work, and each finds its assets where the shell's relative URLs look.
            assert c.get("/ui/").status_code == 200
            assert c.get("/ui/static/app.css").content == (STATIC_DIR / "app.css").read_bytes()
            assert c.get("/static/../__init__.py").status_code == 404
            # JSON identical to the upstream's, version headers intact.
            direct = httpx.get(f"{upstream}/api/v1/modules").json()
            via = c.get("/api/v1/modules")
            assert via.status_code == 200
            assert via.json() == direct
            assert via.headers["x-registry-version"] == __version__
            assert c.get("/health").json()["status"] == "ok"
            assert c.get("/somewhere/else").status_code == 404
            # A bearer supplied by the browser reaches the API.
            who = c.get("/api/v1/auth/whoami", headers={"Authorization": "Bearer mk_live_proxytest"})
            assert who.status_code == 200 and who.json()["account"] == "proxy-tester"
            assert c.get("/api/v1/auth/whoami").status_code == 401
    finally:
        _stop(server)


def test_the_proxy_injects_a_token_only_where_the_browser_sent_none(live_registry) -> None:
    _app, upstream = live_registry
    server, origin = _proxy(upstream, token="mk_live_proxytest")
    try:
        with httpx.Client(base_url=origin) as c:
            assert c.get("/api/v1/auth/whoami").json()["account"] == "proxy-tester"
            # The browser's own header wins, even when it is wrong.
            assert c.get("/api/v1/auth/whoami", headers={"Authorization": "Bearer nope"}).status_code == 401
    finally:
        _stop(server)


def test_the_proxy_relays_multipart_bodies_and_structured_errors(live_registry) -> None:
    """A dry run through the proxy: the multipart boundary survives, and a `200` with `valid: false`
    comes back as exactly that — the proxy must not reinterpret a report as a failure."""
    _app, upstream = live_registry
    server, origin = _proxy(upstream, token="mk_live_proxytest")
    try:
        with httpx.Client(base_url=origin, timeout=60) as c:
            resp = c.post(
                "/api/v1/modules/proxied/broken/validate",
                files=[("files", ("module_spec.yaml", b"module:\n  name: broken\n", "text/plain"))],
            )
            assert resp.status_code == 200, resp.text
            report = resp.json()
            assert report["valid"] is False
            assert report["errors"]
            assert report["format_version"]
    finally:
        _stop(server)


def test_the_proxy_streams_a_tarball(live_registry, seed_into_live) -> None:
    _app, upstream = live_registry
    server, origin = _proxy(upstream)
    try:
        with httpx.Client(base_url=origin) as c:
            resp = c.get("/api/v1/modules/proxied/seeded/versions/1.0.0/download?format=tarball")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/gzip"
            direct = httpx.get(
                f"{upstream}/api/v1/modules/proxied/seeded/versions/1.0.0/download?format=tarball"
            ).content
            # The tar inside is deterministic; the gzip *header* carries the build time, so two
            # fetches straddling a second differ in four bytes. Compare what the archive holds.
            assert gzip.decompress(resp.content) == gzip.decompress(direct)
            assert "attachment" in resp.headers["content-disposition"]
    finally:
        _stop(server)


def test_an_unreachable_upstream_is_a_502_not_a_hang() -> None:
    server, origin = _proxy("http://127.0.0.1:9")  # discard port: nothing listens
    try:
        resp = httpx.get(f"{origin}/health", timeout=15)
        assert resp.status_code == 502
        assert resp.json()["detail"] == "upstream_unreachable"
    finally:
        _stop(server)


@pytest.fixture
def seed_into_live(live_registry):
    app, _ = live_registry
    return seed_into(app, "proxied", "seeded", "1.0.0", genes=["APOE"], categories=["longevity"])


def test_the_cli_refuses_a_token_on_a_non_loopback_host_unless_told_twice() -> None:
    from typer.testing import CliRunner

    from just_dna_registry.client_cli import app as cli

    result = CliRunner().invoke(cli, ["ui", "--host", "0.0.0.0", "--token", "mk_live_x", "--no-open"])
    assert result.exit_code != 0
    assert "--expose-token" in result.output


def test_the_console_docstring_and_assets_agree_on_the_files() -> None:
    assert {p.name for p in STATIC_DIR.iterdir()} == ASSET_NAMES | {"index.html"}
    json.loads(json.dumps(sorted(ASSET_NAMES)))  # the set is plain strings, serialisable for a listing
