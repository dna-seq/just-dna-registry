"""
The 0.11 content-signature re-derivation sweep.

0.10 keyed dedup on a Merkle root over the manifest's `inputs[]` file hashes, minus
`module_spec.yaml`. 0.5 moved the idea into the compiler as a hash of the *parsed rows*, with
`defaults:` folded in and the declared build mixed in. The two disagree, and one of the
disagreements is a live bug being fixed rather than a value merely moving:

**RM37.** Under the old algorithm, two modules whose only difference was `defaults.curator` hashed
*equal*, because the difference lives in `module_spec.yaml` — the one file the old signature
excluded. So a genuinely distinct module could be refused as a duplicate of something it was not.
`test_defaults_only_difference_no_longer_collides` pins that.

The sweep's job is to move the corpus across without either losing the gate or lying about it, and to
say out loud which collisions changed.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.services.signatures import (
    apply_rederivation,
    collision_report,
    plan_rederivation,
    rederive_version_signature,
)

_AUTH = {"Authorization": "Bearer mk_live_testkey"}

_YAML = """\
schema_version: "1.0"
module:
  name: {name}
  title: T
  description: d
  report_title: R
defaults:
  curator: {curator}
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _app(tmp_path: Path) -> TestClient:
    empty = tmp_path / "no-cache"
    client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "m.db",
                local_storage_dir=tmp_path / "a",
                ensembl_cache=empty,
                clinvar_cache=empty,
                constraint_cache=empty,
            )
        )
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    return client


def _publish(client: TestClient, name: str, curator: str = "ai-module-creator") -> dict:
    resp = client.post(
        f"/api/v1/modules/just-dna-seq/{name}/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", ("module_spec.yaml", _YAML.format(name=name, curator=curator).encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers=_AUTH,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_defaults_only_difference_no_longer_collides(tmp_path: Path) -> None:
    """The RM37 false positive, gone.

    Both modules carry byte-identical `variants.csv` and `studies.csv` and differ only in
    `defaults.curator`. Under the old manifest-inputs hash they were indistinguishable, so the second
    publish would have been refused as `duplicate_content`. It now succeeds, with its own signature.
    """
    client = _app(tmp_path)
    alpha = _publish(client, "alpha", curator="curator-a")
    beta = _publish(client, "beta", curator="curator-b")  # would have been 409 under 0.10
    assert alpha["content_signature"] != beta["content_signature"]


def test_identical_data_still_collides(tmp_path: Path) -> None:
    """The gate must still do its job — the fix is a sharper signature, not a weaker one."""
    client = _app(tmp_path)
    _publish(client, "alpha", curator="same")
    dup = client.post(
        "/api/v1/modules/just-dna-seq/rebranded/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", ("module_spec.yaml", _YAML.format(name="rebranded", curator="same").encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers=_AUTH,
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["error"] == "duplicate_content"


def test_rederivation_fills_an_unmigrated_corpus(tmp_path: Path) -> None:
    """A pre-0.5 corpus carries empty signatures; the sweep reads the CSVs back and fills them in."""
    client = _app(tmp_path)
    _publish(client, "alpha", curator="a")
    _publish(client, "beta", curator="b")
    repo, storage = client.app.state.repo, client.app.state.storage

    repo.conn.execute("UPDATE versions SET content_hash = ''")  # simulate the pre-0.5 state
    repo.conn.commit()

    changes = plan_rederivation(repo, storage)
    assert {c.bucket for c in changes} == {"derived"}
    assert all(c.new and c.new.startswith("sha256:") for c in changes)

    assert apply_rederivation(repo, changes) == 2
    stored = {r["content_hash"] for r in repo.conn.execute("SELECT content_hash FROM versions")}
    assert stored == {c.new for c in changes}


def test_rederivation_is_idempotent(tmp_path: Path) -> None:
    """Re-running must be a no-op, or an operator cannot safely repeat an interrupted sweep."""
    client = _app(tmp_path)
    _publish(client, "alpha")
    repo, storage = client.app.state.repo, client.app.state.storage

    changes = plan_rederivation(repo, storage)
    assert {c.bucket for c in changes} == {"unchanged"}
    assert apply_rederivation(repo, changes) == 0


def test_a_version_with_no_stored_spec_is_skipped_not_failed(tmp_path: Path) -> None:
    """A legacy parquet-only import has nothing to re-derive from. It keeps its old value and drops
    out of the gate — reported, and an accepted cost rather than an error."""
    client = _app(tmp_path)
    _publish(client, "alpha")
    storage = client.app.state.storage
    from just_dna_registry.storage.base import version_key

    key = version_key("just-dna-seq", "alpha", "1.0.0")
    (Path(storage.root) / key / "module_spec.yaml").unlink()

    signature, error = rederive_version_signature(storage, "just-dna-seq", "alpha", "1.0.0")
    assert signature is None
    assert "module_spec.yaml" in (error or "")

    changes = plan_rederivation(client.app.state.repo, storage)
    assert [c.bucket for c in changes] == ["skipped"]


def test_collisions_are_reported_by_module_not_by_version(tmp_path: Path) -> None:
    """Two versions of the *same* module sharing a signature is normal (unchanged data, new version)
    and must not be reported as a merge."""
    client = _app(tmp_path)
    _publish(client, "alpha")
    client.post(
        "/api/v1/modules/just-dna-seq/alpha/versions",
        data={"version": "1.0.1"},
        files=[
            ("files", ("module_spec.yaml", _YAML.format(name="alpha", curator="ai-module-creator").encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers=_AUTH,
    )
    changes = plan_rederivation(client.app.state.repo, client.app.state.storage)
    splits, merges = collision_report(changes)
    assert splits == [] and merges == []
