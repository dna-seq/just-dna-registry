# Upstream ledger: fastapi

`fastapi/fastapi`, the service itself (the `server` extra). Releases are tags `X.Y.Z` with no prefix; notes in
`docs/en/docs/release-notes.md`. A busy upstream, watched by its tags only: `[seat.liaison.watch.fastapi]`, from a
clone outside the repository at `/data/sources/fastapi` (its line in the liaison state file). Kept by the liaison
seat (`docs/seats/LIAISON.md`).

## Read mark

**`0.141.1`**, what `uv.lock` installs (floor `fastapi>=0.139.0` in `pyproject.toml`), with `starlette` 1.7.0
under it. No release of fastapi has been read whole by this seat yet: the mark is the installed version, not a
reading.

## Backlog

`0.142.0` to `0.162.0` (latest on 2026-11-04), unread. FastAPI's `0.x` minors carry its breaking changes, so the
backlog is read minor by minor against the list below, oldest first, while the seat is idle. Next slice starts
at `0.142.0`.

## What the registry uses

From the imports under `src/` (an AST walk, 2026-11-04).

- `fastapi`: `FastAPI`, `APIRouter`, `Depends`, `Query`, `File`, `Form`, `Header`, `UploadFile`, `Request`,
  `Response`, `HTTPException`, `status`. The app (`api/app.py`, with a `lifespan`), `api/deps.py`, the routers
  under `api/routers/`, `ui/mount.py`.
- `fastapi.responses`: `FileResponse`, `JSONResponse`, `RedirectResponse`, `Response` (`api/routers/modules.py`,
  `ui/mount.py`).
- `starlette.concurrency.run_in_threadpool` (the caches, drafts, hints and publish routers): the offload of
  compile and enrichment work, which the concurrency gates around it depend on (CLAUDE.md, "Async").
- Behaviour, not symbols: `include_in_schema=False` on every console route and `app.openapi()` enumerated by
  `tests/test_client_sdk.py` and `tests/test_ui.py` (the SDK parity guard); FastAPI's `Depends`/`Query`/`File`
  defaults (ruff B008, exempted); `rate_limit(...)` dependencies resolving before the handler (CLAUDE.md, S23);
  multipart parsing through `python-multipart`; `fastapi.testclient.TestClient` in the tests, whose transport is
  `httpx2` since `huggingface-hub` 2.0 installs it (`tests/sdk_transport.py`).

## Verdicts

None yet.

## Our pieces the upstream may come to do

None recorded.

## Outbound

None.
