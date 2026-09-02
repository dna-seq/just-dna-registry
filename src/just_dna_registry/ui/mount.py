"""Mount the console on the FastAPI app at `/ui`.

Every handler here is `include_in_schema=False`. That is not cosmetic: `tests/test_client_sdk.py`
enumerates `app.openapi()` and fails on any served route without a `RegistryClient` method, and a
page is not an API route — `/docs` and `/openapi.json` are not in that table either. The console
*consumes* the API; it does not extend it.
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse, Response

from just_dna_registry import __version__
from just_dna_registry.config import Settings
from just_dna_registry.ui.assets import asset_media_type, asset_path, index_html

UI_PREFIX: str = "/ui"


def mount_ui(app: FastAPI, settings: Settings) -> None:
    """Serve the console at `/ui/` (and redirect `/` and `/ui` there) unless `ui_enabled` is off."""
    if not settings.ui_enabled:
        return

    index = index_html(__version__)

    @app.get("/", include_in_schema=False)
    @app.get(UI_PREFIX, include_in_schema=False)
    def ui_redirect() -> RedirectResponse:
        # The shell references its assets relatively (`static/app.js`), which only resolves under
        # the trailing-slash form, so the bare prefix redirects rather than serving a page whose
        # stylesheet 404s.
        return RedirectResponse(f"{UI_PREFIX}/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get(f"{UI_PREFIX}/", include_in_schema=False)
    def ui_index() -> Response:
        return Response(index, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})

    @app.get(f"{UI_PREFIX}/static/{{name}}", include_in_schema=False)
    def ui_asset(name: str) -> FileResponse:
        path = asset_path(name)
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="asset_not_found")
        # Versioned URLs (`?v=`) are safe to cache for a long time; the shell itself is not cached.
        return FileResponse(path, media_type=asset_media_type(path), headers={"Cache-Control": "public, max-age=86400"})
