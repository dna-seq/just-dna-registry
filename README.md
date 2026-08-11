# just-dna-registry

A catalog / publish / download **REST API** for [just-dna-lite](../just-dna-lite) annotation
modules. Authors publish module specs; the server validates, recompiles, stores, and indexes them;
consumers browse, search, download, and integrity-verify. There is no frontend here — the webui and
Dagster pipelines are consumers of this API.

**Live:** <https://module-registry.just-dna.life> · health `GET /health` · API under `/api/v1`
· interactive docs at [`/docs`](https://module-registry.just-dna.life/docs).

**Two instances, one image** (0.12). Production is the catalog above. The **polygon**
(<https://module-polygon.just-dna.life>, `REGISTRY_MODE=test`) is where you rehearse a publish: it
accepts `test-`prefixed data and lets you *delete* it again, which production deliberately does not.

See [docs/SPEC.md](docs/SPEC.md) for the full design and [docs/ROADMAP.md](docs/ROADMAP.md) for
build status.

## Install

Two shapes from one package:

```bash
pip install just-dna-registry            # client only (lightweight): httpx + just-dna-format
pip install just-dna-registry[server]    # + FastAPI app, server-side recompile, storage, admin
```

The default install is the **reference client** — import it instead of re-implementing the REST
calls + integrity verification:

```python
from just_dna_registry import RegistryClient

with RegistryClient("https://module-registry.just-dna.life", token="mk_live_…") as mkt:
    print(mkt.list_modules())
    mkt.import_module("just-dna-seq", "coronary", "1.0.0", "coronary_v1.zip")   # publish a zip
    mkt.download("just-dna-seq", "coronary", "1.0.0", "./coronary")             # fetch + verify
    mkt.lookup_by_digest("sha256:…")                                            # already published?
```

Or the `registry-client` CLI (ships with the client install):

```bash
export REGISTRY_URL=https://module-registry.just-dna.life REGISTRY_TOKEN=mk_live_…
registry-client list
registry-client download just-dna-seq coronary 1.0.0 ./coronary
```

## Run the server (needs `[server]`)

```bash
uv sync                      # dev env (includes the server extra + tests)
uv run pytest -q
uv run registry issue-key <account> -n <namespace>   # mint an API key
uv run registry serve --host 0.0.0.0                 # port 8000 (prod) / 8100 (test), /docs for the API
```

### Modes: production vs the polygon

`REGISTRY_MODE` is `prod` (the default) or `test`. It is a **server** setting — the client never branches
on it. An unrecognised value refuses to boot rather than guessing, because a typo resolving to `test`
would arm a delete endpoint on production data.

| | production | polygon (`REGISTRY_MODE=test`) |
|---|---|---|
| default port | 8000 | 8100 |
| `test-`prefixed namespace / `test_`prefixed module | `422 test_data_on_prod` | accepted |
| `409 duplicate_content` | any account | scoped to the publishing account |
| `DELETE` a module or version | `405` — not mounted | served (bearer + namespace) |

**Why the polygon needs a delete verb.** A published version is immutable *and* its authored data is
claimed by a name-independent `content_hash` that **`yank` does not release**. So on one instance every
rehearsal permanently burns a version number and the right to publish that data under any other name —
which is why a "test subtree" inside production does not work, and why the polygon exists.

Give it its own DB and artifact storage. Never point it at production's.

### Ops: snapshots and cleanup

```bash
uv run registry backup --reason before-migration   # rolling index, never overwrites
uv run registry list-backups
uv run registry purge-test-data                    # dry run: prints exactly what would go
uv run registry purge-test-data --apply            # server stopped, please
```

Every destructive command (`reset-db`, `remove-*`, `purge-test-data`) snapshots the DB first. Snapshots
count up (`registry-00001-…`) and are never overwritten or rotated out, so they accumulate — prune them
deliberately. A snapshot is the **index, not the artifacts**.

## What works today

- **Read/catalog API** — list + search (`?q`, `?gene`, `?category`, `?genome_build`, `?owner`,
  `?license`, `?sort`), module detail, versions, manifest (SPEC §8.1–§8.4).
- **Publish** — multipart spec upload **or** zip/tar.gz archive import (incl. legacy parquet-only
  via reverse-engineering), server-side recompiled so `compile_success`/digest are trusted.
- **Download + integrity** — per-file + streamable tar.gz, verify-then-install via
  `just_dna_format.verify_manifest` (SPEC §5).
- **Pre-flight** — `POST .../validate` (offline) and `POST .../check` (the network tier), both taking a
  compressed spec archive; `would_publish` is the field CI branches on.
- **Logs** over the API; **digest lookup**; **auth** (static API keys) + namespace ownership;
  **yank / un-yank**; ops-only **hard removal** (`registry remove-namespace/-module`).
- **Modes + ops safety** (0.12) — production refuses test data, the polygon can delete it; rolling
  pre-flight DB snapshots and a dry-run-by-default `purge-test-data`.

## Architecture

The `manifest.json` of each version is the **source of truth**; the SQLite catalog is a rebuildable
projection of it. The manifest contract and integrity primitives live in the shared, dependency-light
[`just-dna-format`](../just-dna-format) package so this service and the compiler never drift.

```
src/just_dna_registry/
  config.py            # Pydantic settings (incl. REGISTRY_MODE)
  testdata.py          # what counts as test data, and what each mode does about it
  backup.py            # rolling DB snapshots taken before anything destructive
  db/                  # SQLite schema + repository (the projection)
  storage/             # StorageBackend interface + LocalStorage (HfStorage pending)
  models/api.py        # card / detail / version / page response models
  services/            # catalog (reads), ingest (manifest -> projection), enrich, purge
  api/                 # FastAPI app, deps (auth/pagination), routers
  cli.py               # `registry` admin CLI
```
