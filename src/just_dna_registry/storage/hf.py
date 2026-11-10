"""
HuggingFace Hub dataset storage backend (SPEC §9 hybrid).

A module version's files live under `data/{namespace}/{name}/{version}/…` in the configured HF
dataset repo. Writes are a single commit; reads go through `HfFileSystem` (fsspec — never
`snapshot_download`, per project rules); `file_url` returns the HF `resolve` CDN URL so the API
`302`-redirects downloads to the CDN instead of proxying bytes.

Requires a write-capable token (validated at startup by `startup.validate_hf_access`) and a
**public** dataset repo so `resolve` URLs are fetchable without auth. Server-tier only.
"""

import contextlib
from collections.abc import Mapping

# `CommitOperationAdd` from the package root, never `huggingface_hub.hf_api`: 1.32.0 stopped
# re-exporting it there (it lives in `_commit_api`), and the root export has been stable since
# long before the `>=0.34.0` floor. The private module path was an implementation detail we
# happened to import, and a relock that swept 1.31 → 1.32 turned every server import into an
# `ImportError` at collection time.
from huggingface_hub import CommitOperationAdd, CommitOperationCopy, HfApi, HfFileSystem


class HfStorage:
    """Version-scoped store over an HF dataset repo."""

    def __init__(
        self, repo_id: str, token: str | None = None, *, prefix: str = "data", revision: str = "main"
    ) -> None:
        self.repo_id = repo_id
        self.prefix = prefix
        self.revision = revision
        self._api = HfApi(token=token)
        self._fs = HfFileSystem(token=token)

    def _repo_path(self, key: str, name: str) -> str:
        return f"{self.prefix}/{key}/{name}"

    def _fs_path(self, key: str, name: str) -> str:
        return f"datasets/{self.repo_id}/{self._repo_path(key, name)}"

    def store_module(self, key: str, files: Mapping[str, bytes]) -> None:
        operations = [
            CommitOperationAdd(path_in_repo=self._repo_path(key, name), path_or_fileobj=data)
            for name, data in files.items()
        ]
        self._api.create_commit(
            repo_id=self.repo_id,
            repo_type="dataset",
            operations=operations,
            commit_message=f"publish {key}",
            revision=self.revision,
        )

    def exists(self, key: str, name: str) -> bool:
        return self._fs.exists(self._fs_path(key, name))

    def read_file(self, key: str, name: str) -> bytes:
        return self._fs.cat_file(self._fs_path(key, name))

    def file_url(self, key: str, name: str) -> str | None:
        return (
            f"https://huggingface.co/datasets/{self.repo_id}/resolve/"
            f"{self.revision}/{self._repo_path(key, name)}"
        )

    def copy_module(self, src: str, dst: str, overrides: Mapping[str, bytes]) -> int:
        """One commit. The hub copies only LFS files server-side (`CommitOperationCopy`), which are the
        parquets that make a version large; every other file is read and re-added, as is each override."""
        names = self.list_files(src)
        lfs = {
            info.path for info in self._api.get_paths_info(
                self.repo_id, [self._repo_path(src, n) for n in names if n not in overrides],
                repo_type="dataset", revision=self.revision,
            )
            if getattr(info, "lfs", None) is not None
        } if names else set()
        operations: list[CommitOperationAdd | CommitOperationCopy] = []
        for name in sorted({*names, *overrides}):
            target = self._repo_path(dst, name)
            if name in overrides:
                operations.append(CommitOperationAdd(path_in_repo=target, path_or_fileobj=overrides[name]))
            elif self._repo_path(src, name) in lfs:
                operations.append(CommitOperationCopy(
                    src_path_in_repo=self._repo_path(src, name), path_in_repo=target,
                    src_revision=self.revision,
                ))
            else:
                operations.append(CommitOperationAdd(
                    path_in_repo=target, path_or_fileobj=self.read_file(src, name)
                ))
        self._api.create_commit(
            repo_id=self.repo_id, repo_type="dataset", operations=operations,
            commit_message=f"copy {src} to {dst}", revision=self.revision,
        )
        return len(operations)

    def remove(self, key: str) -> None:
        # Broad on purpose and unchanged in substance: removal is idempotent, so an already-absent
        # folder (or any other failure to delete one) is not worth propagating to the caller.
        with contextlib.suppress(Exception):
            self._api.delete_folder(
                path_in_repo=f"{self.prefix}/{key}",
                repo_id=self.repo_id,
                repo_type="dataset",
                revision=self.revision,
            )

    def list_files(self, key: str) -> list[str]:
        base = f"datasets/{self.repo_id}/{self.prefix}/{key}"
        try:
            found = self._fs.find(base, detail=False)
        except FileNotFoundError:
            return []
        return sorted(path[len(base) + 1 :] for path in found if path.startswith(base + "/"))

    def remove_file(self, key: str, name: str) -> None:
        # Unlike `remove`, not suppressed: a revert reads its result back, and an error it cannot see
        # would read as a file restored. An absent file is the one failure that means "done".
        if not self.exists(key, name):
            return
        self._api.delete_file(
            path_in_repo=self._repo_path(key, name),
            repo_id=self.repo_id,
            repo_type="dataset",
            revision=self.revision,
            commit_message=f"revert {key}/{name}",
        )
