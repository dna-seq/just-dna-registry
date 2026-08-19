"""
FastAPI application factory.

Builds the app, opens the SQLite catalog, selects a storage backend, and mounts the routers under
`/api/v1`. `create_app(settings)` takes explicit settings so tests can point at a temp DB and a
local artifact dir.
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from just_dna_format.signing import public_key_b64_from_pem

from just_dna_registry import __version__
from just_dna_registry.api.routers import auth, modules, namespaces, orgs, publish, reviews
from just_dna_registry.config import API_PREFIX, Settings, get_settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.logging_setup import configure_logging
from just_dna_registry.ratelimit import default_limiter
from just_dna_registry.services.enrich import EnrichmentGate, close_lookup_clients
from just_dna_registry.startup import (
    export_enricher_credentials,
    validate_db_path,
    validate_enrichment_caches,
    validate_hf_access,
    warn_obsolete_env,
)
from just_dna_registry.storage.base import StorageBackend
from just_dna_registry.storage.local import LocalStorage
from just_dna_registry.version import VersionInfo

_request_log = logging.getLogger("registry.request")


def _build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir)
    if settings.storage_backend == "hf":
        from just_dna_registry.storage.hf import HfStorage  # imports huggingface_hub lazily

        return HfStorage(settings.hf_repo_id, token=settings.hf_token)
    raise ValueError(f"unsupported storage_backend {settings.storage_backend!r} (use 'local' or 'hf')")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    warn_obsolete_env()  # a stale .env key that no longer does anything must not pass in silence
    export_enricher_credentials(settings)  # keys, contact email, retry floor -> os.environ
    validate_hf_access(settings)  # exits(1) if hf backend + missing/read-only token; no-op for local
    validate_db_path(settings)  # exits(1) on the 0.9 rename orphan (legacy marketplace.db, no registry.db)
    validate_enrichment_caches(settings)  # warns (or exits) when offline enrichment has no snapshot

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        # Release the shared enricher HTTP clients. They hold connections open for the process's
        # lifetime by design — that is what keeps the outbound pacing honest across requests — so
        # they need closing explicitly rather than whenever the collector gets to them.
        close_lookup_clients()

    app = FastAPI(title="just-dna-registry", version=__version__, lifespan=lifespan)
    # Stamped at construction rather than at first request, and monotonic rather than wall-clock, so
    # `uptime_seconds` on `/health` survives an NTP step and cannot go backwards.
    started_monotonic = time.monotonic()

    conn = connect(settings.db_path)
    init_db(conn)
    app.state.settings = settings
    app.state.conn = conn
    app.state.repo = Repository(conn)
    app.state.storage = _build_storage(settings)
    app.state.rate_limiter = default_limiter(settings)
    # Process-wide cap on simultaneous enrichment runs, layered on top of the per-caller `enrich`
    # token bucket: the bucket bounds one caller, this bounds the server's outbound spend. It is also
    # what makes a single shared `LookupClients` safe, since the enricher's pacing gate is not
    # thread-safe. Two lanes: `/check` takes a permit or gets a `503`, publish queues for one and
    # defers to interactive demand — see `EnrichmentGate`.
    app.state.enrichment_gate = EnrichmentGate(
        settings.enrich_max_concurrency,
        quiet_seconds=settings.enrich_idle_quiet_seconds,
        poll_seconds=settings.enrich_idle_poll_seconds,
    )
    # `local()` reads installed package metadata, which cannot know the deployment mode — that is a
    # property of this process's settings, so it is stamped on here.
    server_versions = VersionInfo.local().model_copy(update={"mode": settings.mode})

    @app.middleware("http")
    async def _trace_requests(request: Request, call_next):
        """Trace each request (DEBUG), always log unhandled errors, and stamp the server's versions
        on every response so a client can guard against a contract mismatch without a round-trip."""
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _request_log.exception(
                "unhandled error: %s %s", request.method, request.url.path
            )
            raise
        response.headers["X-Registry-Version"] = server_versions.registry
        response.headers["X-Format-Version"] = server_versions.format or ""
        response.headers["X-API-Version"] = server_versions.api
        duration_ms = (time.perf_counter() - start) * 1000
        _request_log.debug(
            "%s %s%s -> %s (%.1fms)",
            request.method,
            request.url.path,
            f"?{request.url.query}" if request.url.query else "",
            response.status_code,
            duration_ms,
        )
        return response

    app.include_router(modules.router, prefix=API_PREFIX)
    app.include_router(reviews.router, prefix=API_PREFIX)
    app.include_router(publish.router, prefix=API_PREFIX)
    # The polygon's delete verb, and *only* there (0.12). Conditional mounting rather than a guard in
    # the handler: on production these paths do not exist, so a client holding a valid token cannot
    # delete published data even by accident — there is nothing listening to authorize.
    if settings.is_test_instance:
        app.include_router(publish.testops_router, prefix=API_PREFIX)
    app.include_router(namespaces.router, prefix=API_PREFIX)
    app.include_router(orgs.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        """Liveness, plus enough to run the box from without opening a shell (S4).

        `mode` is here as well as on `/api/v1/version` because this is the endpoint an operator or a
        proxy check curls, and it needs no token. A rehearsal that cannot observe which instance
        answered cannot prove it is not about to spend a version number on production (S3) — and
        with both deployments live, the two answered byte-identical payloads until this field.

        **A failing catalog degrades this response rather than failing it.** Liveness that 500s when
        the DB is unhappy tells a load balancer to pull a process that is still serving every read
        it has, and it withholds the diagnosis exactly when it is most wanted. So `status` becomes
        `degraded`, `catalog` becomes null, and the reason is named. This is the one place in this
        codebase where swallowing an exception is the point rather than a smell — the endpoint's job
        is to report, and an endpoint that reports by failing reports nothing.
        """
        body: dict = {
            "status": "ok",
            "version": __version__,
            "storage": settings.storage_backend,
            "mode": settings.mode,
            "uptime_seconds": round(time.monotonic() - started_monotonic, 1),
            "enrichment": app.state.enrichment_gate.occupancy(),
        }
        try:
            body["catalog"] = app.state.repo.catalog_counts()
        except Exception as exc:  # noqa: BLE001 — see the docstring; reporting beats propagating
            _request_log.warning("health: catalog counts unavailable: %s", exc)
            body["status"] = "degraded"
            body["catalog"] = None
            body["degraded_reason"] = f"catalog unavailable: {type(exc).__name__}"
        return body

    @app.get(f"{API_PREFIX}/version", tags=["ops"], response_model=VersionInfo)
    def version() -> VersionInfo:
        """The server's API + contract versions, for the client's compatibility guard. A client that
        gets a 404 here is talking to a pre-0.7.1 server (too old to report), and warns accordingly."""
        return server_versions

    @app.get(f"{API_PREFIX}/pubkey", tags=["ops"])
    def pubkey() -> dict:
        """The Ed25519 public key clients pin to verify signed manifests (SPEC §5). 404 when the
        server is not configured to sign."""
        if settings.signing_key is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="signing_not_configured")
        return {
            "algorithm": "ed25519",
            "public_key": public_key_b64_from_pem(settings.signing_key.read_bytes()),
        }

    return app


app = create_app()
