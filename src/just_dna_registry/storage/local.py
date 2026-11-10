"""
Local filesystem storage backend (dev/test).

Lays out a version's files under `<root>/<key>/<name>` where `key` is `{namespace}/{name}/{version}`
and `name` may be a nested path (e.g. `logs/reviewer.log`). Has no external URL, so the API serves
file bytes itself via the files endpoint.
"""

import shutil
from collections.abc import Mapping
from pathlib import Path


class LocalStorage:
    """Version-scoped store rooted at a local directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, key: str) -> Path:
        return self.root / key

    def store_module(self, key: str, files: Mapping[str, bytes]) -> None:
        target = self._dir(key)
        for name, data in files.items():
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)  # handles nested names (logs/…)
            dest.write_bytes(data)

    def exists(self, key: str, name: str) -> bool:
        return (self._dir(key) / name).is_file()

    def read_file(self, key: str, name: str) -> bytes:
        return (self._dir(key) / name).read_bytes()

    def file_url(self, key: str, name: str) -> str | None:
        # Local backend has no external URL; the API streams the bytes instead.
        return None

    def copy_module(self, src: str, dst: str, overrides: Mapping[str, bytes]) -> int:
        names = sorted({*self.list_files(src), *overrides})
        for name in names:
            dest = self._dir(dst) / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if name in overrides:
                dest.write_bytes(overrides[name])
            else:
                shutil.copyfile(self._dir(src) / name, dest)
        return len(names)

    def remove(self, key: str) -> None:
        shutil.rmtree(self._dir(key), ignore_errors=True)

    def list_files(self, key: str) -> list[str]:
        base = self._dir(key)
        if not base.is_dir():
            return []
        return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())

    def remove_file(self, key: str, name: str) -> None:
        path = self._dir(key) / name
        path.unlink(missing_ok=True)
        # An emptied directory is a remnant a revert must not leave: prune up to the storage root.
        parent = path.parent
        while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
