"""HfStorage path/URL construction (offline). Live commit/read is integration-tested separately
with a real token + public dataset repo (needs network/creds)."""

import sqlite3

from just_dna_registry.config import Settings
from just_dna_registry.maintenance import journaled, maintenance_run, revert_run
from just_dna_registry.storage.hf import HfStorage


def test_hf_paths_and_resolve_url() -> None:
    s = HfStorage("just-dna-seq/registry", token=None)
    key = "just-dna-seq/coronary/1.0.0"
    assert s._repo_path(key, "weights.parquet") == "data/just-dna-seq/coronary/1.0.0/weights.parquet"
    assert s._fs_path(key, "weights.parquet") == (
        "datasets/just-dna-seq/registry/data/just-dna-seq/coronary/1.0.0/weights.parquet"
    )
    assert s.file_url(key, "logs/reviewer.log") == (
        "https://huggingface.co/datasets/just-dna-seq/registry/resolve/main/"
        "data/just-dna-seq/coronary/1.0.0/logs/reviewer.log"
    )


def test_hf_backend_selected_by_config() -> None:
    # storage_backend=hf builds an HfStorage (no network at construction).
    from just_dna_registry.api.app import _build_storage
    from just_dna_registry.config import Settings

    storage = _build_storage(Settings(storage_backend="hf", hf_repo_id="org/repo"))
    assert isinstance(storage, HfStorage)
    assert storage.file_url("a/b/1.0.0", "weights.parquet").startswith(
        "https://huggingface.co/datasets/org/repo/resolve/main/"
    )


# ── list_files / remove_file and a journaled revert, over an in-memory hub (0.28.1) ─────────────────
#
# Not a mock of our code: `HfStorage` runs as written and only its two clients are replaced, by a fake
# hub that keeps one dataset repo as `{path_in_repo: bytes}` and answers the calls `HfStorage` makes, with
# the path spellings huggingface_hub uses (`datasets/<repo>/<path>` for the filesystem, `path_in_repo`
# for the API). So the path arithmetic of the two new methods, and a whole maintenance run reverted
# through them, are exercised without network or credentials.


class _FakeHub:
    def __init__(self, repo_id: str) -> None:
        self.repo_id = repo_id
        self.files: dict[str, bytes] = {}
        self.commits = 0

    def _in_repo(self, fs_path: str) -> str:
        prefix = f"datasets/{self.repo_id}/"
        assert fs_path.startswith(prefix), fs_path
        return fs_path[len(prefix):]

    # HfFileSystem
    def exists(self, path: str) -> bool:
        return self._in_repo(path) in self.files

    def cat_file(self, path: str) -> bytes:
        return self.files[self._in_repo(path)]

    def find(self, path: str, detail: bool = False) -> list[str]:
        base = self._in_repo(path).rstrip("/") + "/"
        found = [f"datasets/{self.repo_id}/{p}" for p in sorted(self.files) if p.startswith(base)]
        if not found:
            raise FileNotFoundError(path)
        return found

    # HfApi
    def create_commit(self, *, repo_id: str, operations, **_: object) -> None:
        assert repo_id == self.repo_id
        for op in operations:
            self.files[op.path_in_repo] = op.path_or_fileobj
        self.commits += 1

    def delete_folder(self, *, path_in_repo: str, repo_id: str, **_: object) -> None:
        assert repo_id == self.repo_id
        doomed = [p for p in self.files if p.startswith(path_in_repo.rstrip("/") + "/")]
        if not doomed:
            raise FileNotFoundError(path_in_repo)
        for p in doomed:
            del self.files[p]

    def delete_file(self, *, path_in_repo: str, repo_id: str, **_: object) -> None:
        assert repo_id == self.repo_id
        del self.files[path_in_repo]  # KeyError if absent: HfStorage must check first


def _hf(hub: _FakeHub) -> HfStorage:
    storage = HfStorage(hub.repo_id, token=None)
    storage._fs = hub  # type: ignore[assignment]
    storage._api = hub  # type: ignore[assignment]
    return storage


def test_list_files_is_relative_to_the_key_and_empty_when_absent() -> None:
    hub = _FakeHub("org/repo")
    storage = _hf(hub)
    storage.store_module("ns/m/1.0.0", {"manifest.json": b"m", "logs/x.log": b"l"})
    storage.store_module("ns/m/1.0.10", {"manifest.json": b"other"})  # a sibling whose name extends ours
    assert storage.list_files("ns/m/1.0.0") == ["logs/x.log", "manifest.json"]
    assert storage.list_files("ns/m") == ["1.0.0/logs/x.log", "1.0.0/manifest.json", "1.0.10/manifest.json"]
    assert storage.list_files("ns/absent/1.0.0") == []


def test_remove_file_deletes_one_and_an_absent_one_is_done() -> None:
    hub = _FakeHub("org/repo")
    storage = _hf(hub)
    storage.store_module("ns/m/1.0.0", {"manifest.json": b"m", "logs/x.log": b"l"})
    storage.remove_file("ns/m/1.0.0", "logs/x.log")
    assert set(hub.files) == {"data/ns/m/1.0.0/manifest.json"}
    storage.remove_file("ns/m/1.0.0", "logs/x.log")  # idempotent, no delete call on an absent file


def test_a_maintenance_run_over_hf_storage_reverts_to_the_byte(tmp_path) -> None:
    hub = _FakeHub("org/repo")
    storage = _hf(hub)
    storage.store_module("ns/kept/1.0.0", {"manifest.json": b"old", "data/a.parquet": b"A"})
    storage.store_module("ns/gone/1.0.0", {"manifest.json": b"bye", "logs/x.log": b"L"})
    before = dict(hub.files)
    db = tmp_path / "registry.db"
    sqlite3.connect(db).execute("CREATE TABLE t (k)").connection.commit()
    settings = Settings(db_path=db, run_dir=tmp_path / "runs")

    with maintenance_run(settings, "rename-account", "x") as run:
        live = journaled(storage)
        live.store_module("ns/kept/1.0.0", {"manifest.json": b"new"})
        live.store_module("ns/new/1.0.1", {"manifest.json": b"n", "data/b.parquet": b"B"})
        live.remove("ns/gone/1.0.0")
    assert hub.files != before

    with maintenance_run(settings, "revert-run", "x"):
        revert_run(settings, run.id, journaled(storage))
    assert hub.files == before
