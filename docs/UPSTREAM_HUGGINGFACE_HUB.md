# Upstream ledger: huggingface-hub

`huggingface/huggingface_hub`, the storage backend modules are published to (CLAUDE.md, "HuggingFace / fsspec
access"; the `server` extra). Releases are tags `vX.Y.Z`; notes on the GitHub releases page. A busy upstream,
watched by its tags only: `[seat.liaison.watch.huggingface-hub]`, from a clone outside the repository at
`/data/sources/huggingface_hub` (its line in the liaison state file). Kept by the liaison seat
(`docs/seats/LIAISON.md`).

## Read mark

**`v2.0.0`**, what `uv.lock` installs. The floor in `pyproject.toml` is still `huggingface-hub>=0.34.0`, which
admits 0.x, 1.x and 2.x alike: the 2.0 major came in by a relock (registry 0.26.2), not a decision. No release
has been read whole by this seat yet: the mark is the installed version, not a reading.

## Backlog

- **The 2.0 major, read first.** It is installed, so what it changed is in production already; what it
  broke surfaced only in the tests (H1). Read its notes against the list below.
- `v2.1.0` to `v2.4.0` (latest on 2026-11-04), then, oldest first.

## What the registry uses

From the imports under `src/` (an AST walk, 2026-11-04). Small, on purpose: the backend is meant to stay
swappable.

- `HfApi`: `create_commit(repo_id, repo_type="dataset", operations, commit_message, revision)` and
  `delete_folder(path_in_repo, repo_id, repo_type, revision)` in `storage/hf.py`; `create_repo(...,
  repo_type="dataset", exist_ok=True)` as the write-access probe in `startup.py:174`.
- `CommitOperationAdd(path_in_repo, path_or_fileobj=bytes)`, imported from the package root (1.32.0 stopped
  re-exporting it from `huggingface_hub.hf_api`; CLAUDE.md).
- `HfFileSystem` (fsspec): `exists`, `cat_file` over `datasets/{repo}/{path}`. Never `snapshot_download`.
- The `resolve` URL shape `https://huggingface.co/datasets/{repo}/resolve/{revision}/{path}`, built by hand in
  `storage/hf.py` (`file_url`) and pinned by `tests/test_hf_storage.py`: downloads are a `302` to it.
- The token, read the way the library reads it (`HF_TOKEN`; `tests/test_startup.py`).

## Verdicts

- **H1 — 2.0 installs `httpx2`, and Starlette's TestClient prefers it.** Recorded, already handled: the SDK
  tests drive the client through `tests/sdk_transport.py` since 0.26.2. Production was never affected (a real
  socket). Nothing owed.

## Our pieces the upstream may come to do

None recorded.

## Outbound

None.
