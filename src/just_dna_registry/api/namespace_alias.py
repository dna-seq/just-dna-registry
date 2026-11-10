"""Requests addressed to a renamed namespace land on its current name (0.29).

A namespace that renamed keeps its old name as an alias (`namespace_aliases`), and every route that
names a namespace has it as the first path segment after `/api/v1/modules/` or `/api/v1/namespaces/`.
So the alias is resolved once, here, by rewriting that segment before routing, and no router learns
about it: a read, a publish, a yank or a member change sent to the old name acts on the new one. The
response carries `X-Namespace-Current` naming it, so a client can update what it stored.

Two exceptions. `/modules/lookup` and `/modules/groups` are routes of their own, so those exact paths
are never looked up (a namespace may still be *named* `lookup`, and `/modules/lookup/x` resolves).
And a `DELETE` is never rewritten: a hard delete or a member removal acts on the name the caller typed,
so one addressed to an old name finds nothing, and the CLI's removals refuse an old name the same way.
A query filter and a claim resolve through `Repository.resolve_namespace` where they are read.
"""

from urllib.parse import quote, unquote

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from just_dna_registry.config import API_PREFIX
from just_dna_registry.models.api import ALIAS_HEADER

#: The path prefixes whose next segment is a namespace.
PREFIXES: tuple[str, ...] = (f"{API_PREFIX}/modules/", f"{API_PREFIX}/namespaces/")
#: Paths under those prefixes that are routes of their own, matched whole.
NOT_NAMESPACES: frozenset[str] = frozenset({f"{API_PREFIX}/modules/lookup", f"{API_PREFIX}/modules/groups"})


def split_namespace(path: str) -> tuple[str, str, str] | None:
    """`(prefix, namespace, rest)` for a path whose first segment after a prefix names a namespace."""
    if path.rstrip("/") in NOT_NAMESPACES:
        return None
    for prefix in PREFIXES:
        if path.startswith(prefix):
            segment, slash, rest = path[len(prefix):].partition("/")
            if segment:
                return prefix, segment, slash + rest
    return None


class NamespaceAliasMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        found = (
            split_namespace(scope["path"])
            if scope["type"] == "http" and scope["method"] != "DELETE" else None
        )
        if found is None:
            await self.app(scope, receive, send)
            return
        prefix, segment, rest = found
        asked = unquote(segment)
        current = scope["app"].state.repo.resolve_namespace(asked)
        if current == asked:
            await self.app(scope, receive, send)
            return
        path = f"{prefix}{current}{rest}"
        scope = {**scope, "path": path, "raw_path": quote(path).encode("ascii")}

        async def stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((ALIAS_HEADER.lower().encode("latin-1"), current.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, stamped)
