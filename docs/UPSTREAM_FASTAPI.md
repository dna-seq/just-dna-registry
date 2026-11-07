# Upstream ledger: fastapi

`fastapi/fastapi`, the service itself (the `server` extra). Releases are tags `X.Y.Z` with no prefix; notes in
`docs/en/docs/release-notes.md`. A busy upstream, watched by its tags only: `[seat.liaison.watch.fastapi]`, from a
clone outside the repository at `/data/sources/fastapi` (its line in the liaison state file). Kept by the liaison
seat (`docs/seats/LIAISON.md`).

## Read mark

**`0.162.1`** read (2026-11-07; 0.162.0 on 2026-11-05, the release notes from 0.142.0, against the list below). Installed: `0.162.0`
(`uv.lock`, the bump of 2026-11-05, `bb42dbd`; floor `fastapi>=0.139.0` in `pyproject.toml`), with `starlette` 1.10.0 under it.

## Backlog

None: read through `0.162.1`.

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

- **F1 — 0.147 to 0.162 rework how omitted and empty form values default, and the registry takes form fields on
  every upload route. *To measure at the first dependency bump, not a finding.*** The changes: an omitted boolean
  form field was made `False` (0.147) and its default handling restored (0.162); request-parameter defaults
  fixed (0.148); empty scalars in form *models* treated as missing (0.149); an unselected browser file input
  treated as missing (0.150); JSON `null` told apart from an omitted body value (0.151). Ours: individual
  `Form()` parameters, not form models, at `api/routers/publish.py:204-208` and `:277-286` (`allow_test_data:
  bool = False`, so an omitted one is `False` either way; `changelog: str = ""`; six `str | None = None`), and a
  body model whose `null` clears an override (`ShortDescriptionRequest`, `:772`), which pydantic parses the same
  either way. Reading finds no break. What reading cannot settle is whether an *empty* `title=` now arrives as
  `None` rather than `""`; the upload and publish tests answer that on the first `uv lock --upgrade`, which is
  the weekly bump's job.
  **Measured 2026-11-05** (`bb42dbd`): the full suite passes on 0.162.0 (612 passed), upload and publish tests
  included, and no warning from fastapi or starlette. Closed.
- Read, nothing for us: 0.162.1 (docs, translations, upstream's own CI pins; its "pytest below 9.2 for
  pytest-xdist" is their test rig, and we run no xdist); 0.143 OpenTelemetry exporter opt-in (we set none up), 0.145 `openapi_prefix` and 0.146
  `root_path` on `FastAPI(...)` (neither used), 0.155 `**extra` on request parameters (none passed), 0.160 a
  parameter model's `extra` (no parameter models here); the features and fixes of 0.152 to 0.161.

## Our pieces the upstream may come to do

None recorded.

## Outbound

None.
