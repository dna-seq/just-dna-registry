"""Additive schema migrations: `init_db` upgrades a pre-existing DB in place (idempotent)."""

from pathlib import Path

from just_dna_registry.db.schema import _V017_COLUMNS, connect, init_db

# A minimal pre-0.5.0 `versions` table — no `needs_upgrade` column.
_OLD_SCHEMA = """
CREATE TABLE modules (id INTEGER PRIMARY KEY, namespace TEXT, name TEXT);
CREATE TABLE versions (
    id INTEGER PRIMARY KEY,
    module_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    compile_success INTEGER NOT NULL DEFAULT 0,
    yanked INTEGER NOT NULL DEFAULT 0,
    changelog TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
"""


def _cols(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_init_db_adds_needs_upgrade_to_old_db(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = connect(db)
    conn.executescript(_OLD_SCHEMA)
    conn.commit()
    assert "needs_upgrade" not in _cols(conn, "versions")

    init_db(conn)  # migrates in place
    assert "needs_upgrade" in _cols(conn, "versions")

    # Idempotent: running again is a no-op, and the audit query now resolves the column.
    init_db(conn)
    assert conn.execute("SELECT needs_upgrade FROM versions").fetchall() == []


def test_init_db_adds_0_6_counters(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = connect(db)
    conn.executescript(_OLD_SCHEMA)
    conn.commit()

    init_db(conn)  # migrates in place
    assert {"stars", "views", "search_hits", "created_at"} <= _cols(conn, "modules")
    assert "downloads" in _cols(conn, "versions")


# A pre-0.6 DB with a single-owner namespace but no membership table.
_PRE_MEMBERSHIP = """
CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE namespaces (name TEXT PRIMARY KEY, account_id INTEGER NOT NULL);
INSERT INTO accounts(id, name) VALUES (1, 'antonkulaga');
INSERT INTO namespaces(name, account_id) VALUES ('just-dna-seq', 1);
"""


def test_init_db_backfills_owner_membership(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = connect(db)
    conn.executescript(_PRE_MEMBERSHIP)
    conn.commit()

    init_db(conn)  # creates namespace_members + backfills the founding owner
    rows = conn.execute(
        "SELECT namespace, account_id, role FROM namespace_members"
    ).fetchall()
    assert [(r["namespace"], r["account_id"], r["role"]) for r in rows] == [
        ("just-dna-seq", 1, "owner")
    ]

    # Idempotent: re-running never duplicates the seeded membership.
    init_db(conn)
    assert len(conn.execute("SELECT * FROM namespace_members").fetchall()) == 1


def test_init_db_reprojects_trust_the_0_11_3_rule_changed(tmp_path: Path) -> None:
    """A stored `trusted` computed under the old rule is repaired in place, without a re-publish.

    The manifests are correct and immutable; only our reading of them moved, so a migration is the
    right instrument. `_migrate_0_11_facets` cannot do this — it backfills only when the columns are
    first added, which on any already-migrated DB has long since happened.

    Both populations are covered, because they need opposite verdicts: a module whose compiler warning
    says a table joins to nothing becomes `False`, while a variants-free module with no such warning
    becomes `NULL` — trust granted by a vacuous `all()` is withdrawn, not inverted into an accusation.
    """
    db = tmp_path / "catalog.db"
    conn = connect(db)
    init_db(conn)

    warned = _manifest_json(warnings=["haplotypes.csv: 106 of 106 row(s) have no chrom+start, so …"])
    quiet = _manifest_json(warnings=[])
    conn.execute("INSERT INTO modules(id, namespace, name, title) VALUES (1, 'just-dna-seq', 'm', 'M')")
    for vid, payload in ((1, warned), (2, quiet)):
        conn.execute(
            "INSERT INTO versions(id, module_id, version, digest, manifest_json, resolution_mode, "
            "fully_resolved, trusted) VALUES (?, 1, ?, 'sha256:x', ?, NULL, 1, 1)",
            (vid, f"1.0.{vid}", payload),
        )
    conn.commit()

    init_db(conn)  # re-runs _migrate
    verdicts = {
        r["id"]: r["trusted"]
        for r in conn.execute("SELECT id, trusted FROM versions").fetchall()
    }
    assert verdicts == {1: 0, 2: None}
    # `fully_resolved` is left exactly as the compiler stamped it — this reinterprets, never edits.
    assert [r["fully_resolved"] for r in conn.execute("SELECT fully_resolved FROM versions")] == [1, 1]

    # Idempotent, and self-limiting: a second pass matches no rows and changes nothing.
    init_db(conn)
    assert {
        r["id"]: r["trusted"]
        for r in conn.execute("SELECT id, trusted FROM versions").fetchall()
    } == verdicts


def _manifest_json(*, warnings: list[str]) -> str:
    """The smallest manifest `is_trusted` reads: a 0.5 witness, no `variants.csv`, given warnings."""
    from just_dna_format.manifest import ModuleManifest

    manifest = ModuleManifest.model_validate(
        {
            "identity": {"namespace": "just-dna-seq", "name": "m", "version": "1.0.0"},
            "display": {"title": "m", "description": "d", "report_title": "m"},
            "artifact": {"digest": "sha256:" + "0" * 64, "files": []},
            # Present => not `predates_resolution_contract`, so the 0.5 rule applies.
            "content_signature": "sha256:" + "0" * 64,
            "compilation": {
                "compile_success": True,
                "resolution_mode": None,      # no variants.csv
                "fully_resolved": True,       # ...so this is all() over nothing
                "warnings": warnings,
            },
        }
    )
    return manifest.model_dump_json()


def test_init_db_backfills_the_0_17_fact_columns_without_re_judging_anything(tmp_path: Path) -> None:
    """The 0.17 migration, and the two opposite defaults it has to get right on the same row.

    This is what an operator meets on upgrade day: a catalog full of pre-0.6 versions, migrated in
    place on the first `registry serve`. `docs/UPGRADE.md` § 0.17 promises it needs no command and
    re-judges nothing, so both halves are checked here rather than argued there.

    **The fact-table booleans backfill to `0`, and that is honest** — a manifest predating the block
    belongs to a module that carried no such table, because the table did not exist to be omitted.
    **The five counters backfill to `NULL`, and `0` would be a lie** — `positional_rows: 0` says "this
    module has no positional table", which about a PGx artifact compiled under 0.5 is false. Same
    migration, same row, opposite correct answers; the columns are declared to match.

    `trusted` is asserted untouched beside them, because the 0.17 rule change is the kind that
    *looks* like it needs a re-projection (0.11.3's did) and does not: the pre-0.6 branch is the 0.5
    rule unchanged, so a migration that moved a stored verdict here would be a bug.
    """
    db = tmp_path / "catalog.db"
    conn = connect(db)
    init_db(conn)

    conn.execute("INSERT INTO modules(id, namespace, name, title) VALUES (1, 'just-dna-seq', 'm', 'M')")
    conn.execute(
        "INSERT INTO versions(id, module_id, version, digest, manifest_json, resolution_mode, "
        "fully_resolved, trusted) VALUES (1, 1, '1.0.0', 'sha256:x', ?, 'strict', 1, 1)",
        (_manifest_json(warnings=[]),),
    )
    conn.commit()

    # Simulate a DB that predates 0.17 by dropping the columns the migration adds. The index goes
    # first — SQLite refuses to drop a column an index still names, and a real pre-0.17 DB has
    # neither.
    conn.execute("DROP INDEX IF EXISTS idx_versions_gwas_effects")
    for column, _decl in _V017_COLUMNS:
        conn.execute(f"ALTER TABLE versions DROP COLUMN {column}")
    conn.commit()
    assert not {c for c, _ in _V017_COLUMNS} & _cols(conn, "versions")

    init_db(conn)  # re-adds and backfills

    row = conn.execute("SELECT * FROM versions WHERE id = 1").fetchone()
    assert (
        row["has_gene_validity"],
        row["has_clinical_assertions"],
        row["has_gwas_effects"],
        row["has_frequencies"],
        row["weighting_declared"],
    ) == (0, 0, 0, 0, 0)
    for counter in (
        "resolution_subjects", "positional_rows", "positional_rows_placed",
        "expanded_keys", "expanded_rows",
    ):
        assert row[counter] is None, f"{counter} backfilled to {row[counter]!r}, not NULL"

    assert row["trusted"] == 1, "0.17 must not re-judge a stored verdict"

    init_db(conn)  # idempotent
    assert conn.execute("SELECT trusted FROM versions WHERE id = 1").fetchone()["trusted"] == 1
