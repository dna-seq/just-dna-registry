"""Drive `RegistryClient` (an `httpx.Client`) against an in-process app through Starlette's TestClient.

**Why this exists rather than `transport=tc._transport`.** Starlette 1.7's TestClient imports `httpx2`
whenever it can, and `huggingface-hub` 2.0 (the `server` extra) installs it, so the transport a
TestClient carries is an `httpx2.BaseTransport` returning `httpx2` streams. Handed to the SDK's
`httpx.Client` it fails `assert isinstance(response.stream, SyncByteStream)` on the first request.
That arrived with the 0.26.2 relock and broke every test lending the SDK a TestClient transport,
while production — a real socket, no TestClient — was never affected.

The adapter re-issues the request on the TestClient's own transport and carries the **raw** body
back, before any decoding, so `httpx` decodes it exactly once, as it would off a socket.
"""

import httpx
import httpx2
from fastapi.testclient import TestClient


class _HttpxOverTestClient(httpx.BaseTransport):
    def __init__(self, tc: TestClient) -> None:
        self._inner = tc._transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        inner = self._inner.handle_request(
            httpx2.Request(request.method, str(request.url), headers=request.headers.raw, content=body)
        )
        raw = b"".join(inner.stream)
        return httpx.Response(inner.status_code, headers=inner.headers.raw, content=raw, request=request)


def sdk_transport(tc: TestClient) -> httpx.BaseTransport:
    """The transport to hand `RegistryClient(transport=…)` for an in-process app."""
    return _HttpxOverTestClient(tc)
