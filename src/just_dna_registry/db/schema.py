"""
SQLite catalog schema and connection helper.

The DB is a *projection* of each version's `manifest.json` (the source of truth). Rows exist per
`(namespace, name, version)`, with denormalized module-level fields for the card grid and side
tables (`version_genes`, `version_categories`) for facet filters. SPEC §9.
"""

import logging
import sqlite3
from pathlib import Path

from just_dna_format.manifest import ModuleManifest

from just_dna_registry.db.facets import UNJOINABLE_PHRASE, is_trusted, version_facets

logger = logging.getLogger("registry.db")

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS accounts (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS api_keys (
    key        TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS namespaces (
    name        TEXT PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    featured    INTEGER NOT NULL DEFAULT 0,
    blacklisted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS modules (
    id             INTEGER PRIMARY KEY,
    namespace      TEXT NOT NULL,
    name           TEXT NOT NULL,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    icon           TEXT NOT NULL DEFAULT 'database',
    color          TEXT NOT NULL DEFAULT '#6435c9',
    genome_build   TEXT NOT NULL DEFAULT 'GRCh38',
    license        TEXT,
    owner          TEXT,
    readme         TEXT NOT NULL DEFAULT '',
    latest_version TEXT,
    downloads      INTEGER NOT NULL DEFAULT 0,
    stars          INTEGER NOT NULL DEFAULT 0,
    views          INTEGER NOT NULL DEFAULT 0,
    search_hits    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT '',
    UNIQUE(namespace, name)
);

CREATE TABLE IF NOT EXISTS versions (
    id              INTEGER PRIMARY KEY,
    module_id       INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    version         TEXT NOT NULL,
    digest          TEXT NOT NULL,
    content_hash    TEXT NOT NULL DEFAULT '',   -- name-independent data-input signature (dedup)
    manifest_json   TEXT NOT NULL,
    compile_success INTEGER NOT NULL DEFAULT 0,
    yanked          INTEGER NOT NULL DEFAULT 0,
    needs_upgrade   INTEGER NOT NULL DEFAULT 0,
    downloads       INTEGER NOT NULL DEFAULT 0,
    changelog       TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT '',
    published_by    INTEGER REFERENCES accounts(id),   -- authoring account (RBAC own-scoping + funding)
    UNIQUE(module_id, version)
);

CREATE TABLE IF NOT EXISTS version_genes (
    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    gene       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS version_categories (
    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    category   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS module_stars (
    module_id  INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    PRIMARY KEY (module_id, account_id)
);

CREATE TABLE IF NOT EXISTS namespace_members (
    namespace  TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    role       TEXT NOT NULL DEFAULT 'member',   -- owner|admin|member (0.9.0; was owner|contributor)
    PRIMARY KEY (namespace, account_id)
);

-- Org membership (0.9.0): a user's role in an org account (type='org'). Cascades to every namespace
-- the org owns. Effective namespace role = highest of {this cascade, an explicit namespace_members
-- grant}. `org_id` must be a type='org' account (app-enforced, matching the codebase's no-CHECK style).
CREATE TABLE IF NOT EXISTS org_members (
    org_id     INTEGER NOT NULL REFERENCES accounts(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    role       TEXT NOT NULL DEFAULT 'member',   -- owner|admin|member
    PRIMARY KEY (org_id, account_id)
);

-- Reviews/audits (0.8.0): registry-layer social data ABOUT a published version — never part of
-- the module manifest (that stays immutable/content-addressed). Anyone authenticated posts one per
-- (version, account); a namespace owner may `highlighted` the good ones (SO accepted-answer style),
-- which is what the `curated` listing group keys on. `verdict` is the optional audit tier.
CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id    INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    version      TEXT NOT NULL,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    rating       INTEGER NOT NULL,
    verdict      TEXT,
    notes        TEXT,
    highlighted  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT '',
    UNIQUE (module_id, version, account_id)
);

CREATE INDEX IF NOT EXISTS idx_versions_module ON versions(module_id);
CREATE INDEX IF NOT EXISTS idx_version_genes ON version_genes(gene);
CREATE INDEX IF NOT EXISTS idx_version_categories ON version_categories(category);
CREATE INDEX IF NOT EXISTS idx_namespace_members_account ON namespace_members(account_id);
CREATE INDEX IF NOT EXISTS idx_org_members_account ON org_members(account_id);
CREATE INDEX IF NOT EXISTS idx_reviews_module ON reviews(module_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with row access by name and foreign keys enabled."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")  # wait out brief write contention (threadpool publishes)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they do not exist, then run lightweight column migrations."""
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent, additive migrations for existing DBs (the live catalog has data)."""
    acct_cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "install_id" not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN install_id TEXT")
    # Account profile (0.8.0): `email` (private contact/identity, not yet an auth factor),
    # `display_name` (human name, distinct from the `name` handle), and a GitHub-style `type`
    # discriminator (`user`|`org`) so a single identity primitive can be a person or an organization.
    if "email" not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN email TEXT")
    if "display_name" not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN display_name TEXT")
    if "avatar_url" not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN avatar_url TEXT")  # userpic (public, http(s))
    if "type" not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN type TEXT NOT NULL DEFAULT 'user'")
    if "funding_url" not in acct_cols:
        # Donation/funding link (0.9.0), public http(s). Used for both an author's and an org's
        # link (same column, different account rows). Surfaced on module cards.
        conn.execute("ALTER TABLE accounts ADD COLUMN funding_url TEXT")
    # One account per install-id / per email (NULLs are exempt — admin-made or profile-less accounts).
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_install_id "
        "ON accounts(install_id) WHERE install_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_email "
        "ON accounts(email) WHERE email IS NOT NULL"
    )

    ns_cols = {row["name"] for row in conn.execute("PRAGMA table_info(namespaces)").fetchall()}
    if "featured" not in ns_cols:
        conn.execute("ALTER TABLE namespaces ADD COLUMN featured INTEGER NOT NULL DEFAULT 0")
    if "blacklisted" not in ns_cols:
        conn.execute("ALTER TABLE namespaces ADD COLUMN blacklisted INTEGER NOT NULL DEFAULT 0")

    mod_cols = {row["name"] for row in conn.execute("PRAGMA table_info(modules)").fetchall()}
    # 0.6.0 community/discovery counters (all mirror the existing `downloads` column pattern).
    if "stars" not in mod_cols:
        conn.execute("ALTER TABLE modules ADD COLUMN stars INTEGER NOT NULL DEFAULT 0")
    if "views" not in mod_cols:
        conn.execute("ALTER TABLE modules ADD COLUMN views INTEGER NOT NULL DEFAULT 0")
    if "search_hits" not in mod_cols:
        conn.execute("ALTER TABLE modules ADD COLUMN search_hits INTEGER NOT NULL DEFAULT 0")
    if "created_at" not in mod_cols:
        # First-publish stamp, distinct from `updated_at` (which advances on every republish).
        conn.execute("ALTER TABLE modules ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")

    ver_cols = {row["name"] for row in conn.execute("PRAGMA table_info(versions)").fetchall()}
    if "needs_upgrade" not in ver_cols:
        # Set by the `revalidate` audit when a version no longer satisfies the current contract.
        conn.execute("ALTER TABLE versions ADD COLUMN needs_upgrade INTEGER NOT NULL DEFAULT 0")
    if "downloads" not in ver_cols:  # 0.6.0 per-version download counter
        conn.execute("ALTER TABLE versions ADD COLUMN downloads INTEGER NOT NULL DEFAULT 0")
    if "published_by" not in ver_cols:  # 0.9.0 authoring account (RBAC own-scoping + author funding)
        conn.execute("ALTER TABLE versions ADD COLUMN published_by INTEGER REFERENCES accounts(id)")
    if "content_hash" not in ver_cols:
        # Name-independent content signature (0.9.1): gates cross-name republish dedup on publish.
        conn.execute("ALTER TABLE versions ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")
    # Backfill anything still empty from the manifest, on every startup rather than only on the
    # column's first appearance — the 0.9.1 one-shot block above has already run on any migrated DB,
    # so a guarded backfill there would never fire again.
    #
    # 0.11 replaced the registry's own manifest-inputs Merkle root with the compiler's canonical
    # row-level `content_signature`, which the compiler now stamps onto the manifest itself. Rows
    # compiled under 0.5 carry it and are free to backfill from here. Rows that predate it cannot be:
    # the new algorithm reads the authored CSVs, which live in storage, and this function holds only
    # a connection. They keep `''` — the sentinel `find_versions_by_content` filters out — until an
    # operator runs `registry rederive-signatures --apply`, which has the storage backend, can report
    # a per-row failure, and is a deliberate act rather than a side effect of starting the server.
    for row in conn.execute(
        "SELECT id, manifest_json FROM versions WHERE content_hash = ''"
    ).fetchall():
        signature = ModuleManifest.model_validate_json(row["manifest_json"]).content_signature
        if signature:
            conn.execute(
                "UPDATE versions SET content_hash = ? WHERE id = ?", (signature, row["id"])
            )
    # Indexed here (not in SCHEMA) so it is created only after the column exists on migrated DBs.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_content ON versions(content_hash)")

    _migrate_0_11_facets(conn, ver_cols)
    _migrate_0_11_3_trust(conn)
    _migrate_0_17_fact_tables(conn, ver_cols)

    # 0.6.0 namespace membership: seed each existing single-owner namespace as an `owner` member,
    # so the new membership check (which supersedes single-owner) sees no disruption. Idempotent.
    conn.execute(
        "INSERT OR IGNORE INTO namespace_members(namespace, account_id, role) "
        "SELECT name, account_id, 'owner' FROM namespaces"
    )
    # 0.9.0 RBAC role rename: contributor → member. Old contributors could amend/yank ANY version;
    # `member` is own-only. Re-grant `admin` to preserve broad rights. Idempotent. See docs/UPGRADE.md.
    conn.execute("UPDATE namespace_members SET role = 'member' WHERE role = 'contributor'")


#: 0.11 per-version facets, projected out of `manifest.json` so listings can filter on them in SQL.
#: Everything else the 0.5 manifest gained — `resolution_signature`, `resolution_sources`, the full
#: `sources` licence lists, the `frequency`/`gene_metrics`/`literature` blocks — stays in
#: `manifest_json` and surfaces through the detail endpoint's inline manifest, the way `authorship`
#: and `panel` already do. A column is for something you filter or sort by; the rest is payload.
_V011_COLUMNS: tuple[tuple[str, str], ...] = (
    ("resolution_mode", "TEXT"),                          # 'strict' | 'best_effort' | NULL
    ("fully_resolved", "INTEGER NOT NULL DEFAULT 0"),
    ("trusted", "INTEGER"),                               # NULLABLE — see below
    ("vrs_alleles", "INTEGER NOT NULL DEFAULT 0"),
    ("vrs_identified", "INTEGER NOT NULL DEFAULT 0"),
    ("commercial_use", "INTEGER"),                        # tri-state 1/0/NULL
    ("redistribution", "INTEGER"),                        # tri-state 1/0/NULL
    ("share_alike", "INTEGER NOT NULL DEFAULT 0"),
)

#: 0.17 (format 0.6) per-version facets: which derived fact tables a version carries, and whether it
#: declared what its weights mean. Same rule as `_V011_COLUMNS` above — a column is for something you
#: filter by, and the counts and lists that make each table *interpretable* stay in `manifest_json`
#: and surface on the detail endpoint.
#:
#: **Plain booleans rather than tri-state, and that is correct here for once.** The licence columns
#: beside them are `NULL`-able because "this source's terms could not be established" is a real third
#: state. Presence of a fact table is not like that: either the compile had the table or it did not,
#: and a manifest that predates the block is a manifest whose module carried no such table — the
#: block did not exist to be omitted. So `0` is honest for a legacy row in a way it would not be for
#: `commercial_use`, and in a way `positional_rows` deliberately is not (see `db/facets.py`).
#:
#: The five RM44/S31/S33 counters are stored **nullable with no default**, which is the opposite
#: choice from the booleans above and is the whole point. `NOT NULL DEFAULT 0` would stamp "this
#: module has no positional rows" across every version compiled before 0.6 — a false statement about
#: a 1,482-row PGx artifact, and precisely the vacuous-`fully_resolved` defect these fields exist to
#: close. `NULL` means *not measured*, exactly as it does in the manifest.
_V017_COLUMNS: tuple[tuple[str, str], ...] = (
    ("has_gene_validity", "INTEGER NOT NULL DEFAULT 0"),
    ("has_clinical_assertions", "INTEGER NOT NULL DEFAULT 0"),
    ("has_gwas_effects", "INTEGER NOT NULL DEFAULT 0"),
    ("has_frequencies", "INTEGER NOT NULL DEFAULT 0"),
    ("weighting_declared", "INTEGER NOT NULL DEFAULT 0"),
    ("resolution_subjects", "INTEGER"),
    ("positional_rows", "INTEGER"),
    ("positional_rows_placed", "INTEGER"),
    ("expanded_keys", "INTEGER"),
    ("expanded_rows", "INTEGER"),
)


def _migrate_0_11_facets(conn: sqlite3.Connection, ver_cols: set[str]) -> None:
    """Add and backfill the 0.5-manifest facets.

    Unlike the content-signature re-derivation, this backfill reads `manifest_json` and nothing else
    — no storage, no network — which is exactly why it can live in a migration while that one cannot.

    `trusted` is deliberately nullable. A pre-0.5 manifest has `resolution_mode=None` and
    `fully_resolved=False`, so `NOT NULL DEFAULT 0` would stamp "untrusted" across the entire existing
    catalog on the day this ships. `NULL` means *predates the contract*, which the API renders as "—"
    rather than as a judgement.
    """
    added = [name for name, decl in _V011_COLUMNS if name not in ver_cols]
    for name, decl in _V011_COLUMNS:
        if name not in ver_cols:
            conn.execute(f"ALTER TABLE versions ADD COLUMN {name} {decl}")
    if added:
        for row in conn.execute("SELECT id, manifest_json FROM versions").fetchall():
            facets = version_facets(ModuleManifest.model_validate_json(row["manifest_json"]))
            conn.execute(
                "UPDATE versions SET " + ", ".join(f"{k} = ?" for k in facets) + " WHERE id = ?",
                (*facets.values(), row["id"]),
            )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_trusted ON versions(trusted)")


def _migrate_0_17_fact_tables(conn: sqlite3.Connection, ver_cols: set[str]) -> None:
    """Add and backfill the format-0.6 fact-table facets.

    Reads `manifest_json` only — no storage, no network — which is what makes it a migration rather
    than an ops command, and it is idempotent: the backfill runs on the columns' first appearance and
    the values are a pure function of a manifest that never changes.

    **Nothing here re-judges anything**, unlike `_migrate_0_11_3_trust`. Every existing row backfills
    to `0` because a pre-0.6 manifest carries none of these blocks, and that is not a downgrade: the
    modules genuinely have no `gwas_effects.csv`, since the table did not exist when they were
    compiled. The columns become non-zero as versions are published or recompiled onto 0.6.
    """
    added = [name for name, decl in _V017_COLUMNS if name not in ver_cols]
    for name, decl in _V017_COLUMNS:
        if name not in ver_cols:
            conn.execute(f"ALTER TABLE versions ADD COLUMN {name} {decl}")
    if added:
        for row in conn.execute("SELECT id, manifest_json FROM versions").fetchall():
            facets = version_facets(ModuleManifest.model_validate_json(row["manifest_json"]))
            columns = {k: v for k, v in facets.items() if k in {n for n, _ in _V017_COLUMNS}}
            conn.execute(
                "UPDATE versions SET " + ", ".join(f"{k} = ?" for k in columns) + " WHERE id = ?",
                (*columns.values(), row["id"]),
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_versions_gwas_effects ON versions(has_gwas_effects)"
    )


def _migrate_0_11_3_trust(conn: sqlite3.Connection) -> None:
    """Re-project `trusted` where 0.11.3 changed the rule out from under a stored value.

    A migration is required and a re-publish is not: the manifests are correct and immutable, only
    our *reading* of them moved. `_migrate_0_11_facets` cannot do it — it backfills solely on the
    columns' first appearance, so on any DB that has already migrated it will never fire again.

    Two populations, and the predicates are written so each row stops matching once fixed, which is
    what makes this idempotent without a marker table:

    * `trusted = 1` with no `resolution_mode` — trust granted by `fully_resolved` being `all()` over a
      `variants.csv` that does not exist. Becomes `False` (the compiler warned) or `NULL` (it did not).
    * any row carrying the positional-joinability warning and not already `0`. The `LIKE` is a cheap
      prefilter over `manifest_json`, not the decision: `is_trusted` re-derives from the parsed
      manifest, so this stays the single derivation and cannot drift from the publish path. It is
      bound from `UNJOINABLE_PHRASE` rather than spelled again here, so the prefilter cannot go
      looking for one string while the verdict keys off another.

    Deliberately narrow rather than a whole-catalog re-projection. Rows this release did not affect
    are not rewritten, so the migration cannot quietly repair — or quietly damage — anything else.
    """
    rows = conn.execute(
        """
        SELECT id, manifest_json FROM versions
         WHERE (trusted = 1 AND resolution_mode IS NULL)
            OR (manifest_json LIKE ? AND (trusted IS NULL OR trusted != 0))
        """,
        (f"%{UNJOINABLE_PHRASE}%",),
    ).fetchall()
    if not rows:
        return
    for row in rows:
        verdict = is_trusted(ModuleManifest.model_validate_json(row["manifest_json"]))
        conn.execute(
            "UPDATE versions SET trusted = ? WHERE id = ?",
            (None if verdict is None else int(verdict), row["id"]),
        )
    logger.info("0.11.3: re-projected `trusted` for %d version(s).", len(rows))
