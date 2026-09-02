"""The console's static files, and the one substitution made into the HTML shell at serve time."""

import mimetypes
from pathlib import Path

STATIC_DIR: Path = Path(__file__).parent / "static"
INDEX_FILE: Path = STATIC_DIR / "index.html"

#: What the page fetches from its own origin. The mount and the standalone proxy both serve exactly
#: this set of local assets; everything else is either the API or a 404.
ASSET_NAMES: frozenset[str] = frozenset({"app.css", "app.js"})


def index_html(version: str) -> bytes:
    """The HTML shell with the registry version stamped into the asset URLs.

    Browsers cache `app.js` aggressively and a stale script against a new API is the kind of drift
    nothing reports — the page just renders less than it should. The query string changes on every
    release, so a redeploy is a cache miss by construction.
    """
    text = INDEX_FILE.read_text(encoding="utf-8")
    for name in sorted(ASSET_NAMES):
        text = text.replace(f'"static/{name}"', f'"static/{name}?v={version}"')
    return text.encode("utf-8")


def asset_path(name: str) -> Path | None:
    """Resolve a requested asset name, refusing anything that is not one of ours."""
    if name not in ASSET_NAMES:
        return None
    return STATIC_DIR / name


def asset_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"
