"""
Admin CLI (Typer). Ops tasks that live outside the HTTP surface: run the server, initialize the
DB, and issue API keys / namespaces for the static-key auth model.
"""

import json
import os
import secrets
from pathlib import Path
from typing import Optional

import httpx
import typer
import uvicorn
from just_dna_format.manifest import ModuleManifest
from just_dna_format.vocab import VALID_DECLARED_USE

from just_dna_registry.backup import create_backup, list_backups, restore_backup
from just_dna_registry.config import DEFAULT_PORTS, VALID_MODES, Settings, get_settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.models.api import VALID_ACCOUNT_TYPES
from just_dna_registry.permissions import VALID_NS_ROLES, VALID_ORG_ROLES
from just_dna_registry.startup import export_enricher_credentials, legacy_db_message
from just_dna_registry.services.pmid_check import verify_pmids
from just_dna_registry.services.purge import DEFAULT_PREFIX, apply_purge, plan_purge
from just_dna_registry.services.revalidate import gather_pmids, revalidate_version
from just_dna_registry.services.upgrade import (
    VersionUpgradePlan,
    is_latest_version,
    prepare_version_upgrade,
    upgrade_version,
)
from just_dna_registry.storage.base import StorageBackend
from just_dna_registry.testdata import accepted_anyway, test_data_refusal
from just_dna_registry.storage.local import LocalStorage

app = typer.Typer(help="just-dna-registry admin CLI", no_args_is_help=True)


def _apply_mode(mode: Optional[str]) -> None:
    """Point this process at one deployment's rules, by setting `REGISTRY_MODE`.

    Set the variable rather than build a `Settings`, for `serve`'s reason (uvicorn imports the app by
    string, so the worker reads the environment) and for a second one that applies to every other
    command: `get_settings` is `lru_cache`d, so a value handed around by hand would leave any later
    reader on the pre-flag settings.
    """
    if mode is None:
        return
    normalized = mode.strip().lower()
    if normalized not in VALID_MODES:
        raise typer.BadParameter(f"--mode must be one of {sorted(VALID_MODES)}, got: {mode!r}")
    os.environ["REGISTRY_MODE"] = normalized
    get_settings.cache_clear()


@app.callback()
def main(
    mode: str = typer.Option(
        None, "--mode", help="prod | test — overrides REGISTRY_MODE for this invocation"
    ),
) -> None:
    """Admin/ops commands for one deployment.

    **`--mode` belongs here and not only on `serve`, and an incident is why.** A deployment sets
    `REGISTRY_MODE` in its unit file or compose env, which reaches the server process and *not* an
    operator's shell — so `registry upgrade` run by hand on the polygon read the default, `prod`, and
    applied production's rules to the test box's catalog. Nothing said so: the mode is invisible until
    a rule fires, and the rule that fired refused the data the polygon exists to hold. Every command
    here now takes the flag, before the subcommand: `registry --mode test upgrade --apply --force`.

    `serve --mode` still works and means the same thing; it predates this and is documented.
    """
    _apply_mode(mode)


def _echo_mode(settings: Settings) -> None:
    """Say which deployment's rules this invocation is applying, before it applies them.

    On the two long catalog-wide operations only. The mode changes what a publish accepts and how
    `duplicate_content` is scoped, and it is otherwise invisible until a rule fires — which is how a
    polygon sweep came to run under production's rules and die on `test_data_on_prod` at the first
    test-prefixed module. A line up front costs nothing and turns that into a self-diagnosis.
    """
    typer.echo(f"mode={settings.mode} db={settings.db_path}")


def _open_existing_db(settings: Settings) -> Repository:
    """Open an EXISTING catalog DB for a read-only op. Refuses a missing or empty/uninitialized file
    (a relative `db_path` resolved against the wrong working directory is the classic trap) instead
    of silently creating a stray empty DB and then failing on `no such table`."""
    path = settings.db_path
    if not path.exists():
        raise typer.BadParameter(
            legacy_db_message(path)
            or f"no registry database at {path.resolve()} — set REGISTRY_DB_PATH to the server's DB"
        )
    conn = connect(path)
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'"
    ).fetchone() is None:
        raise typer.BadParameter(
            f"{path.resolve()} has no registry schema (empty/uninitialized) — wrong REGISTRY_DB_PATH?"
        )
    init_db(conn)  # additive/idempotent: bring a pre-0.9 DB up to the current schema (adds funding_url, …)
    return Repository(conn)


def _storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir)
    if settings.storage_backend == "hf":
        from just_dna_registry.storage.hf import HfStorage  # imports huggingface_hub lazily

        return HfStorage(settings.hf_repo_id, token=settings.hf_token)
    raise typer.BadParameter(f"unsupported storage_backend {settings.storage_backend!r}")


def _guard(settings: Settings, *, reason: str, backup: bool) -> None:
    """Snapshot the catalog before a destructive op, and say where it went.

    Called *after* the confirmation prompt and *before* the first mutation, so an aborted command
    leaves no snapshot and an applied one always has exactly one. `backup=False` (per-command
    `--no-backup`, or `REGISTRY_AUTO_BACKUP=false`) is honoured but announced — a silent opt-out of the
    only undo in this CLI is not something an operator should discover afterwards from a diff.
    """
    if not (backup and settings.auto_backup):
        typer.secho("! no pre-flight snapshot taken (auto-backup disabled)", fg=typer.colors.YELLOW)
        return
    snapshot = create_backup(settings, reason=reason)
    if snapshot is None:
        typer.echo("no existing DB to snapshot")
    else:
        typer.secho(f"snapshot: {snapshot}", fg=typer.colors.GREEN)


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = typer.Option(None, help="Default: 8000 in prod mode, 8100 in test mode"),
    mode: str = typer.Option(
        None, "--mode", help="prod | test — overrides REGISTRY_MODE for this process"
    ),
    reload: bool = False,
) -> None:
    """Run the API server. The port defaults per mode: prod 8000, test (polygon) 8100.

    One number apart rather than adjacent so a client pointed at the wrong instance gets a connection
    refusal instead of the wrong catalog answering on a plausible port.

    `--mode` here is the same flag the root callback takes (`registry --mode test serve` works too),
    kept on the command because it predates the callback and deployments have it written down. Both go
    through `_apply_mode`, which sets `REGISTRY_MODE` rather than handing a value to the app — it has
    to: uvicorn imports the application by string, so `create_app()` runs in the worker and builds its
    own `Settings` from the environment, and with `--reload` that worker is a whole other process.
    Mutating a `Settings` object here would configure the CLI and nothing that serves a request.

    A deployment should still set `REGISTRY_MODE` in its unit file or compose env. The flag is for a
    local polygon on a developer's machine, where remembering an export per shell is the annoying part.
    """
    _apply_mode(mode)
    settings = get_settings()
    resolved = port if port is not None else DEFAULT_PORTS[settings.mode]
    typer.echo(f"mode={settings.mode} listening on {host}:{resolved}")
    if settings.is_test_instance:
        typer.secho(
            "test instance: accepts test-prefixed data, scopes duplicate_content to the publisher, "
            "and mounts DELETE on modules/versions.",
            fg=typer.colors.YELLOW,
        )
    uvicorn.run("just_dna_registry.api.app:app", host=host, port=resolved, reload=reload)


@app.command("init-db")
def init_db_command() -> None:
    """Create the catalog tables if they do not exist."""
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)
    typer.echo(f"Initialized catalog DB at {settings.db_path}")


@app.command("issue-key")
def issue_key(
    account: str,
    namespace: list[str] = typer.Option([], "--namespace", "-n"),
    email: str = typer.Option(None, "--email", help="Account contact email (private)"),
    display_name: str = typer.Option(None, "--display-name", help="Human display name"),
    avatar_url: str = typer.Option(None, "--avatar-url", help="Userpic (public http(s) URL)"),
    account_type: str = typer.Option("user", "--type", help="Account type: user|org"),
    allow_test_data: bool = typer.Option(
        False,
        "--allow-test-data",
        help="Grant a test-prefixed namespace on production deliberately (0.14). Off by default so "
             "a typo is still refused.",
    ),
) -> None:
    """Create an account (if needed), grant it namespaces, and print a fresh API key."""
    if account_type not in VALID_ACCOUNT_TYPES:
        raise typer.BadParameter(f"--type must be one of {sorted(VALID_ACCOUNT_TYPES)}")
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)
    repo = Repository(conn)
    account_id = repo.create_account(account)
    repo.set_account_type(account_id, account_type)
    if email is not None or display_name is not None or avatar_url is not None:
        repo.set_account_profile(
            account_id, email=email, display_name=display_name, avatar_url=avatar_url
        )
    for ns in namespace:
        # Same rule as the HTTP claim route: production does not host test-prefixed namespaces, and the
        # CLI is the other door into the same table. Checked per namespace before any is granted, so a
        # mixed list does not half-apply.
        refusal = test_data_refusal(ns, "", settings)
        if refusal is None:
            continue
        if not allow_test_data:
            raise typer.BadParameter(f"{refusal} Pass --allow-test-data to grant it anyway.")
        typer.secho(accepted_anyway(refusal), fg=typer.colors.YELLOW)
    for ns in namespace:
        repo.add_namespace(ns, account_id)
    key = "mk_live_" + secrets.token_urlsafe(24)
    repo.add_api_key(key, account_id)
    typer.echo(f"account={account} type={account_type} namespaces={namespace}")
    typer.echo(f"API key: {key}")


@app.command("export-keys")
def export_keys(
    out: Path = typer.Option(None, "--out", "-o", help="Write JSON here (default: stdout)"),
) -> None:
    """Export the auth graph — accounts, API keys, namespaces, memberships — for backup or a
    preprod→prod migration. WARNING: the output contains live API-key tokens; keep it secret.

    (The Ed25519 *signing* key is a separate PEM file at `REGISTRY_SIGNING_KEY`, never in the DB —
    copy that file directly; it is unaffected by `reset-db`.)"""
    settings = get_settings()
    repo = _open_existing_db(settings)  # refuse a missing/empty DB (don't create a stray one)
    payload = json.dumps(repo.export_auth(), indent=2)
    if out is not None:
        out.write_text(payload + "\n", encoding="utf-8")
        typer.echo(f"wrote auth export to {out} (contains secrets — protect it)")
    else:
        typer.echo(payload)


@app.command("import-keys")
def import_keys(path: Path = typer.Argument(..., help="JSON file produced by export-keys")) -> None:
    """Restore an auth graph exported by `export-keys` (idempotent; preserves account ids). Use to
    seed a fresh/reset DB or a new environment with the same accounts + API keys."""
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)  # ensure tables exist before importing
    counts = Repository(conn).import_auth(json.loads(path.read_text(encoding="utf-8")))
    typer.echo("imported " + ", ".join(f"{n} {k}" for k, n in counts.items()))


@app.command("reset-db")
def reset_db(
    keep_keys: bool = typer.Option(
        True, "--keep-keys/--wipe-keys",
        help="Keep accounts + API keys (default), or wipe them too",
    ),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Snapshot the DB first"),
) -> None:
    """Wipe the catalog projection (modules, versions, stars, reviews) — a fresh start. Accounts +
    API keys are **kept** by default (so you don't lock yourself out); `--wipe-keys` clears them too.
    Does NOT touch artifact storage. Requires typing RESET to confirm (destructive)."""
    settings = get_settings()
    scope = "the catalog" if keep_keys else "the catalog AND all accounts + API keys"
    typer.echo(f"This will permanently delete {scope} in {settings.db_path.resolve()}. Artifacts are untouched.")
    if typer.prompt("Type RESET to confirm") != "RESET":
        raise typer.Abort()
    _guard(settings, reason="reset-db", backup=backup)
    conn = connect(settings.db_path)
    init_db(conn)
    Repository(conn).reset_catalog(keep_auth=keep_keys)
    typer.echo("catalog reset" + (" (accounts + API keys kept)" if keep_keys else " (keys wiped too)"))


@app.command("add-member")
def add_member(
    namespace: str,
    account: str,
    role: str = typer.Option("member", "--role", "-r", help="owner | admin | member"),
) -> None:
    """Add or re-role an account in a namespace (ops)."""
    if role not in VALID_NS_ROLES:
        raise typer.BadParameter(f"role must be one of {sorted(VALID_NS_ROLES)}")
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    if repo.namespace_owner(namespace) is None:
        typer.echo(f"namespace not found: {namespace}")
        raise typer.Exit(code=1)
    row = repo.account_by_name(account)
    if row is None:
        typer.echo(f"account not found: {account}")
        raise typer.Exit(code=1)
    repo.add_member(namespace, int(row["id"]), role)
    typer.echo(f"{namespace}: {account} is now {role}")


@app.command("remove-member")
def remove_member(namespace: str, account: str) -> None:
    """Revoke an account's membership in a namespace (ops). Refuses to remove the last owner."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    row = repo.account_by_name(account)
    if row is None:
        typer.echo(f"account not found: {account}")
        raise typer.Exit(code=1)
    account_id = int(row["id"])
    if (
        repo.namespace_role(namespace, account_id) == "owner"
        and repo.count_namespace_owners(namespace) <= 1
    ):
        typer.echo(f"refusing to remove the last owner of {namespace}")
        raise typer.Exit(code=1)
    if not repo.remove_member(namespace, account_id):
        typer.echo(f"{account} is not a member of {namespace}")
        raise typer.Exit(code=1)
    typer.echo(f"{namespace}: removed {account}")


@app.command("list-members")
def list_members(namespace: str) -> None:
    """List a namespace's members and their roles (ops)."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    members = repo.list_members(namespace)
    if not members:
        typer.echo(f"{namespace}: no members (namespace may not exist)")
        return
    for m in members:
        typer.echo(f"  {m['role']:<12} {m['account']}")


# ── Orgs + funding (0.9.0) ───────────────────────────────────────────────────

def _require_org(repo: Repository, org: str) -> int:
    row = repo.account_by_name(org)
    if row is None or repo.account_type(int(row["id"])) != "org":
        typer.echo(f"org not found (or not type=org): {org}")
        raise typer.Exit(code=1)
    return int(row["id"])


@app.command("create-org")
def create_org(name: str) -> None:
    """Create an org account (ops). Add members with `add-org-member`."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    if repo.account_by_name(name) is not None:
        typer.echo(f"name already taken: {name}")
        raise typer.Exit(code=1)
    org_id = repo.create_account(name)
    repo.set_account_type(org_id, "org")
    typer.echo(f"created org: {name}")


@app.command("add-org-member")
def add_org_member(
    org: str,
    account: str,
    role: str = typer.Option("member", "--role", "-r", help="owner | admin | member"),
) -> None:
    """Add or re-role an org member (ops)."""
    if role not in VALID_ORG_ROLES:
        raise typer.BadParameter(f"role must be one of {sorted(VALID_ORG_ROLES)}")
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    org_id = _require_org(repo, org)
    row = repo.account_by_name(account)
    if row is None:
        typer.echo(f"account not found: {account}")
        raise typer.Exit(code=1)
    repo.add_org_member(org_id, int(row["id"]), role)
    typer.echo(f"{org}: {account} is now {role}")


@app.command("remove-org-member")
def remove_org_member(org: str, account: str) -> None:
    """Remove an org member (ops). Refuses to remove the last owner."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    org_id = _require_org(repo, org)
    row = repo.account_by_name(account)
    if row is None:
        typer.echo(f"account not found: {account}")
        raise typer.Exit(code=1)
    if repo.org_role(org_id, int(row["id"])) == "owner" and repo.count_org_owners(org_id) <= 1:
        typer.echo(f"refusing to remove the last owner of {org}")
        raise typer.Exit(code=1)
    if not repo.remove_org_member(org_id, int(row["id"])):
        typer.echo(f"{account} is not a member of {org}")
        raise typer.Exit(code=1)
    typer.echo(f"{org}: removed {account}")


@app.command("list-org-members")
def list_org_members(org: str) -> None:
    """List an org's members and their roles (ops)."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    org_id = _require_org(repo, org)
    for m in repo.list_org_members(org_id):
        typer.echo(f"  {m['role']:<12} {m['account']}")


@app.command("set-funding")
def set_funding(account: str, url: str = typer.Argument(..., help="Donation link ('' clears)")) -> None:
    """Set (or clear) an account's or org's public funding/donation link (ops)."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    row = repo.account_by_name(account)
    if row is None:
        typer.echo(f"account not found: {account}")
        raise typer.Exit(code=1)
    repo.set_account_profile(int(row["id"]), funding_url=url)
    typer.echo(f"{account}: funding_url {'cleared' if url == '' else 'set'}")


@app.command("remove-module")
def remove_module(
    namespace: str, name: str, yes: bool = typer.Option(False, "--yes", "-y"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Snapshot the DB first"),
) -> None:
    """Hard-delete a module (all versions + artifacts). Ops-only; not reversible, not yank."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    storage = _storage(settings)
    if not yes:
        typer.confirm(f"Hard-delete {namespace}/{name} and ALL its artifacts?", abort=True)
    _guard(settings, reason=f"remove-module-{namespace}-{name}", backup=backup)
    versions = repo.delete_module(namespace, name)
    storage.remove(f"{namespace}/{name}")
    typer.echo(f"removed {namespace}/{name} ({len(versions)} version(s): {versions})")


@app.command("remove-version")
def remove_version(
    namespace: str, name: str, version: str, yes: bool = typer.Option(False, "--yes", "-y"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Snapshot the DB first"),
) -> None:
    """Hard-delete a single version + its artifacts (not yank). Frees it for re-upload."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    storage = _storage(settings)
    if not yes:
        typer.confirm(f"Hard-delete {namespace}/{name}@{version} and its artifacts?", abort=True)
    _guard(settings, reason=f"remove-version-{namespace}-{name}", backup=backup)
    if not repo.delete_version(namespace, name, version):
        typer.echo(f"not found: {namespace}/{name}@{version}")
        raise typer.Exit(code=1)
    storage.remove(f"{namespace}/{name}/{version}")
    typer.echo(f"removed {namespace}/{name}@{version}")


@app.command("remove-namespace")
def remove_namespace(
    namespace: str, yes: bool = typer.Option(False, "--yes", "-y"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Snapshot the DB first"),
) -> None:
    """Hard-delete every module under a namespace + its artifacts, and free the namespace so a new
    key can claim it. Ops-only; nothing resurfaces."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    storage = _storage(settings)
    modules = repo.modules_in_namespace(namespace)
    if not yes:
        typer.confirm(
            f"Hard-delete namespace {namespace!r}: {len(modules)} module(s) + artifacts, "
            "and free the namespace?",
            abort=True,
        )
    _guard(settings, reason=f"remove-namespace-{namespace}", backup=backup)
    for module in modules:
        repo.delete_module(namespace, module["name"])
    repo.delete_namespace_grant(namespace)
    storage.remove(namespace)  # nuke any residual {ns}/ subtree
    typer.echo(
        f"removed namespace {namespace}: {len(modules)} module(s) purged; namespace freed"
    )


def _set_flag(namespace: str, *, featured=None, blacklisted=None) -> None:
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    if not repo.set_namespace_flags(namespace, featured=featured, blacklisted=blacklisted):
        typer.echo(f"namespace not found: {namespace}")
        raise typer.Exit(code=1)
    typer.echo(f"{namespace}: featured={featured} blacklisted={blacklisted}")


@app.command()
def feature(namespace: str) -> None:
    """Mark a namespace featured (floats to the top of listings)."""
    _set_flag(namespace, featured=True)


@app.command()
def unfeature(namespace: str) -> None:
    """Clear a namespace's featured flag."""
    _set_flag(namespace, featured=False)


@app.command()
def blacklist(namespace: str) -> None:
    """Hide a namespace from default listings/search (still reachable by direct request)."""
    _set_flag(namespace, blacklisted=True)


@app.command()
def unblacklist(namespace: str) -> None:
    """Un-hide a blacklisted namespace."""
    _set_flag(namespace, blacklisted=False)


@app.command()
def revalidate(
    namespace: str = typer.Option(None, "--namespace", "-n", help="Limit to one namespace"),
    set_flag: bool = typer.Option(
        False, "--set-flag/--report-only",
        help="Set the needs_upgrade flag on failing versions (default: report only)",
    ),
    check_pmids: bool = typer.Option(
        False, "--check-pmids", help="Also verify each study PMID resolves at NCBI (network)"
    ),
    strict_check: bool = typer.Option(
        False, "--strict-check", help="Grade mode-ladder findings at strict severity (cheap)"
    ),
    recompile_check: bool = typer.Option(
        False,
        "--recompile-check",
        help="Enrich + compile strict for real, to see what a strict publish would refuse (slow)",
    ),
) -> None:
    """Re-run the current contract's `validate_spec` over every published version's stored spec.

    Finds modules that a `just-dna-format` bump would now reject. Published artifacts are immutable
    and untouched; with `--set-flag` failing versions are marked `needs_upgrade` so listings surface
    them and an upgrade (re-publish as a new PATCH) can be scheduled. See docs/UPGRADE.md.

    **Before flipping a deployment to strict publishes**, run `--recompile-check`: it enriches and
    compiles each version exactly as a publish would, so `strict_blocked` tells you precisely which
    modules a flip would stop accepting — one report rather than a stream of 422s from confused
    publishers. `--strict-check` is the cheap approximation: it catches the mode-ladder findings but
    not the unresolved-position gate, which only a real compile can see."""
    settings = get_settings()
    _echo_mode(settings)
    conn = connect(settings.db_path)
    init_db(conn)  # idempotent: ensures the needs_upgrade column exists on a pre-0.5.0 DB
    repo = Repository(conn)
    storage = _storage(settings)
    counts = {"ok": 0, "upgradable": 0, "needs_upgrade": 0, "strict_blocked": 0,
              "superseded": 0, "skipped": 0}
    for row in repo.list_all_versions(namespace):
        ns, name, ver = row["namespace"], row["name"], row["version"]
        manifest = ModuleManifest.model_validate_json(row["manifest_json"])
        status, messages = revalidate_version(
            storage, ns, name, ver, manifest,
            settings=settings, strict_check=strict_check, recompile_check=recompile_check,
        )

        pmid_note = ""
        if check_pmids:
            pmids = gather_pmids(storage, ns, name, ver, manifest)
            try:
                missing = [p for p, exists in verify_pmids(pmids).items() if not exists]
            except httpx.HTTPError as exc:
                pmid_note = f"  [pmid check failed: {exc}]"
            else:
                if missing:
                    status = "needs_upgrade"
                    messages = [*messages, f"PMIDs not found at NCBI: {', '.join(missing)}"]
                pmid_note = f"  [{len(pmids)} pmid(s) checked]"

        # Mask a drifted OLD version once a newer one supersedes it: it's immutable and the module's
        # latest is what an upgrade targets, so it isn't actionable (and must not drive a re-publish).
        if status in ("upgradable", "needs_upgrade", "strict_blocked") and not is_latest_version(
            repo, ns, name, ver
        ):
            status = "superseded"
            messages = [f"superseded by a newer version ({row['latest_version']}); not actionable"]

        counts[status] += 1
        marker = {"ok": "✓", "upgradable": "⇧", "needs_upgrade": "✗",
                  "strict_blocked": "⊘", "superseded": "·", "skipped": "–"}[status]
        typer.echo(f"{marker} {ns}/{name}@{ver} [{status}]{pmid_note}")
        for msg in messages[:5]:
            typer.echo(f"    {msg}")
        # Actionable states flag the version; ok/superseded clear it (superseded can't be fixed).
        if set_flag and status in ("ok", "upgradable", "needs_upgrade", "superseded"):
            repo.set_needs_upgrade(ns, name, ver, status in ("upgradable", "needs_upgrade"))

    typer.echo(
        f"\n{counts['ok']} ok, {counts['upgradable']} upgradable, "
        f"{counts['needs_upgrade']} needs_upgrade, {counts['strict_blocked']} strict_blocked, "
        f"{counts['superseded']} superseded, {counts['skipped']} skipped"
        + ("" if set_flag else "  (report only; pass --set-flag to persist)")
    )


def _describe_upgrade(prep: VersionUpgradePlan, *, recompile: bool) -> str:
    """One-line summary of what a re-publish of this version would change."""
    bits: list[str] = []
    if prep.variants_plan.needed:
        bits.append(
            f"{prep.variants_plan.upgradable_rows}/{prep.variants_plan.total_rows} row(s) back-populated"
        )
    if prep.dropped:
        dropped = sum(len(c) for c in prep.dropped.values())
        bits.append(f"{dropped} column(s)/key(s) trimmed")
    if prep.needs_contract_recompile:
        bits.append("0.5 recompile (digest moves: variant_key re-baselined)")
    if not bits:  # only a schema recompile is left
        bits.append("schema recompile (no content change)")
    return ", ".join(bits)


@app.command()
def upgrade(
    namespace: str = typer.Option(None, "--namespace", "-n", help="Limit to one namespace"),
    module: str = typer.Option(None, "--module", "-m", help="Limit to one module name"),
    apply: bool = typer.Option(
        False, "--apply/--dry-run",
        help="Actually re-publish upgraded versions (default: dry-run, report only)",
    ),
    force: bool = typer.Option(
        False, "--force", "--recompile",
        help="Recompile the latest to the current contract even with no 0.3 drift (a non-lossy "
             "schema migration); also required to enable the lossy --trim",
    ),
    trim: bool = typer.Option(
        False, "--trim",
        help="Drop columns the current contract rejects so a legacy spec compiles (LOSSY — discards "
             "data); requires --force",
    ),
    limit: int = typer.Option(
        0, "--limit", help="Stop after this many versions (0 = no limit). Batch a large migration."
    ),
) -> None:
    """Migrate published versions to the current `just-dna-format` contract and re-publish as a PATCH.

    Automatic: back-populates the additive 0.3 axes (direction/stat_significance/clin_sig) for any
    version whose `variants.csv` still carries only the legacy `state`/booleans. `--force`
    (`--recompile`) additionally re-emits an already-on-contract module in the current parquet schema
    (non-lossy). `--trim` drops columns 0.4 now forbids (old schemas only warned) so a stale spec
    compiles — LOSSY, so it requires `--force`. A version with such columns and no `--trim` is
    reported *blocked*. Re-publish runs the full server-side compile path; the predecessor is never
    mutated. Dry-run by default. See docs/UPGRADE.md."""
    if trim and not force:
        raise typer.BadParameter("--trim is lossy (it drops columns); re-run with --force to confirm")
    settings = get_settings()
    _echo_mode(settings)
    conn = connect(settings.db_path)
    init_db(conn)
    repo = Repository(conn)
    storage = _storage(settings)
    planned = upgraded = blocked = 0
    # The 0.5 migration roughly doubles the catalog's version count and runs a full enrich+compile
    # per module, so it is the longest ops operation the registry has. `--limit` makes it batchable.
    for row in repo.list_all_versions(namespace):
        if limit and (planned + upgraded) >= limit:
            typer.echo(f"\n(stopping at --limit {limit}; re-run to continue)")
            break
        ns, name, ver = row["namespace"], row["name"], row["version"]
        if module is not None and name != module:
            continue
        # Only the latest version is upgrade-eligible — a superseded older version is immutable and
        # already replaced, so re-upgrading it would just mint an endless chain of patches.
        if not is_latest_version(repo, ns, name, ver):
            continue
        manifest = ModuleManifest.model_validate_json(row["manifest_json"])
        prep = prepare_version_upgrade(storage, ns, name, ver, manifest, trim=trim)
        if prep is None:  # spec inputs not retrievable (legacy import)
            continue
        if prep.blocked:
            detail = "; ".join(f"{f}: {', '.join(c)}" for f, c in prep.blocked.items())
            typer.echo(f"✗ {ns}/{name}@{ver}: contract rejects ({detail}) — "
                       f"re-run with --trim --force to drop them")
            blocked += 1
            continue
        if not prep.would_act(recompile=force):
            continue
        if not apply:
            planned += 1
            typer.echo(f"⇧ {ns}/{name}@{ver}: {_describe_upgrade(prep, recompile=force)} → next PATCH")
            continue
        result = upgrade_version(
            repo=repo, storage=storage, settings=settings,
            namespace=ns, name=name, version=ver, manifest=manifest,
            recompile=force, trim=trim, prepared=prep,
        )
        if result is not None:
            new_version, _ = result
            upgraded += 1
            typer.echo(
                f"✓ {ns}/{name}@{ver} → {new_version} ({_describe_upgrade(prep, recompile=force)})"
            )
            typer.echo(f"    digest {manifest.artifact.digest[:23]}… → {result[1].artifact.digest[:23]}…")

    blocked_note = f", {blocked} blocked (need --trim --force)" if blocked else ""
    if apply:
        typer.echo(f"\n{upgraded} version(s) upgraded and re-published{blocked_note}")
    else:
        typer.echo(
            f"\n{planned} version(s) would upgrade{blocked_note}  (dry-run; pass --apply to publish)"
        )


@app.command("revoke-key")
def revoke_key(key: str) -> None:
    """Invalidate a single API key (e.g. a leaked one)."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    typer.echo("revoked" if repo.revoke_api_key(key) else "no such key")


@app.command("revoke-account")
def revoke_account(account: str, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Invalidate ALL API keys for an account."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    if not yes:
        typer.confirm(f"Revoke all API keys for account {account!r}?", abort=True)
    typer.echo(f"revoked {repo.revoke_api_keys_for_account(account)} key(s)")


if __name__ == "__main__":
    app()


# ── 0.11 operator commands ────────────────────────────────────────────────────


@app.command("warm-caches")
def warm_caches(
    ensembl: bool = typer.Option(True, "--ensembl/--no-ensembl"),
    clinvar: bool = typer.Option(True, "--clinvar/--no-clinvar"),
    constraint: bool = typer.Option(
        False, "--constraint/--no-constraint", help="gnomAD gene constraint (only the metrics pass)"
    ),
    pgx: bool = typer.Option(
        False, "--pgx/--no-pgx",
        help="The licence-gated PGx snapshots (cpic, clinpgx) — only the `?pgx=` check reads them",
    ),
    use: Optional[str] = typer.Option(
        None, "--use",
        help=(
            "Declared use for the gated snapshots: unstated | non_commercial | commercial. "
            "Downloading is *taking* the data, so the terms apply here. Defaults to "
            "REGISTRY_DECLARED_USE."
        ),
    ),
    apply: bool = typer.Option(False, "--apply/--dry-run"),
) -> None:
    """Provision the reference snapshots enrichment needs, from HuggingFace Hub.

    **Run this before pointing a deployment at 0.11.** Publishing now enriches before it compiles,
    and with strict compiles on, a server holding no snapshot cannot publish an rsID-authored module
    at all — it refuses rather than emitting a partial artifact.

    The dry run (the default) reports what the *running server* would find, using the same explicit
    cache paths and the same resolver, so it doubles as a health check. `--apply` downloads what is
    missing: hundreds of megabytes, minutes.

    Three groups, because they gate different things. **Resolution** (ensembl, clinvar) decides
    whether a publish works. **PGx** (cpic, clinpgx — `--pgx`) is what makes a *hosted* `?pgx=`
    check legitimate rather than merely possible: without a cache the only alternatives are fetching
    a source that forbids sale live, per request, on the operator's own acceptance, or skipping the
    check. Their rate figures are per IP, so a server multiplies its callers onto one allowance.
    Tiny by comparison — CPIC is ~256 KB. **Metrics** (constraint — `--constraint`) gates nothing
    here yet: the gene-metrics pass writes an authored sidecar and the registry never runs it, so
    this is provisioning for a `just-dna-enricher gene-metrics` run on the same box, and its absence
    is never reported as a finding about a module.

    **`--use` applies to the PGx pair and to nothing else.** Under a data-usage policy the terms are
    accepted when the data is *taken*, and a download is taking it, so `unstated` skips them and
    `commercial` refuses. The resolution snapshots never ask: none of Ensembl, ClinVar or gnomAD
    forbids sale.

    **PharmVar is absent on purpose.** Its bulk data comes down under a key its terms §2 make
    personal and non-transferable, so upstream publishes nothing to pull and offers no
    `ensure_pharmvar_snapshot`. Build it once yourself — `just-dna-enricher pharmvar build --out
    <dir>` — and set `REGISTRY_PHARMVAR_CACHE`.
    """
    settings = get_settings()
    from just_dna_registry.services.enrich import (
        GATED_REFERENCES,
        METRICS_REFERENCES,
        PGX_REFERENCES,
        RESOLUTION_REFERENCES,
        available_references,
        configured_caches,
        enricher_available,
    )

    # `create_app` does this at boot, and this command runs without one. It matters most here:
    # `huggingface_hub` reads `HF_TOKEN` and knows nothing of the `REGISTRY_` prefix, and the two
    # licence-gated PGx mirrors are private — so without the export a configured token is invisible
    # and the pull fails with 401 rather than with anything that names the cause.
    export_enricher_credentials(settings)

    if not enricher_available():
        typer.secho(
            "just-dna-enricher is not installed — run `uv sync --extra server`.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    from just_dna_enricher.download import (
        ensure_clinpgx_snapshot,
        ensure_clinvar_snapshot,
        ensure_constraint_snapshot,
        ensure_cpic_snapshot,
        ensure_snapshot,
    )
    from just_dna_enricher.licensing import (
        CLINPGX_TERMS,
        CPIC_TERMS,
        LicenseRefusal,
        check_declared_use,
    )

    # Hyphens accepted, and normalized here rather than in the API. A CLI flag is a human interface
    # and `--use non-commercial` is the spelling every enricher command documents — including inside
    # the licence messages printed below, which are upstream's words. An HTTP query parameter is a
    # machine interface, so `/check?declared_use=` stays strict and 422s: there the wrong spelling is
    # a caller bug, and guessing at a value that decides whether a no-sale source is touched is the
    # last place to be lenient.
    declared = (use or settings.declared_use).replace("-", "_")
    if declared not in VALID_DECLARED_USE:
        typer.secho(
            f"--use must be one of {sorted(VALID_DECLARED_USE)} (hyphens accepted), got {use!r}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    wanted = {
        "ensembl": ensembl, "clinvar": clinvar, "constraint": constraint,
        "cpic": pgx, "pharmvar": pgx, "clinpgx": pgx,
    }
    # `ensure_*` takes only the cache path; the fetcher is `None` where nothing is published.
    fetchers = {
        "ensembl": ensure_snapshot,
        "clinvar": ensure_clinvar_snapshot,
        "constraint": ensure_constraint_snapshot,
        "cpic": ensure_cpic_snapshot,
        "clinpgx": ensure_clinpgx_snapshot,
        "pharmvar": None,
    }
    terms = {"cpic": CPIC_TERMS, "clinpgx": CLINPGX_TERMS}

    configured = configured_caches(settings)
    present = available_references(settings)
    missing: list[str] = []
    for group, names in (
        ("resolution", RESOLUTION_REFERENCES),
        ("metrics", METRICS_REFERENCES),
        ("pgx", PGX_REFERENCES),
    ):
        typer.secho(f"\n{group}:", bold=True)
        for name in names:
            if not wanted[name]:
                typer.echo(f"  – {name}: skipped")
            elif present[name] is not None:
                typer.echo(f"  ✓ {name}: {present[name]}")
            elif fetchers[name] is None:
                # Not a failure to report as one: there is nothing to download, ever.
                typer.secho(
                    f"  ✗ {name}: absent, and never published — build it with "
                    f"`just-dna-enricher {name} build --out <dir>`, then set "
                    f"REGISTRY_{name.upper()}_CACHE",
                    fg=typer.colors.YELLOW,
                )
            else:
                typer.secho(f"  ✗ {name}: not provisioned", fg=typer.colors.YELLOW)
                missing.append(name)

    if not missing:
        typer.secho("\nEvery requested snapshot that can be pulled is present.", fg=typer.colors.GREEN)
        return
    if not apply:
        typer.echo(
            f"\n{len(missing)} snapshot(s) missing: {', '.join(missing)}. "
            f"Re-run with --apply to download (this takes a while and a lot of disk)."
        )
        raise typer.Exit(code=1)

    failures = 0
    for name in missing:
        if name in GATED_REFERENCES:
            # Checked before the download, not after: refusing here means nothing was taken, which
            # is the whole point of gating at acquisition.
            try:
                reason = check_declared_use(terms[name], declared)
            except LicenseRefusal as exc:
                typer.secho(f"✗ {name}: {exc}", fg=typer.colors.RED, err=True)
                failures += 1
                continue
            if reason is not None:
                # Upstream's own wording, unedited — it names the source, its licence and the policy
                # URL, and it is the text a reader will find again in the enricher's output.
                typer.secho(f"– {name}: skipped — {reason}", fg=typer.colors.YELLOW)
                continue
        typer.echo(f"downloading {name} …")
        try:
            path = fetchers[name](configured[name])
        except Exception as exc:  # noqa: BLE001 — one snapshot failing must not sink the rest
            # Broad on purpose, and mirroring the enricher's own `cache pull`. The reachable causes
            # are a dataset that is not published yet, an HF outage, a 429, a full disk and an
            # expired token — several of which surface from deep inside `fsspec` as types this
            # module has no business knowing. What an operator needs is which snapshot failed and
            # why, then for the other five to carry on; a traceback here would bury both.
            typer.secho(f"✗ {name}: FAILED — {exc}", fg=typer.colors.RED, err=True)
            looks_like_auth = "401" in str(exc) or "not found" in str(exc).lower()
            if name in GATED_REFERENCES and looks_like_auth:
                # These two mirrors are private, precisely because they mirror sources that forbid
                # sale — so anonymous access is refused rather than throttled, and a 401 reads as
                # "no such dataset". Say which it is, because the fix is a token and not a rebuild.
                typer.secho(
                    "   the licence-gated mirrors are private: set REGISTRY_HF_TOKEN (or HF_TOKEN) "
                    "to an account with access, or build this snapshot locally with "
                    f"`just-dna-enricher {name} build --out <dir>`.",
                    fg=typer.colors.YELLOW, err=True,
                )
            failures += 1
            continue
        typer.secho(f"✓ {name}: {path}", fg=typer.colors.GREEN)

    if failures:
        typer.secho(
            f"\n{failures} snapshot(s) could not be provisioned. The rest are usable — a missing "
            f"resolution snapshot degrades publishing, a missing PGx one only skips `?pgx=` legs.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)


@app.command("rederive-signatures")
def rederive_signatures(
    namespace: str = typer.Option(None, "--namespace", "-n"),
    apply: bool = typer.Option(False, "--apply/--dry-run"),
    allow_merges: bool = typer.Option(
        False,
        "--allow-merges",
        help="Proceed even when re-derivation makes two published modules collide",
    ),
) -> None:
    """Recompute every version's content signature under the compiler's canonical algorithm (0.11).

    0.11 replaced the registry's own manifest-inputs Merkle root with
    `just_dna_compiler.compiler.content_signature`, which hashes the authored rows as parsed rather
    than as bytes — so it survives a reformat, a row reorder, and a recompile against a different
    reference. The new value cannot be derived from a manifest, so this reads each version's CSVs
    back out of storage.

    **Required after upgrading.** Until it runs, versions predating 0.5 carry an empty signature and
    simply drop out of the dedup gate: publishing stays safe (nothing false-positives), but a genuine
    re-list of old data under a new name would not be caught, and the signature lookup endpoint would
    not find them.
    """
    settings = get_settings()
    repo = _open_existing_db(settings)
    storage = _storage(settings)

    from just_dna_registry.services.signatures import (
        apply_rederivation,
        collision_report,
        plan_rederivation,
    )

    changes = plan_rederivation(repo, storage, namespace=namespace)
    if not changes:
        typer.echo("no versions to re-derive")
        return

    marker = {"unchanged": "·", "derived": "+", "moved": "⇧", "moved_build": "⇧", "skipped": "–"}
    counts: dict[str, int] = {k: 0 for k in ("unchanged", "derived", "moved", "moved_build", "skipped")}
    for change in changes:
        counts[change.bucket] += 1
        if change.bucket == "unchanged":
            continue
        note = ""
        if change.bucket == "moved_build":
            note = f"  (genome_build={change.genome_build}; the build is now part of the content)"
        elif change.bucket == "skipped":
            note = f"  ({change.error})"
        typer.echo(f"{marker[change.bucket]} {change.module} [{change.bucket}]{note}")

    splits, merges = collision_report(changes)
    if splits:
        typer.secho(
            f"\n{len(splits)} split(s) — these modules no longer share a signature:",
            fg=typer.colors.YELLOW,
        )
        for old, modules in splits:
            typer.echo(f"    {old[:23]}… → {', '.join(modules)}")
        typer.echo(
            "    Benign, but worth knowing: anything previously refused as `duplicate_content` "
            "against one of these is now publishable."
        )
    if merges:
        typer.secho(
            f"\n{len(merges)} MERGE(s) — distinct published modules now share a signature:",
            fg=typer.colors.RED,
        )
        for new, modules in merges:
            typer.echo(f"    {new[:23]}… ← {', '.join(modules)}")
        typer.echo(
            "    The dedup gate will refuse the next version of all but one of each group. "
            "Review before proceeding."
        )

    typer.echo(
        "\n" + ", ".join(f"{n} {k}" for k, n in counts.items() if n)
        + ("" if apply else "  (dry run; pass --apply to write)")
    )
    if not apply:
        return
    if merges and not allow_merges:
        typer.secho(
            "\nRefusing to apply: re-derivation would make already-published modules collide. "
            "Review the merges above, then re-run with --allow-merges.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    written = apply_rederivation(repo, changes)
    typer.secho(f"\nwrote {written} signature(s)", fg=typer.colors.GREEN)


# ── 0.12 backup + test-data purge ─────────────────────────────────────────────


@app.command("backup")
def backup_command(
    reason: str = typer.Option("manual", "--reason", help="Goes in the filename, so `ls` explains itself"),
) -> None:
    """Snapshot the catalog DB now. Safe: the rolling index only counts up and never overwrites."""
    settings = get_settings()
    snapshot = create_backup(settings, reason=reason)
    if snapshot is None:
        typer.echo(f"no DB to snapshot at {settings.db_path.resolve()}")
        raise typer.Exit(code=1)
    typer.secho(f"snapshot: {snapshot}", fg=typer.colors.GREEN)


@app.command("list-backups")
def list_backups_command() -> None:
    """Snapshots, newest first, by rolling index."""
    settings = get_settings()
    found = list_backups(settings)
    if not found:
        typer.echo("no snapshots")
        return
    for path in found:
        typer.echo(f"{path.name}\t{path.stat().st_size / 1_048_576:.1f} MiB")


@app.command("restore-backup")
def restore_backup_command(
    snapshot: Path = typer.Argument(..., help="Snapshot file (see list-backups)"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Replace the live catalog DB with a snapshot. Snapshots the current DB first, always.

    Artifacts are NOT restored — a snapshot is the index, not the bytes. Restoring past a purge that
    removed artifacts gives rows pointing at storage keys that are gone; check `list-backups` timing
    against what you deleted."""
    settings = get_settings()
    if not yes:
        typer.confirm(f"Replace {settings.db_path.resolve()} with {snapshot}?", abort=True)
    typer.echo(f"restored {restore_backup(settings, snapshot)}")


@app.command("purge-test-data")
def purge_test_data(
    prefix: str = typer.Option(DEFAULT_PREFIX, "--prefix", help="What counts as test data"),
    apply: bool = typer.Option(False, "--apply", help="Actually remove it (default is a dry run)"),
    include_prod_namespaces: bool = typer.Option(
        False, "--include-prod-namespaces",
        help="Also remove prefix-matching modules that live in NON-test namespaces (dangerous)",
    ),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Snapshot the DB first"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Remove test accounts, namespaces and modules (+ orphans under them). Dry run by default.

    Run it with the server stopped: it deletes artifacts and rows that an in-flight publish may be
    holding, and SQLite gives no way to tell one is in progress.

    A module whose *name* matches the prefix but which lives in a production namespace is reported and
    **skipped** — it may be a real published module, and deleting it is unrecoverable. `--include-prod-
    namespaces` opts in. A production version authored by a purged account is kept and only loses its
    `published_by` pointer."""
    settings = get_settings()
    repo = _open_existing_db(settings)
    plan = plan_purge(repo, prefix=prefix, include_prod_namespaces=include_prod_namespaces)

    if not prefix.strip():
        typer.secho("empty --prefix matches nothing (refusing to treat it as match-all)",
                    fg=typer.colors.RED)
        raise typer.Exit(code=2)
    if plan.is_empty and not plan.modules_in_prod:
        typer.echo(f"nothing matches {prefix!r}")
        return

    for line in plan.describe():
        typer.echo("  " + line)
    if plan.modules_in_prod and not include_prod_namespaces:
        typer.secho(
            f"\n{len(plan.modules_in_prod)} prefix-matching module(s) in production namespaces were "
            f"SKIPPED — pass --include-prod-namespaces to remove them too.",
            fg=typer.colors.YELLOW,
        )
    if not apply:
        typer.echo(f"\ndry run — {len(plan.modules)} module(s) would be removed. Re-run with --apply.")
        return

    if not yes:
        typer.confirm(
            f"\nPermanently remove {len(plan.modules)} module(s), {len(plan.namespaces)} namespace(s) "
            f"and {len(plan.accounts)} account(s) + their artifacts?",
            abort=True,
        )
    _guard(settings, reason=f"purge-{prefix.strip('-') or 'test'}", backup=backup)
    apply_purge(repo, _storage(settings), plan)
    typer.secho(
        f"purged {len(plan.modules)} module(s), {len(plan.namespaces)} namespace(s), "
        f"{len(plan.accounts)} account(s); {len(plan.disowned_versions)} version(s) disowned",
        fg=typer.colors.GREEN,
    )
