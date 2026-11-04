# Upstream ledger: huggingface-hub

`huggingface/huggingface_hub`, the storage backend modules are published to (CLAUDE.md, "HuggingFace / fsspec
access"; the `server` extra). Releases are tags `vX.Y.Z`; notes on the GitHub releases page. A busy upstream,
watched by its tags only: `[seat.liaison.watch.huggingface-hub]`, from a clone outside the repository at
`/data/sources/huggingface_hub` (its line in the liaison state file). Kept by the liaison seat
(`docs/seats/LIAISON.md`).

## Read mark

**`v2.4.0`** read (2026-11-05, the release notes of 2.0.0 to 2.4.0 against the list below). Installed: `v2.0.0`
(`uv.lock`). The floor in `pyproject.toml` is still `huggingface-hub>=0.34.0`, which admits 0.x, 1.x and 2.x
alike: the 2.0 major came in by a relock (registry 0.26.2), not a decision. Nothing the registry calls was
removed or retyped in 2.0 to 2.4, so no cap is wanted.

## Backlog

None: read through `v2.4.0`.

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
- **H2 — 2.0 moved the HTTP stack to `httpx2`, so its logs come from the `httpx2` and `httpcore2` loggers.
  *Breaks us, quietly.*** `logging_setup.py:20` `_NOISY` pins `"httpx", "httpcore"` to WARNING and not the new
  two, so under `debug` every Hub request is logged again. Mechanical: add both names. Five minutes. Sent to the
  lead 2026-11-05; **built** the same night (015d3d0, with a test over every installed transport).
- **H3 — `httpx2` uses the operating system's certificate store by default** (`SSL_CERT_FILE`/`SSL_CERT_DIR` still
  honoured). Nothing for us unless a box relies on a CA bundle the system store lacks; none is configured in
  this repo.
- **H4 — `HfFileSystem` caches listings and "not found" answers for the life of the instance** (2.2.0 made
  `exists(path, refresh=True)` clear a cached miss). The server and the CLI each hold one `HfStorage` for their
  whole run (`api/app.py:59`, `cli.py:120`), and `exists` never passes `refresh`. No symptom seen: a version's
  key is written once and asked about only after, so a cached miss needs a delete and re-publish of one key in a
  running process (the polygon's delete verb) or a key asked about before another process wrote it. Watch, not a
  task; reproduce before filing.
- Read, nothing for us: 2.0's removed APIs (none of them called here); 2.1 `HfFileSystem.get_file` through
  `hf_xet` (we use `cat_file`), Jobs, Inference, Sandboxes; 2.2 jobs and download changes; 2.3 bucket
  `live_follow`, parallel listing, `create_commit` keeping a re-added file (we only add); 2.4 bucket copies, a
  clearer "repository not found".

## Our pieces the upstream may come to do

None recorded.

## Outbound

None.
