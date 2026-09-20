"""`registry-client ui`: the console served from a laptop, against any registry.

The page can only talk to its own origin — the server sets no CORS policy, on purpose — so pointing
a locally served page at `module-registry.just-dna.life` needs something in between. This is that
something: a stdlib `ThreadingHTTPServer` that serves the console's three files and forwards
`/api/…`, `/health`, `/docs` and `/openapi.json` to the upstream registry over `httpx` (a base
dependency, so this runs on the client-only install with nothing added).

What is forwarded is deliberately narrow: the request method, path and query, the body bytes, and
the handful of headers the API reads (`Authorization`, `Content-Type` with its multipart boundary,
`Accept`, `X-Format-Version`). Responses come back with their status, body and the registry's own
version headers, streamed rather than buffered so a tarball download does not sit in memory.

`--token` injects a bearer for requests that carry none, so the browser never has to hold the key.
That makes the listening socket as powerful as the key: it binds to loopback by default and the
CLI refuses to combine a token with a non-loopback host unless told twice.
"""

import logging
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from just_dna_registry import __version__
from just_dna_registry.ui.assets import asset_media_type, asset_path, index_html

log = logging.getLogger("registry.ui")

#: Path prefixes handed to the upstream registry. Everything else is local or a 404.
PROXIED_PREFIXES: tuple[str, ...] = ("/api/", "/health", "/docs", "/openapi.json")
#: Request headers the API reads. Hop-by-hop and browser-only headers (cookies, origin, host) stop here.
FORWARDED_REQUEST_HEADERS: frozenset[str] = frozenset(
    {"authorization", "content-type", "accept", "x-format-version", "x-registry-version"}
)
#: Response headers passed back to the browser. `content-length` is handled explicitly.
FORWARDED_RESPONSE_HEADERS: frozenset[str] = frozenset(
    {
        "content-type", "content-disposition", "location", "retry-after", "cache-control",
        "x-registry-version", "x-format-version", "x-api-version",
        # Which bucket a `429 rate_limited` came from (0.26). Added with the header, because a
        # whitelist that lags the API by one field is a page saying "rate limited" and nothing else.
        "x-ratelimit-bucket",
    }
)
_CHUNK = 64 * 1024


class ConsoleProxy(ThreadingHTTPServer):
    """The server, carrying what every handler needs: the upstream and one shared HTTP client."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, upstream: str, token: str | None, timeout: float) -> None:
        super().__init__(address, ConsoleHandler)
        self.upstream = upstream.rstrip("/")
        self.token = token
        # One client for the process: connection reuse, and a place for a timeout that is long enough
        # for a publish (minutes) without hanging a dead upstream forever.
        self.client = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0), follow_redirects=False)
        self.index = index_html(__version__)

    def server_close(self) -> None:
        self.client.close()
        super().server_close()


class ConsoleHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: ConsoleProxy  # narrowed for the attributes above

    # ── dispatch ────────────────────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802 — http.server's naming
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch()

    def _dispatch(self) -> None:
        path = urlsplit(self.path).path
        if path in ("/", "/index.html", "/ui", "/ui/"):
            self._send_bytes(self.server.index, "text/html; charset=utf-8", cache="no-cache")
        elif path.startswith(("/static/", "/ui/static/")):
            # Both entry paths resolve their assets: the shell references `static/…` relatively,
            # so `/ui/` asks for `/ui/static/…` and `/` for `/static/…`.
            self._send_asset(path.rsplit("/static/", 1)[1])
        elif path.startswith(PROXIED_PREFIXES):
            self._proxy()
        else:
            self._send_bytes(b'{"detail":"not_found"}', "application/json", status=HTTPStatus.NOT_FOUND)

    # ── local files ─────────────────────────────────────────────────────────────────────────────
    def _send_asset(self, name: str) -> None:
        path: Path | None = asset_path(name)
        if path is None:
            self._send_bytes(b'{"detail":"asset_not_found"}', "application/json", status=HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(path.read_bytes(), asset_media_type(path), cache="public, max-age=86400")

    def _send_bytes(self, body: bytes, media_type: str, *, status: HTTPStatus = HTTPStatus.OK, cache: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ── the proxy ───────────────────────────────────────────────────────────────────────────────
    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() in FORWARDED_REQUEST_HEADERS}
        if self.server.token and "authorization" not in {k.lower() for k in headers}:
            headers["Authorization"] = f"Bearer {self.server.token}"
        # Identity encoding, so an upstream `Content-Length` describes the bytes we relay.
        headers["Accept-Encoding"] = "identity"
        url = self.server.upstream + self.path
        try:
            request = self.server.client.build_request(self.command, url, headers=headers, content=body)
            upstream = self.server.client.send(request, stream=True)
        except httpx.HTTPError as exc:
            log.warning("upstream %s %s failed: %s", self.command, url, exc)
            self._send_bytes(
                b'{"detail":"upstream_unreachable","upstream":"' + self.server.upstream.encode() + b'"}',
                "application/json", status=HTTPStatus.BAD_GATEWAY,
            )
            return
        try:
            self.send_response(upstream.status_code)
            for key, value in upstream.headers.multi_items():
                if key.lower() in FORWARDED_RESPONSE_HEADERS:
                    self.send_header(key, value)
            content_length = upstream.headers.get("content-length")
            chunked = content_length is None
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", content_length)
            self.end_headers()
            if self.command == "HEAD":
                return
            for chunk in upstream.iter_raw(_CHUNK):
                if chunked:
                    self.wfile.write(f"{len(chunk):x}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                else:
                    self.wfile.write(chunk)
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
        finally:
            upstream.close()

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("%s %s", self.address_string(), fmt % args)


def serve(
    *, upstream: str, host: str = "127.0.0.1", port: int = 8765, token: str | None = None,
    timeout: float = 600.0, open_browser: bool = False, announce: Callable[[str], None] | None = None,
) -> None:
    """Run the console proxy until interrupted. `announce` is called with the bound origin — after
    the bind, so `port=0` reports the port the kernel picked rather than the zero it was asked for."""
    server = ConsoleProxy((host, port), upstream=upstream, token=token, timeout=timeout)
    origin = f"http://{host}:{server.server_address[1]}/"
    log.info("console on %s -> %s", origin, upstream)
    if announce is not None:
        announce(origin)
    if open_browser:
        webbrowser.open(origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
