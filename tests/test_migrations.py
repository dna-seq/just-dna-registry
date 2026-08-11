"""Additive schema migrations: `init_db` upgrades a pre-existing DB in place (idempotent)."""

from pathlib import Path

from just_dna_registry.db.schema import connect, init_db

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
