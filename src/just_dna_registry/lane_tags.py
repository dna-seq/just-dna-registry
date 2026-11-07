"""How a snapshot lane's readers are rendered, on the box and from a client (0.28.5).

The readers themselves are assembled in `services/lane_readers.py`, which imports the server tier.
The rendering lives here, outside `services/`, because `registry-client caches` prints the same tag
from `GET /caches`' `readers` field, and `client_cli` may import nothing from `services/`.
"""

PUBLISH = "publish"
PROXY_PREFIX = "proxy: "


def reader_tag(readers: tuple[str, ...] | list[str], *, where: str = "here") -> str:
    """`[publish; check: resolution; proxy: derived, hints, drafts]`, or `[nothing here]`."""
    if not readers:
        return f"[nothing {where}]"
    proxy = [r.removeprefix(PROXY_PREFIX) for r in readers if r.startswith(PROXY_PREFIX)]
    rest = [r for r in readers if not r.startswith(PROXY_PREFIX)]
    parts = rest + ([f"proxy: {', '.join(proxy)}"] if proxy else [])
    return f"[{'; '.join(parts)}]"
