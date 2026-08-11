"""
The 0.12 safety pair: rolling DB snapshots, and the test-data purge they guard.

Both are ops-only and destructive, so the tests are about the *refusals* as much as the actions — an
empty prefix matching everything, or a snapshot overwriting its predecessor, are the two mistakes here
that cannot be undone by the feature that exists to undo mistakes.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.backup import (
    create_backup,
    list_backups,
    next_index,
    restore_backup,
)
from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.services.purge import apply_purge, plan_purge

_AUTH = {"Authorization": "Bearer mk_live_testkey"}
_YAML = """\
schema_version: "1.0"
module:
  name: {name}
  title: A module
  report_title: A module
  description: Fixture module for the purge tests.
genome_build: GRCh38
"""
#: Weight is varied per module, because `duplicate_content` is keyed on the authored rows: two modules
#: sharing a fixture would 409 the second publish, which is the gate under test elsewhere in this file
#: and pure noise here.
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,{weight},risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _settings(tmp_path: Path, *, mode: str = "prod") -> Settings:
    empty = tmp_path / "no-cache"
    return Settings(
        mode=mode,
        db_path=tmp_path / "registry.db",
        local_storage_dir=tmp_path / "artifacts",
        ensembl_cache=empty,
        clinvar_cache=empty,
        constraint_cache=empty,
    )


def _parts(name: str, *, data: str = "") -> list:
    """Spec parts for `name`. `data` picks the *content* identity independently of the name, so a test
    can ask for "same module, different data" or "different module, same data" on purpose."""
    weight = f"-0.{abs(hash(data or name)) % 89 + 10}"
    return [
        ("files", ("module_spec.yaml", _YAML.format(name=name).encode(), "text/yaml")),
        ("files", ("variants.csv", _VARIANTS.format(weight=weight).encode(), "text/csv")),
        ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
    ]


# ── Snapshots ─────────────────────────────────────────────────────────────────


def test_the_index_counts_up_and_never_reuses_a_number(tmp_path: Path) -> None:
    """Taking a backup must be the one unambiguously safe act, so the sequence only ever grows.

    Not a ring buffer: after five snapshots the sixth is 6, not a recycled 1. The number is derived
    from the filenames rather than a counter, so a hand-copied or restored snapshot cannot make the
    next one collide with an existing file.
    """
    settings = _settings(tmp_path)
    init_db(connect(settings.db_path))

    made = [create_backup(settings, reason=f"step{i}") for i in range(1, 6)]
    assert all(p is not None for p in made)
    assert [p.name.split("-")[1] for p in made] == ["00001", "00002", "00003", "00004", "00005"]
    # Every snapshot still exists — nothing was rotated out from under the operator.
    assert all(p.is_file() for p in made)
    assert len(list_backups(settings)) == 5
    # Newest first, by index rather than mtime.
    assert list_backups(settings)[0] == made[-1]

    # Deleting a middle snapshot must not make the next write reuse its number.
    made[2].unlink()
    assert next_index(made[0].parent) == 6
    assert create_backup(settings, reason="after-gap").name.split("-")[1] == "00006"


def test_the_reason_is_in_the_filename(tmp_path: Path) -> None:
    """`ls` has to tell an operator what a snapshot was taken ahead of; a bare timestamp does not."""
    settings = _settings(tmp_path)
    init_db(connect(settings.db_path))
    assert "purge-test-data" in create_backup(settings, reason="purge-test-data").name
    # Path separators and spaces cannot escape the filename.
    assert "/" not in create_backup(settings, reason="a b/c").name.removeprefix("registry-")


def test_no_db_is_not_an_error(tmp_path: Path) -> None:
    """`init-db` and a first `reset-db` legitimately have nothing to snapshot; raising there would make
    the guard the thing that breaks a fresh install."""
    assert create_backup(_settings(tmp_path), reason="fresh") is None


def test_restore_round_trips_and_snapshots_what_it_replaces(tmp_path: Path) -> None:
    """Restoring the wrong file is the likeliest mistake in this module, so it is itself undoable."""
    settings = _settings(tmp_path)
    repo = Repository(connect(settings.db_path))
    init_db(repo.conn)
    account = repo.create_account("keeper")
    repo.add_namespace("just-dna-seq", account)
    snapshot = create_backup(settings, reason="before-wipe")

    repo.conn.execute("DELETE FROM namespaces")
    repo.conn.commit()
    assert repo.namespaces_for_account(account) == []
    repo.conn.close()

    restore_backup(settings, snapshot)
    restored = Repository(connect(settings.db_path))
    assert restored.namespaces_for_account(account) == ["just-dna-seq"]
    # The pre-restore state was itself captured, so restoring the wrong snapshot is recoverable.
    assert any("restore" in p.name for p in list_backups(settings))


# ── The purge ─────────────────────────────────────────────────────────────────


def _seeded(tmp_path: Path) -> tuple[TestClient, Repository, Settings]:
    """A catalog with test data and production data deliberately entangled.

    Seeded in **test** mode because a production instance now refuses a `test-` publish outright — but
    that guard is prospective only, and the catalog this command has to clean is full of data published
    before it existed (or on a box that was a polygon before it was promoted). So the fixture creates the
    data the way it really got there, and the purge runs against it afterwards regardless of mode.
    """
    settings = _settings(tmp_path, mode="test")
    client = TestClient(create_app(settings))
    repo = client.app.state.repo
    prod = repo.create_account("antonkulaga")
    tester = repo.create_account("test-runner")
    repo.add_namespace("just-dna-seq", prod)
    repo.add_namespace("test-sandbox", tester)
    repo.add_api_key("mk_live_testkey", prod)
    repo.add_api_key("mk_live_testerkey", tester)
    # Give the tester publish rights in the production namespace too — the entangling case.
    repo.add_member("just-dna-seq", tester, "member")
    return client, repo, settings


def test_a_test_namespace_goes_wholesale_and_production_is_untouched(tmp_path: Path) -> None:
    client, repo, settings = _seeded(tmp_path)
    for ns, name, auth in (
        ("test-sandbox", "burner", {"Authorization": "Bearer mk_live_testerkey"}),
        ("just-dna-seq", "coronary", _AUTH),
    ):
        r = client.post(f"/api/v1/modules/{ns}/{name}/versions",
                        data={"version": "1.0.0"}, files=_parts(name), headers=auth)
        assert r.status_code == 201, r.text

    plan = plan_purge(repo, prefix="test-")
    assert plan.namespaces == ["test-sandbox"]
    assert ("test-sandbox", "burner") in plan.modules
    assert not any(ns == "just-dna-seq" for ns, _ in plan.modules)
    assert [name for _id, name in plan.accounts] == ["test-runner"]

    apply_purge(repo, None, plan)
    assert repo.get_module_row("test-sandbox", "burner") is None
    assert repo.get_module_row("just-dna-seq", "coronary") is not None
    assert repo.account_by_name("test-runner") is None
    assert repo.account_by_name("antonkulaga") is not None


def test_a_prefixed_module_in_a_production_namespace_is_skipped_until_asked(tmp_path: Path) -> None:
    """The unrecoverable mistake this command could make, and the flag that gates it.

    `test_panel` under `just-dna-seq` may be a real published module with users. Its *name* matching is
    not consent to delete it.

    Spelled with an **underscore**, and that is a finding rather than a detail: a module name is
    validated `lowercase alphanumeric with underscores`, so `test-panel` is a `422` at publish and can
    never exist to be purged. A `--prefix test-` applied literally to module names would therefore match
    nothing, ever, and this whole gated case would be unreachable — which is why `plan_purge` normalises
    the prefix per identifier (`purge.module_name_prefix`).
    """
    client, repo, _settings = _seeded(tmp_path)
    r = client.post("/api/v1/modules/just-dna-seq/test_panel/versions",
                    data={"version": "1.0.0"}, files=_parts("test_panel"), headers=_AUTH)
    assert r.status_code == 201, r.text

    default = plan_purge(repo, prefix="test-")
    assert ("just-dna-seq", "test_panel") not in default.modules
    assert any(name == "test_panel" for _ns, name, _why in default.modules_in_prod)
    assert any("SKIPPED" in line for line in default.describe())

    opted_in = plan_purge(repo, prefix="test-", include_prod_namespaces=True)
    assert ("just-dna-seq", "test_panel") in opted_in.modules
    assert any("WOULD REMOVE" in line for line in opted_in.describe())

    apply_purge(repo, None, default)
    assert repo.get_module_row("just-dna-seq", "test_panel") is not None  # survived the default run


def test_an_empty_prefix_matches_nothing(tmp_path: Path) -> None:
    """The one bug that would make this command indistinguishable from `reset-db` on a live box."""
    client, repo, _settings = _seeded(tmp_path)
    client.post("/api/v1/modules/just-dna-seq/coronary/versions",
                data={"version": "1.0.0"}, files=_parts("coronary"), headers=_AUTH)
    for prefix in ("", "   ", None):
        plan = plan_purge(repo, prefix=prefix)
        assert plan.is_empty and not plan.modules_in_prod, f"{prefix!r} matched something"


def test_a_production_version_authored_by_a_purged_account_is_disowned_not_deleted(
    tmp_path: Path,
) -> None:
    """`versions.published_by` is a foreign key with no cascade, so this case decides the whole design:
    delete the module (catastrophic), fail the purge (a test account can never be removed), or keep the
    module and drop the pointer. The third, and it is reported rather than silent."""
    client, repo, _settings = _seeded(tmp_path)
    r = client.post("/api/v1/modules/just-dna-seq/coronary/versions",
                    data={"version": "1.0.0"}, files=_parts("coronary"),
                    headers={"Authorization": "Bearer mk_live_testerkey"})
    assert r.status_code == 201, r.text

    plan = plan_purge(repo, prefix="test-")
    assert ("just-dna-seq", "coronary", "1.0.0") in plan.disowned_versions
    assert any("disown" in line for line in plan.describe())

    apply_purge(repo, None, plan)
    assert repo.get_module_row("just-dna-seq", "coronary") is not None
    row = repo.conn.execute("SELECT published_by FROM versions").fetchone()
    assert row["published_by"] is None
    assert repo.account_by_name("test-runner") is None  # the FK no longer blocks the delete


def test_the_polygon_scopes_dedup_to_the_publisher(tmp_path: Path) -> None:
    """The one contract that differs by mode (0.12), asserted in both directions.

    A shared test box has several publishers rehearsing overlapping data, so another tester's rehearsal
    must not block yours. Your *own* is still refused — otherwise the gate would be untested until you
    met it on production for the first time, which is the failure the split exists to avoid.
    """
    client, repo, _settings = _seeded(tmp_path)  # mode="test"
    tester = {"Authorization": "Bearer mk_live_testerkey"}

    assert client.post("/api/v1/modules/test-sandbox/burner/versions",
                       data={"version": "1.0.0"}, files=_parts("burner", data="shared"),
                       headers=tester).status_code == 201

    # Same data, different account → allowed on the polygon.
    other = client.post("/api/v1/modules/just-dna-seq/coronary/versions",
                        data={"version": "1.0.0"}, files=_parts("coronary", data="shared"),
                        headers=_AUTH)
    assert other.status_code == 201, other.text

    # Same data, SAME account, different module → still refused, so the gate is still exercised.
    mine = client.post("/api/v1/modules/test-sandbox/burner_two/versions",
                       data={"version": "1.0.0"}, files=_parts("burner_two", data="shared"),
                       headers=tester)
    assert mine.status_code == 409
    assert mine.json()["detail"]["error"] == "duplicate_content"


def test_production_refuses_test_prefixed_data_but_only_prospectively(tmp_path: Path) -> None:
    """The prod guard, and the reason it does not make `purge-test-data` redundant.

    It refuses *new* test data. Everything already in the catalog — published before the guard, or while
    the box was still a polygon — is untouched by it, which is exactly the population the purge exists
    for. Modelled by seeding through a polygon app and then serving the same DB in production mode.
    """
    settings = _settings(tmp_path, mode="test")
    polygon = TestClient(create_app(settings))
    repo = polygon.app.state.repo
    tester = repo.create_account("test-runner")
    repo.add_namespace("test-sandbox", tester)
    repo.add_api_key("mk_live_testerkey", tester)
    assert polygon.post("/api/v1/modules/test-sandbox/burner/versions",
                        data={"version": "1.0.0"}, files=_parts("burner"),
                        headers={"Authorization": "Bearer mk_live_testerkey"}).status_code == 201

    prod = TestClient(create_app(_settings(tmp_path, mode="prod")))
    refused = prod.post("/api/v1/modules/test-sandbox/burner/versions",
                        data={"version": "2.0.0"}, files=_parts("burner", data="v2"),
                        headers={"Authorization": "Bearer mk_live_testerkey"})
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "test_data_on_prod"

    # ...and the pre-existing version is still right there, which is the point.
    assert prod.app.state.repo.get_module_row("test-sandbox", "burner") is not None
    assert not plan_purge(prod.app.state.repo, prefix="test-").is_empty


def test_purging_frees_the_content_signature_that_was_blocking_a_real_publish(tmp_path: Path) -> None:
    """The reason this command exists, end to end, on a production instance.

    `duplicate_content` is keyed on a name-independent signature and does **not** exempt yanked rows, so
    data rehearsed under another name makes the real publish a permanent `409`. Purging is what clears
    it — the yank step in the middle is the one an operator would expect to work and which does not.

    Seeded through a polygon app (production would refuse the `test-` namespace outright) and then
    attempted against the same DB in production mode, where dedup considers every account.
    """
    settings = _settings(tmp_path, mode="test")
    polygon = TestClient(create_app(settings))
    repo = polygon.app.state.repo
    prod_acct = repo.create_account("antonkulaga")
    tester = repo.create_account("test-runner")
    repo.add_namespace("just-dna-seq", prod_acct)
    repo.add_namespace("test-sandbox", tester)
    repo.add_api_key("mk_live_testkey", prod_acct)
    repo.add_api_key("mk_live_testerkey", tester)
    sandbox = {"Authorization": "Bearer mk_live_testerkey"}

    assert polygon.post("/api/v1/modules/test-sandbox/coronary/versions",
                        data={"version": "1.0.0"}, files=_parts("coronary", data="shared"),
                        headers=sandbox).status_code == 201

    prod = TestClient(create_app(_settings(tmp_path, mode="prod")))
    blocked = prod.post("/api/v1/modules/just-dna-seq/coronary/versions",
                        data={"version": "1.0.0"}, files=_parts("coronary", data="shared"),
                        headers=_AUTH)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "duplicate_content"

    # Yanking is not enough — the gate ignores `yanked`.
    polygon.post("/api/v1/modules/test-sandbox/coronary/versions/1.0.0/yank", headers=sandbox)
    still = prod.post("/api/v1/modules/just-dna-seq/coronary/versions",
                      data={"version": "1.0.0"}, files=_parts("coronary", data="shared"),
                      headers=_AUTH)
    assert still.status_code == 409

    apply_purge(prod.app.state.repo, None, plan_purge(prod.app.state.repo, prefix="test-"))
    freed = prod.post("/api/v1/modules/just-dna-seq/coronary/versions",
                      data={"version": "1.0.0"}, files=_parts("coronary", data="shared"),
                      headers=_AUTH)
    assert freed.status_code == 201, freed.text
