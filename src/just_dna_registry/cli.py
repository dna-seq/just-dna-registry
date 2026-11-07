"""
Admin CLI (Typer). Ops tasks that live outside the HTTP surface: run the server, initialize the
DB, and issue API keys / namespaces for the static-key auth model.
"""

import json
import logging
import os
import secrets
import shlex
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import httpx
import typer
import uvicorn
from just_dna_format.manifest import ModuleManifest
from just_dna_format.vocab import VALID_DECLARED_USE
from typer.core import TyperGroup

from just_dna_registry.backup import create_backup, list_backups, restore_backup
from just_dna_registry.config import DEFAULT_PORTS, VALID_MODES, Settings, get_settings
from just_dna_registry.db.repository import HandleReserved, Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.logging_setup import uvicorn_log_config
from just_dna_registry.maintenance import (
    LOG_FILE,
    NOT_A_RUN,
    RevertRefused,
    active_run,
    apply_prune,
    disk_usage,
    human_size,
    journaled,
    list_runs,
    maintenance_run,
    plan_prune,
    quiet_console,
    read_record,
    revert_run,
    run_root,
    write_sweep,
)
from just_dna_registry.models.api import VALID_ACCOUNT_TYPES, AccountRename
from just_dna_registry.permissions import VALID_NS_ROLES, VALID_ORG_ROLES
from just_dna_registry.replay import ReplayRefused, replay_upgrade
from just_dna_registry.services.accounts import RenameRefused, merge_accounts, rename_account
from just_dna_registry.services.enrich import enricher_available, snapshot_not_current
from just_dna_registry.services.pmid_check import verify_pmids
from just_dna_registry.services.publish import PublishError
from just_dna_registry.services.purge import DEFAULT_PREFIX, apply_purge, plan_purge
from just_dna_registry.services.rebuild import UNPROBED_SURFACES
from just_dna_registry.services.revalidate import gather_pmids, revalidate_version
from just_dna_registry.services.upgrade import (
    GAP_PATCH,
    GAP_UNKNOWN,
    UpgradeHeld,
    VersionUpgradePlan,
    is_latest_version,
    prepare_version_upgrade,
    upgrade_version,
)
from just_dna_registry.startup import export_enricher_credentials, legacy_db_message
from just_dna_registry.storage.base import StorageBackend
from just_dna_registry.storage.local import LocalStorage
from just_dna_registry.sweep_report import (
    ANOMALY,
    BLOCKED,
    FAILED,
    HELD,
    HELD_NEEDS_ONLINE,
    HELD_SNAPSHOT,
    PUBLISHED,
    REFUSED,
    UNCHANGED,
    WOULD_UPGRADE,
    SweepItem,
    SweepResult,
    WarningCounter,
)
from just_dna_registry.testdata import accepted_anyway, test_data_refusal

#: Where a sweep's per-module detail goes: the run's log (INFO), not the terminal.
_sweep_log = logging.getLogger("just_dna_registry.sweep")


class _MaintenanceGroup(TyperGroup):
    """Keeps the subcommand's raw arguments for the run's log, before the group consumes them."""

    def invoke(self, ctx: click.Context) -> object:
        ctx.meta["argv"] = [*getattr(ctx, "_protected_args", []), *ctx.args]
        return super().invoke(ctx)


app = typer.Typer(help="just-dna-registry admin CLI", no_args_is_help=True, cls=_MaintenanceGroup)


def _apply_mode(mode: str | None) -> None:
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
    ctx: typer.Context,
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
    # **Every command is a maintenance run** (0.28.1, `maintenance.py`): logged, the catalog
    # snapshotted before the command acts, its storage writes journaled, and `revert-run` able to undo
    # it. Opened here, in the dispatch, so a new command is one without doing anything.
    command = ctx.invoked_subcommand
    asked_for_help = any(arg in {"--help", "-h"} for arg in ctx.meta.get("argv", []))
    if command is not None and command not in NOT_A_RUN and not asked_for_help:
        settings = get_settings()
        argv = " ".join(shlex.quote(arg) for arg in ctx.meta.get("argv", []))
        ctx.with_resource(
            maintenance_run(settings, command, f"registry --mode {settings.mode} {argv}".rstrip())
        )


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
        return journaled(LocalStorage(settings.local_storage_dir))
    if settings.storage_backend == "hf":
        from just_dna_registry.storage.hf import HfStorage  # imports huggingface_hub lazily

        return journaled(HfStorage(settings.hf_repo_id, token=settings.hf_token))
    raise typer.BadParameter(f"unsupported storage_backend {settings.storage_backend!r}")


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
    if settings.log_file is not None:
        typer.echo(f"logging to {settings.log_file} as well as stdout")
    uvicorn.run(
        "just_dna_registry.api.app:app", host=host, port=resolved, reload=reload,
        log_config=uvicorn_log_config(settings),
    )


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
    site_admin: bool = typer.Option(
        False,
        "--site-admin",
        help="Make the account a registry-wide admin: owner on every existing namespace and org "
             "(yank, amend, publish, grant members). Hard delete stays this CLI's.",
    ),
) -> None:
    """Create an account (if needed), grant it namespaces, and print a fresh API key.

    On an existing account this mints an *additional* key and leaves the old ones working — which
    is also the whole remedy for a user who lost theirs."""
    if account_type not in VALID_ACCOUNT_TYPES:
        raise typer.BadParameter(f"--type must be one of {sorted(VALID_ACCOUNT_TYPES)}")
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)
    repo = Repository(conn)
    try:
        account_id = repo.create_account(account)
    except HandleReserved as exc:
        # Never a new account wearing the old name: the operator almost certainly meant the person.
        typer.echo(f"{account} was renamed to {exc.current}; issue the key to {exc.current}")
        raise typer.Exit(code=1) from exc
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
    if site_admin:
        repo.set_site_admin(account_id, True)
    key = "mk_live_" + secrets.token_urlsafe(24)
    repo.add_api_key(key, account_id)
    admin_note = " site_admin=yes" if repo.is_site_admin(account_id) else ""
    typer.echo(f"account={account} type={account_type} namespaces={namespace}{admin_note}")
    typer.echo(f"API key: {key}")


@app.command("site-admin")
def site_admin_command(
    account: str,
    grant: bool = typer.Option(
        None, "--grant/--revoke", help="Set or clear the flag; omit to show it"
    ),
) -> None:
    """Show, grant or revoke registry-wide admin on an account. Takes effect on the next request,
    including for JWT sessions already issued."""
    settings = get_settings()
    repo = _open_existing_db(settings)
    row = repo.account_by_name(account)
    if row is None:
        typer.echo(f"account not found: {account}")
        raise typer.Exit(code=1)
    if grant is not None:
        repo.set_site_admin(int(row["id"]), grant)
    typer.echo(f"{account}: site_admin={'yes' if repo.is_site_admin(int(row['id'])) else 'no'}")


@app.command("merge-accounts")
def merge_accounts_command(
    source: str = typer.Argument(..., help="The account whose key was lost"),
    into: str = typer.Argument(..., help="The account its owner carried on with"),
    apply: bool = typer.Option(False, "--apply", help="Act; without it, report only"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Fold SOURCE into INTO: namespaces, roles, authored versions, stars and reviews move, and
    SOURCE's API keys are revoked. Reports only unless --apply; snapshots the DB before applying."""
    settings = get_settings()
    repo = _open_existing_db(settings)
    try:
        plan = merge_accounts(repo, settings, source, into, apply=False)
    except LookupError as exc:
        typer.echo(f"account not found: {exc}")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"cannot merge {source} into {into}: {exc}")
        raise typer.Exit(code=1) from exc
    for field, value in plan.model_dump(
        exclude={"source", "into", "applied", "snapshot", "owner_amended", "owner_failed"}
    ).items():
        typer.echo(f"  {field:<24} {value}")
    if not apply:
        typer.echo("dry run: nothing changed (pass --apply to act)")
        return
    if not yes:
        typer.confirm(f"Merge {source} into {into} and revoke {source}'s keys?", abort=True)
    done = merge_accounts(repo, settings, source, into, apply=True, storage=_storage(settings))
    for line in done.owner_failed:
        typer.secho(f"✗ owner not amended: {line}", fg=typer.colors.RED)
    if done.snapshot is None:
        typer.secho("! no pre-flight snapshot taken (auto-backup disabled)", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"snapshot: {done.snapshot}", fg=typer.colors.GREEN)
    typer.echo(f"merged {source} into {into}")


@app.command("rename-account")
def rename_account_command(
    account: str = typer.Argument(..., help="The account's handle (a retired one resolves)"),
    new: str = typer.Argument(..., help="The new handle"),
    apply: bool = typer.Option(False, "--apply", help="Act; without it, report only"),
    allow_test_data: bool = typer.Option(
        False, "--allow-test-data", help="Give a test- handle on production deliberately"
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Rename ACCOUNT to NEW: the old handle stays reserved to it, and `owner` is amended on every
    stored manifest naming any handle of the account (outside the digest; nothing changes identity).
    Reports only unless --apply; snapshots the DB first. Running it again finishes a sweep that a
    storage error interrupted. Not capped by `max_handle_aliases` (that is the self-service limit)."""
    settings = get_settings()
    _echo_mode(settings)
    repo = _open_existing_db(settings)
    storage = _storage(settings)

    def run(act: bool) -> AccountRename:
        try:
            return rename_account(
                repo, storage, settings, account, new,
                apply=act, allow_test_data=allow_test_data, by_admin=True,
            )
        except LookupError as exc:
            typer.echo(f"account not found: {account}")
            raise typer.Exit(code=1) from exc
        except RenameRefused as exc:
            typer.echo(f"cannot rename {account} to {new}: {exc.code}: {exc}")
            raise typer.Exit(code=1) from exc

    plan = run(False)
    for field, value in plan.model_dump(
        exclude={"account", "name", "applied", "amended", "snapshot"}
    ).items():
        typer.echo(f"  {field:<22} {value}")
    if not apply:
        typer.echo(f"dry run: nothing changed (pass --apply to rename {plan.account} to {new})")
        return
    if not yes:
        typer.confirm(
            f"Rename {plan.account} to {new}? {plan.account} stays reserved to the account.",
            abort=True,
        )
    done = run(True)
    if done.snapshot is None:
        typer.secho("! no pre-flight snapshot taken (auto-backup disabled)", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"snapshot: {done.snapshot}", fg=typer.colors.GREEN)
    for line in done.failed:
        typer.secho(f"✗ {line}", fg=typer.colors.RED)
    if done.failed:
        typer.echo("run the same command again to finish the versions above")
    typer.echo(f"renamed {done.account} to {done.name}: {done.amended} manifest(s) amended")


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
    try:
        counts = Repository(conn).import_auth(json.loads(path.read_text(encoding="utf-8")))
    except HandleReserved as exc:
        typer.echo(f"refused, nothing imported: {exc} on this registry, so the export would hand "
                   f"that handle to another account")
        raise typer.Exit(code=1) from exc
    typer.echo("imported " + ", ".join(f"{n} {k}" for k, n in counts.items()))


@app.command("reset-db")
def reset_db(
    keep_keys: bool = typer.Option(
        True, "--keep-keys/--wipe-keys",
        help="Keep accounts + API keys (default), or wipe them too",
    ),
) -> None:
    """Wipe the catalog projection (modules, versions, stars, reviews) — a fresh start. Accounts +
    API keys are **kept** by default (so you don't lock yourself out); `--wipe-keys` clears them too.
    Does NOT touch artifact storage. Requires typing RESET to confirm (destructive)."""
    settings = get_settings()
    scope = "the catalog" if keep_keys else "the catalog AND all accounts + API keys"
    typer.echo(f"This will permanently delete {scope} in {settings.db_path.resolve()}. Artifacts are untouched.")
    if typer.prompt("Type RESET to confirm") != "RESET":
        raise typer.Abort()
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
    if repo.handle_taken(name) is not None:  # a current handle or a retired one (0.28)
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
) -> None:
    """Hard-delete a module (all versions + artifacts). Ops-only; not reversible, not yank."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    storage = _storage(settings)
    if not yes:
        typer.confirm(f"Hard-delete {namespace}/{name} and ALL its artifacts?", abort=True)
    versions = repo.delete_module(namespace, name)
    storage.remove(f"{namespace}/{name}")
    typer.echo(f"removed {namespace}/{name} ({len(versions)} version(s): {versions})")


@app.command("remove-version")
def remove_version(
    namespace: str, name: str, version: str, yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Hard-delete a single version + its artifacts (not yank). Frees it for re-upload."""
    settings = get_settings()
    repo = Repository(connect(settings.db_path))
    storage = _storage(settings)
    if not yes:
        typer.confirm(f"Hard-delete {namespace}/{name}@{version} and its artifacts?", abort=True)
    if not repo.delete_version(namespace, name, version):
        typer.echo(f"not found: {namespace}/{name}@{version}")
        raise typer.Exit(code=1)
    storage.remove(f"{namespace}/{name}/{version}")
    typer.echo(f"removed {namespace}/{name}@{version}")


@app.command("remove-namespace")
def remove_namespace(
    namespace: str, yes: bool = typer.Option(False, "--yes", "-y"),
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
            try:
                pmids = gather_pmids(storage, ns, name, ver, manifest)
                missing = [p for p, exists in verify_pmids(pmids).items() if not exists]
            except (httpx.HTTPError, ValueError) as exc:
                # ValueError: a citing table would not parse, so its PMIDs cannot be listed. Said as a
                # failed check, not as zero PMIDs; revalidate's own status already names the table.
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


def _describe_rederive(prep: VersionUpgradePlan) -> str:
    """The dry run's note on how an acting re-publish enriches (M12): empty when it carries its table."""
    if not prep.rederive:
        return ""
    where = "online" if prep.needs_online else "from the snapshot"
    return f"; re-derive {prep.rederive_subjects} recorded subject(s) {where}"


def _describe_upgrade(prep: VersionUpgradePlan, *, recompile: bool) -> str:
    """One-line summary of what a re-publish of this version would change."""
    bits: list[str] = []
    if prep.variants_plan.needed:
        # Name the columns, not just the row count. An operator reading `990/990 row(s)
        # back-populated` cannot tell which of the six `_UPGRADED_COLUMNS` moved, and on a spec that
        # already authored the 0.3 axes the honest answer is "only `state`" (S15). The changelog this
        # run writes says exactly the same thing; a dry run that summarised it differently from the
        # record it predicts would be its own defect.
        touched = ", ".join(sorted(prep.variants_plan.changed_cells)) or "no existing cell"
        bits.append(
            f"{prep.variants_plan.upgradable_rows}/{prep.variants_plan.total_rows} row(s) "
            f"back-populated (rewrites {touched})"
        )
    if prep.dropped:
        dropped = sum(len(c) for c in prep.dropped.values())
        bits.append(f"{dropped} column(s)/key(s) trimmed")
    if prep.contract_acts:
        bits.append(f"contract recompile — {prep.gap.describe()} (digest moves)")
    if prep.verdict.acts_by_default:
        # Named as a *measurement*, not as a version difference, because that is what makes it act
        # without `--force`: the field was recomputed from this version's own rows and disagreed.
        bits.append(prep.verdict.describe())
    if not bits:  # only a forced schema recompile is left
        bits.append(f"schema recompile, no content change ({prep.gap.describe()})")
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
        help="Recompile even where no gap is detected — a same-contract or unidentifiable version. "
             "A contract gap is found on its own and does NOT need this. Required for --trim",
    ),
    trim: bool = typer.Option(
        False, "--trim",
        help="Drop columns the current contract rejects so a legacy spec compiles (LOSSY — discards "
             "data); requires --force",
    ),
    limit: int = typer.Option(
        0, "--limit", help="Stop after this many versions (0 = no limit). Batch a large migration."
    ),
    online: bool = typer.Option(
        False, "--online",
        help="Let a re-derivation that needs the network (a module carrying an indel) ask live sources. "
             "Without it such a module is held; every other module re-derives from the snapshot",
    ),
    accept_drift: bool = typer.Option(
        False, "--accept-drift",
        help="Publish a re-derivation whose drift wants reading (moved, lost_allele, renamed, "
             "undecided) after you have read it. Aim it with -m",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Print each module's detail (drift, refusal reasons, digests) and upstream warnings on the "
             "terminal too. Without it the terminal gets one line per module and the counts; the run's "
             "log always has everything",
    ),
    jobs: int = typer.Option(
        None, "--jobs", "-j", min=1,
        help="Modules re-published at once under --apply (default REGISTRY_UPGRADE_JOBS, 4). Overlaps "
             "their waits; live requests still pace through one shared client bundle",
    ),
) -> None:
    """Migrate published versions to the current `just-dna-format` contract and re-publish as a PATCH.

    **Two gaps, both detected, neither needing a flag.** A *data* gap is the additive 0.3 axes
    (direction/stat_significance/clin_sig) back-populated from the legacy `state`/booleans. A
    *contract* gap is a version whose parquet was compiled under an older contract than this server
    runs — measured by comparing its `compilation.compiler_version` stamp against the installed
    compiler under the same rule the wire check uses, so a 0.5-compiled artifact in a 0.6 catalog is
    found the way a 0.5 client talking to a 0.6 server is.

    So a catalog-wide re-baseline is `--apply`, and `--force` is an override again: it recompiles where
    there is *no* detectable gap — a same-contract version, or one whose compiler cannot be identified
    (counted and named in the summary rather than silently skipped). A compiler **patch** difference is
    deliberately not a gap: it moves no schema, so acting on it would mint a PATCH per module for a
    dependency bump and the sweep would restart with every upstream patch release.

    `--trim` drops columns 0.4 now forbids (old schemas only warned) so a stale spec compiles — LOSSY,
    so it requires `--force`. A version with such columns and no `--trim` is reported *blocked*.
    Re-publish runs the full server-side compile path; the predecessor is never mutated. Dry-run by
    default. See docs/UPGRADE.md.

    **A stored `resolution.csv` written before format 0.8 is re-derived, not carried** (M12): detected
    from its rows, never a flag. It needs the new Ensembl snapshot on the box (checked before anything
    re-derives), the network for a module with an indel (`--online`), and a person to read drift that
    moved an answer (`--accept-drift`, after reading). A held or refused module is reported and the
    sweep goes on.

    **The terminal gets one line per module** (published, refused/held with its code, unchanged with
    its bucket, failed with the exception's type) and, at the end, counts by type; every detail line and
    every upstream warning is in the run's `run.log` (`--verbose` prints them too). A module that fails
    unexpectedly is reported and the sweep goes on; the command then exits 1.

    **`--apply` re-publishes `--jobs` modules at once** (default 4). Planning stays in catalog order on
    one thread; each module's line is printed whole when it finishes, so the order is completion order."""
    if trim and not force:
        raise typer.BadParameter("--trim is lossy (it drops columns); re-run with --force to confirm")
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)
    result = _upgrade_sweep(
        settings, Repository(conn), _storage(settings), namespace=namespace, module=module,
        apply=apply, force=force, trim=trim, limit=limit, online=online, accept_drift=accept_drift,
        verbose=verbose, jobs=jobs or settings.upgrade_jobs,
    )
    if result.count(FAILED):
        raise typer.Exit(code=1)


def _act_codes(prep: VersionUpgradePlan, *, recompile: bool) -> str:
    """Why a version acts, as codes read off the plan's own fields: the terminal's `[...]` on its line."""
    codes: list[str] = []
    if prep.variants_plan.needed:
        codes.append("data_gap")
    if prep.dropped:
        codes.append("trim")
    if prep.contract_acts:
        codes.append("contract_gap")
    if prep.verdict.acts_by_default:
        codes.append("output_drift")
    if not codes and recompile:
        codes.append("forced")
    if prep.rederive:
        codes.append("rederive_online" if prep.needs_online else "rederive_snapshot")
    return f"[{', '.join(codes)}]"


def _emit(item: SweepItem, *, verbose: bool) -> None:
    """Print one module's outcome whole, after it is done; its detail goes to the run's log.

    One call per stream, so a sweep that processes modules concurrently still prints whole lines and
    logs whole blocks. The detail record is INFO: the run's file handler takes it and the terminal's
    (WARNING) does not, which is the whole of "full details in the log". `--verbose` prints it instead.
    """
    colour = {
        PUBLISHED: typer.colors.GREEN, REFUSED: typer.colors.RED, FAILED: typer.colors.RED,
        BLOCKED: typer.colors.RED, ANOMALY: typer.colors.RED, HELD: typer.colors.YELLOW,
    }.get(item.status)
    if verbose:
        typer.secho(item.block(), fg=colour)
        return
    typer.secho(item.head, fg=colour)
    if item.detail:
        _sweep_log.info("%s", item.block())


@dataclass
class _ToPublish:
    """A version the plan says acts under `--apply`: what its worker needs, and its line's parts."""

    label: str
    namespace: str
    name: str
    version: str
    manifest: ModuleManifest
    prep: VersionUpgradePlan
    codes: str
    described: str
    online_subjects: int


def _sweep_one(
    settings: Settings,
    storage: StorageBackend,
    row: Any,
    *,
    apply: bool,
    force: bool,
    trim: bool,
    online: bool,
    snapshot_problem: str | None,
) -> SweepItem | _ToPublish:
    """One latest version's plan: what became of it, or, under `--apply`, the re-publish to run."""
    ns, name, ver = row["namespace"], row["name"], row["version"]
    label = f"{ns}/{name}@{ver}"
    manifest = ModuleManifest.model_validate_json(row["manifest_json"])
    prep = prepare_version_upgrade(storage, ns, name, ver, manifest, trim=trim)
    if prep is None:  # spec inputs not retrievable (legacy import)
        return SweepItem(label, UNCHANGED, "no_spec_inputs", f"· {label}: unchanged no_spec_inputs")
    if prep.blocked:
        return SweepItem(
            label, BLOCKED, "contract_rejects", f"✗ {label}: blocked contract_rejects (--trim --force)",
            [f"{f}: {', '.join(c)}" for f, c in prep.blocked.items()],
        )
    if not prep.would_act(recompile=force):
        if prep.verdict.anomaly:
            return SweepItem(
                label, ANOMALY, "identical_compiler_drift", f"! {label}: anomaly identical_compiler_drift",
                [prep.verdict.describe()],
            )
        bucket = (
            "compiler_unidentifiable" if prep.gap.scale == GAP_UNKNOWN
            else "patch_gap" if prep.gap.scale == GAP_PATCH
            else "current"
        )
        return SweepItem(label, UNCHANGED, bucket, f"· {label}: unchanged {bucket}")
    if prep.rederive and snapshot_problem:
        return SweepItem(label, HELD, HELD_SNAPSHOT, f"… held {label}: {HELD_SNAPSHOT}", [snapshot_problem])
    if prep.needs_online and not online:
        return SweepItem(
            label, HELD, HELD_NEEDS_ONLINE, f"… held {label}: {HELD_NEEDS_ONLINE}",
            ["carries an indel, which offline 0.8 cannot left-align; needs --online"],
        )
    codes = _act_codes(prep, recompile=force)
    described = f"{_describe_upgrade(prep, recompile=force)}{_describe_rederive(prep)}"
    online_subjects = prep.rederive_subjects if prep.needs_online else 0
    if not apply:
        return SweepItem(
            label, WOULD_UPGRADE, "next_patch", f"⇧ {label}: would upgrade {codes} → next PATCH", [described],
            online_subjects=online_subjects,
        )
    return _ToPublish(label, ns, name, ver, manifest, prep, codes, described, online_subjects)


def _failed(label: str, exc: Exception) -> SweepItem:
    """A module that failed unexpectedly: reported, never fatal to the sweep.

    Through 0.28.1 an unexpected error ended the sweep at that module and left the rest of the catalog
    unvisited. The traceback is the log's; the terminal says which module and what kind of failure, and
    `upgrade` exits 1 at the end. INFO, so the traceback reaches the log and not the terminal (whose
    handler takes ERROR)."""
    _sweep_log.info("%s failed", label, exc_info=exc)
    return SweepItem(
        label, FAILED, type(exc).__name__, f"✗ {label}: failed {type(exc).__name__}",
        [f"{type(exc).__name__}: {exc}"],
    )


def _sweep_db_file(repo: Repository) -> str | None:
    """The file behind `repo`'s connection, for a worker to open its own, or `None` to share it.

    A worker gets a connection of its own so no thread reads or commits on another's. Shared instead
    when there is no file (an in-memory catalog) or the caller holds an open transaction, which a
    second connection would wait on until sqlite's busy timeout."""
    if repo.conn.in_transaction:
        return None
    for row in repo.conn.execute("PRAGMA database_list").fetchall():
        if row[1] == "main" and row[2]:
            return row[2]
    return None


def _publish_one(
    settings: Settings,
    repo: Repository,
    db_file: str | None,
    storage: StorageBackend,
    todo: _ToPublish,
    *,
    force: bool,
    trim: bool,
    online: bool,
    accept_drift: bool,
) -> SweepItem:
    """One planned re-publish, on a worker thread, as the item the main thread prints and counts."""
    label, manifest = todo.label, todo.manifest
    try:
        own = Repository(connect(Path(db_file))) if db_file else repo
        try:
            result = upgrade_version(
                repo=own, storage=storage, settings=settings,
                namespace=todo.namespace, name=todo.name, version=todo.version, manifest=manifest,
                recompile=force, trim=trim, prepared=todo.prep, online=online, accept_drift=accept_drift,
            )
        finally:
            if own is not repo:
                own.conn.close()
    except UpgradeHeld as exc:
        return SweepItem(label, HELD, exc.code, f"… held {label}: {exc.code}", [str(exc)])
    except PublishError as exc:
        return SweepItem(
            label, REFUSED, exc.detail, f"✗ {label}: {exc.detail}", list(exc.errors),
            online_subjects=todo.online_subjects,
        )
    except Exception as exc:  # one module's failure is reported, not fatal
        return _failed(label, exc)
    if result is None:
        return SweepItem(label, UNCHANGED, "current", f"· {label}: unchanged current")
    new_version, new_manifest = result
    return SweepItem(
        label, PUBLISHED, new_version, f"✓ {label} → {new_version} {todo.codes}",
        [todo.described, f"digest {manifest.artifact.digest[:23]}… → {new_manifest.artifact.digest[:23]}…"],
        warnings_summary=dict(new_manifest.compilation.warnings_summary),
        online_subjects=todo.online_subjects,
    )


def _upgrade_sweep(
    settings: Settings,
    repo: Repository,
    storage: StorageBackend,
    *,
    namespace: str | None,
    module: str | None,
    apply: bool,
    force: bool,
    trim: bool,
    limit: int,
    online: bool,
    accept_drift: bool,
    verbose: bool = False,
    jobs: int = 1,
) -> SweepResult:
    """The sweep `registry upgrade` runs, over a given catalog and storage.

    Separate from the command so `replay-upgrade` runs the same code over a scratch copy of the
    catalog and a storage overlay, which is what makes its report the one the lost run printed. It
    returns every module's outcome (`SweepResult`), which is what the replay reads, and prints one line
    per module and the counts at the end; the detail is in the run's log (`sweep_report`).

    **Planned on this thread, re-published on `jobs` workers.** Each version's plan (acts, held,
    blocked, unchanged) is read in catalog order here; under `--apply` an acting version goes to a
    worker, at most `jobs` at once so at most that many modules' files are in memory, and its line is
    emitted here when it finishes, so `result.items` is in completion order. Workers share the storage
    backend (the publish path commits one at a time and the run's journal is thread-safe) and open
    their own catalog connection. What they overlap is the enrichment's and the compile's waiting; live
    egress paces through the shared client bundle whatever the count. `--limit` counts versions that
    would act or were handed to a worker.
    """
    _echo_mode(settings)
    # Echoed for the reason the mode is: a switch is invisible until a rule fires, minutes in.
    typer.echo(
        "re-derive: online where a module carries an indel, snapshot only elsewhere" if online
        else "re-derive: snapshot only; a module carrying an indel is held (pass --online)"
    )
    # Asked once, up front, and before any PATCH is minted: re-deriving against the old release reads
    # the old answers back into a permanent successor (`snapshot_not_current`).
    snapshot_problem = (
        snapshot_not_current(settings) if enricher_available()
        else "just-dna-enricher is not installed (install the `server` extra)"
    )
    if snapshot_problem:
        typer.secho(f"re-derive refused for every module that needs it: {snapshot_problem}",
                    fg=typer.colors.YELLOW)
    result = SweepResult()
    counter = WarningCounter()
    root_logger = logging.getLogger()
    root_logger.addHandler(counter)
    workers = max(1, jobs)
    db_file = _sweep_db_file(repo)
    pending: set[Future[SweepItem]] = set()
    handed = 0

    def report(item: SweepItem) -> None:
        """Record one module's outcome and print its line whole, on this thread only."""
        result.items.append(item)
        _emit(item, verbose=verbose)

    def collect(at_most: int) -> None:
        """Report every finished worker, waiting until no more than `at_most` are still running."""
        while pending:
            done = {f for f in pending if f.done()}
            if not done and len(pending) <= at_most:
                return
            if not done:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                pending.discard(future)
                report(future.result())

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="upgrade") if apply else None
    # A warning an upstream logs (the enricher's re-derivation drift, a placement note) is counted on
    # the summary and kept whole in the run's log, rather than printed between the module lines.
    with quiet_console(enabled=not verbose):
        try:
            # The 0.5 migration roughly doubles the catalog's version count and runs a full
            # enrich+compile per module, so it is the longest ops operation the registry has. `--limit`
            # makes it batchable.
            for row in repo.list_all_versions(namespace):
                acted = result.count(WOULD_UPGRADE) + handed
                if limit and acted >= limit:
                    typer.echo(f"\n(stopping at --limit {limit}; re-run to continue)")
                    break
                if module is not None and row["name"] != module:
                    continue
                # Only the latest version is upgrade-eligible — a superseded older version is
                # immutable and already replaced, so re-upgrading it would mint an endless chain.
                if not is_latest_version(repo, row["namespace"], row["name"], row["version"]):
                    continue
                label = f"{row['namespace']}/{row['name']}@{row['version']}"
                try:
                    planned = _sweep_one(
                        settings, storage, row, apply=apply, force=force, trim=trim,
                        online=online, snapshot_problem=snapshot_problem,
                    )
                except Exception as exc:  # one module's failure is reported, not fatal
                    planned = _failed(label, exc)
                if isinstance(planned, SweepItem):
                    report(planned)
                    continue
                assert pool is not None  # a re-publish is planned only under --apply
                # At most `workers` running: their files are in memory until they finish.
                collect(at_most=workers - 1)
                handed += 1
                pending.add(pool.submit(
                    _publish_one, settings, repo, db_file, storage, planned,
                    force=force, trim=trim, online=online, accept_drift=accept_drift,
                ))
            collect(at_most=0)
        finally:
            if pool is not None:
                # Reached early only by an interrupt: what has not started is dropped, what is running
                # finishes (a thread cannot be stopped), and whatever finished still published, so it
                # is still reported.
                for future in pending:
                    future.cancel()
                pool.shutdown(wait=True)
                for future in list(pending):
                    if not future.cancelled() and future.exception() is None:
                        report(future.result())
            root_logger.removeHandler(counter)
    result.logged_warnings = counter.by_logger
    _sweep_summary(result, apply=apply, force=force)
    if (run := active_run()) is not None:
        write_sweep(run, result.to_json())
    return result


def _sweep_summary(result: SweepResult, *, apply: bool, force: bool) -> None:
    """The sweep's last lines: the distribution, the counts by type, and the notes once per sweep."""
    blocked, refused, held = result.count(BLOCKED), result.count(REFUSED), result.count(HELD)
    failed = result.count(FAILED)
    blocked_note = f", {blocked} blocked (need --trim --force)" if blocked else ""
    if refused:
        blocked_note += f", {refused} refused (above)"
    if held:
        blocked_note += f", {held} held"
    if failed:
        blocked_note += f", {failed} failed"
    if apply:
        typer.echo(f"\n{result.count(PUBLISHED)} version(s) upgraded and re-published{blocked_note}")
    else:
        typer.echo(
            f"\n{result.count(WOULD_UPGRADE)} version(s) would upgrade{blocked_note}  "
            "(dry-run; pass --apply to publish)"
        )
    for line in result.problem_lines():
        typer.echo(f"by type: {line}")
    for line in result.warning_lines():
        typer.echo(line)
    run = active_run()
    if run is not None:
        typer.echo(f"full detail: {run.path / LOG_FILE}")
    if any(item.online_subjects for item in result.items):
        typer.echo(
            f"online re-derivation re-asks {sum(item.online_subjects for item in result.items)} recorded "
            "subject(s) from this process's own pacing, which a running server does not share: run it in "
            "a quiet window"
        )
    if any(item.status == REFUSED and item.code == "rederive_drift_needs_reading" for item in result.items):
        typer.echo(
            "A `rederive_drift_needs_reading` refusal lists each subject before → after in the run's log; "
            "once read, re-run with -m <module> --accept-drift."
        )
    # **An anomaly is not a gap and is not actionable, so it is said on its own.** Drift measured
    # against the identical compiler cannot be repaired by recompiling — the recompile derives the same
    # value — so the sweep says so rather than looping. Red, because unlike everything else here it
    # means a published manifest disagrees with the compiler that allegedly produced it.
    anomalies = [item.label for item in result.items if item.status == ANOMALY]
    if anomalies:
        typer.secho(
            f"{len(anomalies)} version(s) with drift measured against the identical compiler ("
            + _listed(anomalies)
            + "). Recompiling reproduces it, so this sweep will not act; investigate the stored inputs "
            "or the manifest.",
            fg=typer.colors.RED,
        )
    # **A patch is not a gap, and a patch bucket is not nothing** (0.20.1). The rule is unchanged: a
    # compiler patch moves no schema, so acting on one merely because the version differs would mint a
    # PATCH per module every time a dependency moved. What was wrong was reporting the decision as
    # *silence* — `0 version(s) would upgrade` with no mention that versions sat on a different
    # compiler.
    #
    # **Since 0.21 the message is narrower, and the narrowing is the release.** The probed fields are
    # recomputed from each version's own rows, so a patch that moved one is found and acted on under
    # plain `--apply`. What is left in this bucket is the genuinely unanswerable half: the surfaces
    # that need the compile we are avoiding. `--force` is how an operator acts on those — a fallback
    # for a case the detector cannot reach, rather than the everyday lever it had to be for
    # `stats.genes` in 0.20.
    patch_gap = [item.label for item in result.items if item.code == "patch_gap"]
    if patch_gap and not force:
        typer.secho(
            f"{len(patch_gap)} version(s) sit on a different compiler patch ({_listed(patch_gap)}). "
            "Every probed field was recomputed and is current; what cannot be checked without "
            f"recompiling is {', '.join(UNPROBED_SURFACES)}. Check the upstream changelog for the "
            "interval, and re-run with --force -m <module> if it moved one of those.",
            fg=typer.colors.YELLOW,
        )
    # Counted rather than merely skipped. A version this planner cannot date is the one shape that
    # reads identically to "already current", which is the confusion that made `--force` the normal
    # path in the first place — so it gets its own number and a name an operator can aim
    # `--force -m <module>` at.
    unidentifiable = [item.label for item in result.items if item.code == "compiler_unidentifiable"]
    if unidentifiable and not force:
        typer.secho(
            f"{len(unidentifiable)} version(s) skipped because the compiler that produced them "
            f"cannot be identified — unchecked, not up to date: {_listed(unidentifiable)}. "
            "Re-run with --force to recompile them anyway.",
            fg=typer.colors.YELLOW,
        )


def _listed(labels: list[str]) -> str:
    return ", ".join(labels[:5]) + (f" … ({len(labels)} total)" if len(labels) > 5 else "")


@app.command("list-runs")
def list_runs_command() -> None:
    """Maintenance runs, oldest first: what each command changed, whether it was reverted or pruned,
    and what it holds on disk, with the total."""
    settings = get_settings()
    runs = list_runs(settings)
    if not runs:
        typer.echo(f"no runs under {run_root(settings)}")
        return
    total = 0
    for path in runs:
        record = read_record(path)
        if record.get("pruned"):
            state = f"pruned {record['pruned']}"
        elif record.get("reverted_by"):
            state = f"reverted by {record['reverted_by']}"
        elif record.get("changed"):
            state = "changed"
        else:
            state = "no change"
        size = disk_usage(path)
        total += size
        typer.echo(
            f"{record['id']}\t{record.get('outcome')}\t{state}\t{human_size(size)}\t{record.get('invocation')}"
        )
    # Every command also copies the catalog before it acts and drops the copy if nothing changed, so a
    # command briefly needs about the DB's size free on this volume, on top of what is listed here.
    typer.echo(
        f"total {human_size(total)} in {len(runs)} run(s) under {run_root(settings)}; a command also needs "
        f"about {human_size(disk_usage(settings.db_path.resolve()))} free while it runs (the catalog copy)"
    )


@app.command("prune-runs")
def prune_runs_command(
    keep: int = typer.Option(
        None, "--keep", min=1,
        help="Revertible runs (and replays) to keep whole. Default: REGISTRY_RUN_KEEP, or 2 when that is 0",
    ),
    apply: bool = typer.Option(False, "--apply/--dry-run", help="Delete (default: list what would go)"),
) -> None:
    """Free the disk old runs hold, keeping their logs.

    Keeps the newest revertible runs whole, and the newest `replay-upgrade` scratch trees; every other run
    loses its catalog snapshot, journal, `storage/` and `replay/` and keeps `run.log` and `run.json`,
    marked `pruned`, so `revert-run` refuses it by name. Revert goes newest first, so pruning the older
    runs never strands one that could still be reverted. The same prune runs at the end of every command
    (`REGISTRY_RUN_KEEP`); this is for room now. Not a run itself: it would copy the catalog in order to
    delete catalog copies."""
    settings = get_settings()
    keep = keep or settings.run_keep or 2
    plan = plan_prune(settings, keep)
    if not plan.prune:
        typer.echo(f"nothing to prune (keeping the newest {keep} revertible run(s) and replay(s) whole)")
        return
    for name, size in plan.prune:
        typer.echo(f"  {name}\t{human_size(size)}")
    if not apply:
        typer.echo(
            f"dry run: {len(plan.prune)} run(s) would be pruned, {human_size(plan.freed)} freed "
            f"(keeping {keep} whole). Re-run with --apply."
        )
        return
    freed = apply_prune(settings, plan)
    typer.secho(f"pruned {len(plan.prune)} run(s), {human_size(freed)} freed", fg=typer.colors.GREEN)


@app.command("revert-run")
def revert_run_command(
    run_id: str = typer.Argument(..., help="A run id from `list-runs`"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    force: bool = typer.Option(
        False, "--force",
        help="Restore even over later runs or changes made since (destroys them)",
    ),
) -> None:
    """Undo a maintenance run: its stored files back as they were, then its catalog snapshot.

    Newest first: a run with a later unreverted change is refused, as is one whose catalog or stored
    files moved since it ended (a server's write, another command), unless --force. Stop the server
    before reverting; the revert itself is a run, so it can be reverted in turn."""
    settings = get_settings()
    if not yes:
        typer.confirm(f"Revert run {run_id} in {settings.db_path.resolve()}?", abort=True)
    try:
        report = revert_run(settings, run_id, _storage(settings), force=force)
    except RevertRefused as exc:
        typer.secho(f"refused: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.secho(
        f"reverted {report.run_id}: {report.files_restored} stored file(s) restored, "
        f"{report.files_removed} removed, catalog "
        + ("restored from its snapshot" if report.db_restored else "removed (none existed before)"),
        fg=typer.colors.GREEN,
    )


@app.command("replay-upgrade")
def replay_upgrade_command(
    since: str = typer.Option(
        None, "--since", help="Only successors created at or after this ISO time (e.g. 2026-11-06)"
    ),
    compiler: str = typer.Option(
        None, "--compiler", help="Only successors whose compiler_version starts with this, e.g. 0.8"
    ),
    online: bool | None = typer.Option(
        None, "--online/--offline",
        help="The original run's switch. Default: read off a successor's changelog; refused when none says",
    ),
    namespace: str = typer.Option(None, "--namespace", "-n"),
    module: str = typer.Option(None, "--module", "-m"),
    jobs: int = typer.Option(
        None, "--jobs", "-j", min=1,
        help="Modules replayed at once (default REGISTRY_UPGRADE_JOBS, 4), as `upgrade --jobs`",
    ),
) -> None:
    """Recover a lost `upgrade --apply` report by replaying the sweep from the published successors'
    predecessors, on a scratch copy of the catalog and a storage overlay. Writes nothing to the live
    catalog or storage; the replay's DB and files stay in its run's directory (`list-runs`).

    It prints the sweep's own report (held modules and why, each refusal with its drift), then compares
    each replayed successor with the published one. With --online it re-asks live sources, so an answer
    that moved since the original run shows up as a difference; it spends the same egress budget."""
    settings = get_settings()
    # Inside the run's own directory: `replay-upgrade` keeps its run (ALWAYS_LOG), so its report and
    # the scratch catalog it was read from stay together under one id.
    run = active_run()
    workdir = (run.path if run is not None else settings.db_path.resolve().parent / "replays") / "replay"
    try:
        replay_upgrade(
            settings, _storage(settings), sweep=_upgrade_sweep, since=since, compiler=compiler,
            online=online, namespace=namespace, module=module, workdir=workdir,
            jobs=jobs or settings.upgrade_jobs,
        )
    except ReplayRefused as exc:
        typer.secho(f"refused: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


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
    checks: bool = typer.Option(
        False, "--checks/--no-checks",
        help="The ACMG SF list read by the `?acmg=` pass. Buildable only, from your own workbook",
    ),
    lane: list[str] = typer.Option(
        [], "--lane",
        help="Provision a lane by name, repeatable. Accepts lanes no pass here reads (`registry "
             "warm-caches` with no --apply lists every one).",
    ),
    every: bool = typer.Option(
        False, "--all", help="Every lane the enricher knows about, not only the ones read here"
    ),
    proxy: bool = typer.Option(
        False, "--proxy",
        help="The lanes the caching proxy's routes open (`/hint/*`, `POST /drafts`, `POST .../derived`) "
             "and the parents they build from: the authoring surface, without `--all`'s rest",
    ),
    exclude: list[str] = typer.Option(
        [], "--exclude",
        help="Leave a lane out, repeatable. Applied last, so it overrides --all, --proxy, a group flag, "
             "--lane and the default resolution pair",
    ),
    source: list[str] = typer.Option(
        [], "--source",
        help="`<lane>=<path>` for a lane that builds from a file you hold (ACMG's workbook, a "
             "ClinVar VCF). Repeatable.",
    ),
    pin: list[str] = typer.Option(
        [], "--pin",
        help="`<lane>=<release>` for a lane that builds a dated release (MANE, CIViC, STRchive). "
             "A lane that needs one and does not get it reports could-not-run rather than building "
             "whatever is upstream today. Repeatable.",
    ),
    use: str | None = typer.Option(
        None, "--use",
        help=(
            "Declared use for the gated snapshots: unstated | non_commercial | commercial. "
            "Downloading is *taking* the data, so the terms apply here. Defaults to "
            "REGISTRY_DECLARED_USE."
        ),
    ),
    apply: bool = typer.Option(False, "--apply/--dry-run"),
) -> None:
    """Provision the reference snapshots enrichment needs.

    **Run this before pointing a deployment at a new format minor.** Publishing enriches before it
    compiles, and with strict compiles on, a server holding no snapshot cannot publish an
    rsID-authored module at all — it refuses rather than emitting a partial artifact.

    The dry run (the default) reports what the *running server* would find, using the same explicit
    cache paths and the same resolvers, so it doubles as a health check. It lists **every lane the
    enricher knows about**, not only the ones selected, because a lane nobody told you existed is a
    lane you cannot decide about. `--apply` provisions the selected ones.

    **Each lane is provisioned by its own route, and the route is not a flag** (format 0.7, RM176).
    A lane with a published snapshot is pulled; one without is unpublished for a recorded reason —
    PharmVar's personal, non-transferable key, ACMG's Elsevier supplementary material, NCBI's policy
    on MANE — and building locally is the only route there will ever be. `cache pull` stopped at the
    first kind, which is how a deployment came to run with buildable caches permanently absent and
    the checks that read them skipping themselves. A present cache is left alone, so re-running is
    cheap and safe — **with one exception**: a present *derived* lane (built locally from parents
    already on disk) whose `release.json` names an older enricher than the installed one is rebuilt
    beside itself and swapped in, the previous build kept as `<lane>.pre-<version>`. Without it an
    upstream correction to a derivation (RM293) never reaches a box that built the lane once.

    **And a present *pulled* lane whose pull record names another repo, or none, is handed to the
    provisioner** (0.28.1). Format 0.8 moved Ensembl to a new repo under the same file names, so a 0.7
    cache reads as present; upstream re-pulls it, or checks a record-less one against the published
    files once. The dry run marks these `⟳`, and `--apply` reads each record back afterwards.

    **Each lane is tagged with what in this server opens it** (`services/lane_readers.py`): `publish`
    (every enrichment), `check: <group>`, `proxy: hints / drafts / derived`, `builds: <lane>`, or
    `[nothing here]`. `--proxy` selects the caching proxy's lanes and their build parents, the
    authoring surface without the rest of `--all`; `--exclude LANE` (repeatable) is applied last and
    overrides every flag that adds, so `--all --exclude alphagenome_avi` is everything but that one.

    Groups, because they gate different things. **Resolution** (ensembl, clinvar) decides whether a
    publish works. **PGx** (cpic, clinpgx, pharmvar — `--pgx`) is what makes a *hosted* `?pgx=` check
    legitimate rather than merely possible: without a snapshot the alternatives are fetching a source
    that forbids sale live, per request, on the operator's own acceptance, or skipping the check;
    both published rate figures are per IP, so a server multiplies its callers onto one allowance.
    **Checks** (acmg — `--checks`) is the SF secondary-findings list; without it the pass falls back
    to a live page, which served SF v3.2 while the current list is v3.3 — a check quietly answering
    about last year's genes. **Metrics** (constraint — `--constraint`) gates nothing here yet: the
    gene-metrics pass writes an authored sidecar and this service never runs it, so its absence is
    never reported as a finding about a module.

    **`--use` applies to the licence-gated lanes and to nothing else.** Under a data-usage policy the
    terms are accepted when the data is *taken*, so `unstated` skips them and `commercial` refuses.
    Checked before the fetch, never after: refusing means nothing was taken, which is the whole point
    of gating at acquisition. Ensembl, ClinVar and gnomAD never ask.
    """
    settings = get_settings()
    from just_dna_registry.services.enrich import (
        CHECK_REFERENCES,
        METRICS_REFERENCES,
        PGX_REFERENCES,
        RESOLUTION_REFERENCES,
        cache_lanes,
        derived_lane_ages,
        enricher_available,
        export_lane_locations,
        gated_lanes,
        lane_destinations,
        lane_presence,
        lanes_to_repull,
        provisionable_lanes,
        pullable_lanes,
        rebuild_derived_lane,
        repull_left_undone,
    )
    from just_dna_registry.services.lane_readers import lane_readers, proxy_lanes, reader_tag

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

    lanes = cache_lanes()
    known = provisionable_lanes()
    unknown = [name for name in [*lane, *exclude] if name not in lanes]
    if unknown:
        typer.secho(
            f"unknown lane(s): {', '.join(sorted(unknown))}. This enricher knows "
            f"{', '.join(known)}.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    pins, sources = _lane_pairs(pin, "--pin", lanes), _lane_pairs(source, "--source", lanes)

    groups: tuple[tuple[str, tuple[str, ...], bool], ...] = (
        ("resolution", RESOLUTION_REFERENCES, True),
        ("metrics", METRICS_REFERENCES, constraint),
        ("pgx", PGX_REFERENCES, pgx),
        ("checks", CHECK_REFERENCES, checks),
    )
    selected: set[str] = set(lane)
    if every:
        selected |= set(known)
    if proxy:
        selected |= proxy_lanes()
    for _label, names, wanted in groups:
        if wanted:
            selected |= set(names)
    # The two resolution lanes are individually switchable because they are the two a publish needs.
    if not ensembl:
        selected.discard("ensembl")
    if not clinvar:
        selected.discard("clinvar")
    # Last, so it overrides every flag that adds: the one way to say "all of them but that 30 GB one".
    selected -= set(exclude)

    readers = lane_readers()
    # **Every lane, not the seven a pass here opens.** `available_references` is keyed by
    # `REFERENCE_NAMES` and is right to be — it feeds the boot gate and the `/check` notes — but a
    # report has a different job from a gate, and reading presence out of it gave `None` for the
    # lanes it does not cover: a provisioned `civic` or `mitomap` could never render as present, and
    # under `--all` it rendered as missing and was queued for a download of bytes already on disk.
    present = lane_presence(settings)
    pullable, gated = pullable_lanes(), gated_lanes()
    # A present derived lane built by an older enricher is rebuilt whether or not it was selected:
    # it is already here, so the operator chose to have it, and `prepare_lane` alone would keep the
    # old derivation forever. See `LaneAge` for why only derived lanes.
    ages = {age.lane: age for age in derived_lane_ages(settings)}
    # A present pulled lane whose record names another repo, or no repo (`lanes_to_repull`).
    repull = lanes_to_repull(present, selected)

    typer.secho("lanes:", bold=True)
    missing: list[str] = []
    stale: list[str] = []
    for name in known:
        lane_obj = lanes[name]
        where = present.get(name)
        tag = reader_tag(readers.get(name, ()))
        age = ages.get(name)
        if where is not None and name in repull:
            typer.secho(f"  ⟳ {name} {tag}: {where} — {repull[name]}", fg=typer.colors.YELLOW)
            missing.append(name)
        elif where is not None and age is not None and age.stale:
            typer.secho(
                f"  ⟳ {name} {tag}: {where} — built by enricher {age.built_by}, {age.installed} is "
                f"installed; rebuild",
                fg=typer.colors.YELLOW,
            )
            stale.append(name)
        elif where is not None and age is not None and age.stale is None:
            typer.echo(
                f"  ✓ {name} {tag}: {where} (builder version unrecorded, so staleness cannot be "
                f"judged; `just-dna-enricher cache rebuild --only {name}` to be sure)"
            )
        elif where is not None:
            typer.echo(f"  ✓ {name} {tag}: {where}")
        elif name in exclude:
            typer.echo(f"  – {name} {tag}: excluded")
        elif name not in selected:
            typer.echo(f"  – {name} {tag}: not selected")
        elif name in pullable:
            # **A gated lane says what the gate is, in the listing.** `--apply` already prints
            # upstream's full sentence ("clinpgx forbids sale and no use was declared…"), but the
            # listing is what an operator reads *first* and decides from, and "(licence-gated)" alone
            # named neither the source, the term, nor the flag. Beside `pharmvar`, which carries its
            # whole reason, it read as an unexplained failure of the same kind — the "a new report
            # field is only half a fix" rule, at the renderer.
            forecast = _gate_forecast(lane_obj, declared) if name in gated else "pull"
            typer.secho(
                f"  ✗ {name} {tag}: not provisioned — {forecast}", fg=typer.colors.YELLOW
            )
            missing.append(name)
        elif lane_obj.rebuild is not None:
            # Not a failure to report as one. Nothing publishes it, and the lane says why in its own
            # words — which is the sentence an operator can act on, unlike a red cross.
            typer.secho(
                f"  ✗ {name} {tag}: not provisioned — build ({lane_obj.unpublished or 'unpublished'})",
                fg=typer.colors.YELLOW,
            )
            missing.append(name)
        else:
            typer.secho(
                f"  ✗ {name} {tag}: no route in this tier ({lane_obj.unbuilt or 'unbuildable'})",
                fg=typer.colors.YELLOW,
            )

    if not missing and not stale:
        typer.secho("\nEvery selected lane is present.", fg=typer.colors.GREEN)
        return
    if not apply:
        if missing:
            typer.echo(
                f"\n{len(missing)} lane(s) to provision or re-pull: {', '.join(missing)}. "
                f"Re-run with --apply (this takes a while and a lot of disk)."
            )
        if stale:
            typer.echo(
                f"\n{len(stale)} derived lane(s) to rebuild: {', '.join(stale)}. Re-run with --apply "
                f"(local, no network; the previous build is kept beside it)."
            )
        raise typer.Exit(code=1)

    # **After the report, before the provisioning.** The report answers "what would the running
    # server find", which is this deployment's own resolvers; the provisioning happens inside the
    # enricher, whose lane ladder reads its own variables — so the configured paths are published
    # into them first, or a pull lands somewhere the server never looks.
    for var, value in sorted(export_lane_locations(settings).items()):
        typer.echo(f"  · {var}={value}")

    rebuild_failures = 0
    for name in stale:
        built, detail = rebuild_derived_lane(settings, ages[name])
        if built is True:
            typer.secho(f"✓ {name}: rebuilt — {detail}", fg=typer.colors.GREEN)
        elif built is None:
            typer.secho(f"– {name}: {detail}", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"✗ {name}: rebuild FAILED — {detail}", fg=typer.colors.RED, err=True)
            rebuild_failures += 1

    # **ACMG before the enricher gets a say, because the enricher has no route for it here.** Its
    # only build path needs `openpyxl` (a `[dev]` extra upstream, in no extra of ours), so
    # `prepare_caches` can only report the lane as unbuildable. Fetching the built list is the route,
    # and `--source acmg=<workbook>` still wins for an operator who does have the build extra.
    fetch_failures = rebuild_failures
    if "acmg" in missing and "acmg" not in sources:
        # `lane_destinations` returns None to mean *the lane's own default*, not "unresolved" — and
        # by here `export_lane_locations` has already published any configured path into
        # `JUST_DNA_ACMG_CACHE`, so the lane's bare `default_dir()` IS the configured one. Treating
        # None as an error made `REGISTRY_ACMG_SNAPSHOT_DIR` mandatory, which it is not: it is an
        # override of where the snapshot lives, and a box that sets nothing has a perfectly good
        # default under the shared cache base.
        configured = lane_destinations(settings).get("acmg")
        try:
            acmg_dest = Path(configured) if configured is not None else lanes["acmg"].default_dir()
            detail = _fetch_acmg_snapshot(settings, Path(acmg_dest))
        except (httpx.HTTPError, ValueError, OSError) as exc:
            typer.secho(
                f"✗ acmg: FAILED — {type(exc).__name__}: {exc}", fg=typer.colors.RED, err=True
            )
            typer.secho(
                "   set REGISTRY_ACMG_SNAPSHOT_URL, or build it where you have the workbook "
                "and openpyxl: `just-dna-enricher acmg build --out <dir>`.",
                fg=typer.colors.YELLOW, err=True,
            )
            fetch_failures = 1
        else:
            typer.secho(f"✓ acmg: fetched — {detail}", fg=typer.colors.GREEN)
        # Out of `missing` either way. Leaving it in on failure hands the lane to `prepare_caches`,
        # which has no route for it and reports a *second*, different failure naming a path we did not
        # use — two contradictory sentences about one lane, and the misleading one last.
        missing = [name for name in missing if name != "acmg"]

    if not missing:
        if fetch_failures:
            raise typer.Exit(code=1)
        return

    from just_dna_enricher.caches import prepare_caches

    outcomes = prepare_caches(
        [lanes[name] for name in missing],
        declared_use=declared,
        pins=pins or None,
        sources=sources or None,
    )
    failures = fetch_failures
    for outcome in outcomes:
        # Read back, never taken from the route: `prepare_lane` answers `present` both for a lane it
        # checked and kept and for one it would not touch (a cache outside the lane's own directory).
        undone = (
            repull_left_undone(outcome.lane, lane_presence(settings).get(outcome.lane))
            if outcome.lane in repull and outcome.ready is True
            else None
        )
        if undone is not None:
            typer.secho(
                f"✗ {outcome.lane}: not re-pulled, {undone} — {outcome.detail}",
                fg=typer.colors.RED, err=True,
            )
            failures += 1
        elif outcome.ready is True:
            typer.secho(f"✓ {outcome.lane}: {outcome.route} — {outcome.detail}", fg=typer.colors.GREEN)
        elif outcome.ready is None:
            # Tri-state, and this arm is the reason it is not a bool: a lane that cannot run
            # unattended (a workbook only the operator holds, a release to pin, a licence declaration
            # that skips it) has not failed. Reported in the lane's own words and not counted.
            typer.secho(f"– {outcome.lane}: {outcome.detail}", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"✗ {outcome.lane}: FAILED — {outcome.detail}", fg=typer.colors.RED, err=True)
            if outcome.lane in gated and _looks_like_auth(outcome.detail):
                # The licence-gated mirrors are private, precisely because they mirror sources that
                # forbid sale — so anonymous access is refused rather than throttled, and a 401 reads
                # as "no such dataset". Say which it is: the fix is a token, not a rebuild.
                typer.secho(
                    "   the licence-gated mirrors are private: set REGISTRY_HF_TOKEN (or HF_TOKEN) "
                    "to an account with access, or build this snapshot locally with "
                    f"`just-dna-enricher {outcome.lane} build --out <dir>`.",
                    fg=typer.colors.YELLOW, err=True,
                )
            failures += 1

    if failures:
        typer.secho(
            f"\n{failures} lane(s) could not be provisioned. The rest are usable — a missing "
            f"resolution snapshot degrades publishing, a missing PGx or ACMG one skips a check leg.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)


@app.command("drop-caches")
def drop_caches(
    lane: list[str] = typer.Option(
        [], "--lane", help="A lane to remove from this box, by name, repeatable"
    ),
    leftovers: bool = typer.Option(
        False, "--leftovers",
        help="Also remove what no resolver reads: `<lane>.pre-<version>` builds a derived-lane rebuild "
             "kept, failed rebuild staging, and interrupted removals",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Remove a lane a pass here reads, or one with no published snapshot to pull back",
    ),
    apply: bool = typer.Option(False, "--apply/--dry-run", help="Delete (default: list what would go)"),
) -> None:
    """Give a snapshot lane's disk back: the inverse of `warm-caches`, one lane at a time.

    With no `--lane` and no `--leftovers` it lists every lane on this box with its size, which is the
    question to answer first. The path removed is the one the running server would read, never one you
    type, and a lane whose directory contains anything else (another lane, the shared cache base, the
    catalog, its storage or its runs) is refused whatever the flags say.

    `--force` is needed for a lane a pass here reads (`ensembl` and `clinvar` decide whether a publish
    works; the PGx and ACMG lanes feed opt-in checks) and for one nothing publishes, which comes back
    only by a local build (PharmVar's personal key, ACMG's workbook). A pulled lane comes back with
    `registry warm-caches --lane NAME --apply`; the dry run prints that line beside each one.

    A maintenance run, like `warm-caches`, and always keeps its log, so the removal is on record. It
    is not revertible by `revert-run`: the point is the disk, and the restore is the pull. A server
    that has a file of the lane open keeps that space until it restarts.
    """
    settings = get_settings()
    from just_dna_registry.services.cache_drop import drop, path_bytes, plan_drops
    from just_dna_registry.services.enrich import cache_lanes, enricher_available, lane_presence
    from just_dna_registry.services.lane_readers import lane_readers, reader_tag

    if not enricher_available():
        typer.secho(
            "just-dna-enricher is not installed — run `uv sync --extra server`.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    lanes = cache_lanes()
    unknown = sorted(name for name in lane if name not in lanes)
    if unknown:
        typer.secho(
            f"unknown lane(s): {', '.join(unknown)}. This enricher knows {', '.join(lanes)}.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    if not lane and not leftovers:
        present = {name: where for name, where in lane_presence(settings).items() if where is not None}
        if not present:
            typer.echo("no lane is present on this box")
            return
        sizes = {name: path_bytes(Path(where)) for name, where in present.items()}
        readers = lane_readers()
        for name in sorted(present, key=lambda n: -sizes[n]):
            tag = reader_tag(readers.get(name, ()))
            typer.echo(f"  {name} {tag}\t{human_size(sizes[name])}\t{present[name]}")
        typer.echo(
            f"{len(present)} lane(s), {human_size(sum(sizes.values()))}. Remove one with "
            f"`registry drop-caches --lane NAME --apply`."
        )
        return

    plan = plan_drops(settings, list(dict.fromkeys(lane)), leftovers=leftovers)
    for name in plan.absent:
        typer.echo(f"  – {name}: nothing on this box")
    for item in plan.drops:
        tag = reader_tag(item.readers)
        line = f"  {item.lane} {tag} {item.state}: {item.path} — {human_size(item.size)}"
        if item.refused:
            typer.secho(f"  ✗ {line[2:]}\n      refused: {item.refused}", fg=typer.colors.RED)
            continue
        typer.secho(line, fg=typer.colors.YELLOW if item.needs_force else None)
        for reason in item.needs_force:
            typer.echo(f"      needs --force: {reason}")
        if item.feeds:
            typer.echo(
                f"      {', '.join(item.feeds)} were built from it: they keep working, their next "
                f"rebuild needs it back"
            )
        if item.state == "present" and item.route == "pull":
            typer.echo(f"      restore: registry warm-caches --lane {item.lane} --apply")

    if not plan.drops:
        typer.echo("nothing to remove")
        return
    blocked = [item for item in plan.drops if item.blocked(force)]
    if blocked:
        typer.secho(
            f"\n{len(blocked)} path(s) refused or needing --force; nothing removed. Drop them from the "
            f"selection or pass --force where it applies.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    if not apply:
        typer.echo(
            f"\ndry run: {len(plan.drops)} path(s), {human_size(plan.size)} would be freed. "
            f"Re-run with --apply."
        )
        return
    freed = 0
    for item in plan.drops:
        freed += drop(item)
        typer.echo(f"  removed {item.path} ({item.lane}, {human_size(item.size)})")
    typer.secho(
        f"removed {len(plan.drops)} path(s), {human_size(freed)} freed. A server that has one of "
        f"these files open keeps its space until it restarts.",
        fg=typer.colors.GREEN,
    )


def _lane_pairs(pairs: list[str], flag: str, lanes: dict[str, Any]) -> dict[str, Any]:
    """`<lane>=<value>` options, parsed and checked against the lane registry.

    Checked rather than passed through: a typo'd lane name in a `--source` would otherwise be
    silently ignored and the lane would build from nothing (or refuse for a reason that names the
    wrong cause), which is the shape of every "the flag did nothing" report there has ever been.
    """
    out: dict[str, Any] = {}
    for raw in pairs:
        name, _, value = raw.partition("=")
        if not value or name not in lanes:
            typer.secho(
                f"{flag} takes `<lane>=<value>` for a known lane, got {raw!r}", fg=typer.colors.RED
            )
            raise typer.Exit(code=2)
        out[name] = Path(value) if flag == "--source" else value
    return out


def _gate_forecast(lane: Any, declared: str) -> str:
    """What `declared_use` will do to this lane, asked of upstream's own gate rather than restated.

    **`gated_lanes()` means "has recorded terms", not "forbids sale"**, and conflating the two got a
    sentence wrong in the one direction that matters: `alphagenome_avi` records terms *and* permits
    commercial use, so it needs no declaration at all, and a first cut of this line told an operator
    it "forbids sale and no use is declared". Predicting a refusal that will not happen sends someone
    to argue with a licence they already satisfy.

    So the forecast calls `check_declared_use`, which is the function `prepare_caches` itself gates
    on — three outcomes: raise (a declared `commercial` against a no-sale source), a reason string (a
    skip: nothing declared, or terms that could not be established), or `None` to proceed. Deriving
    it means this cannot drift from what `--apply` then does, which restating it in our own words
    demonstrably could.
    """
    terms = getattr(lane, "terms", None)
    if terms is None:  # not gated; the caller checked, but do not assume it
        return "pull"
    from just_dna_enricher.licensing import LicenseRefusal, check_declared_use

    try:
        reason = check_declared_use(terms, declared)
    except LicenseRefusal as exc:
        return f"WILL BE REFUSED: {exc}"
    if reason is not None:
        # No remedy appended: upstream's reason already ends with "Re-run with --use non-commercial
        # to record a declaration", and saying it twice in one line is how a message stops being read.
        return f"WILL BE SKIPPED: {reason}"
    settled = "no declaration needed" if terms.commercial_use is True else f"{declared} declared"
    return f"pull (licence-gated: {terms.source}, {settled})"


def _fetch_acmg_snapshot(settings: Settings, dest: Path) -> str:
    """Download the built ACMG SF list into `dest`, returning a one-line detail for the report.

    **The one lane a server has no other route to, and `openpyxl` is the reason.** Upstream's only
    build path reads ACMG's supplementary workbook through `openpyxl`, a `[dev]` extra there and a
    dependency of no extra here — so a deployment cannot run that build whatever workbook it holds,
    and fetching the workbook would not change that. What travels is the *built* list: `acmg_sf.csv`
    plus `release.json`, read by the pass with the standard library, so this needs no new dependency
    and no checkout on the box.

    `release.json` carries the DOI and the workbook's own `source_sha256`, so a fetched snapshot still
    says exactly what it was built from — the workbook itself is ACMG/Elsevier supplementary material
    and is not redistributed.
    """
    base = settings.acmg_snapshot_url.rstrip("/")
    payload: dict[str, bytes] = {}
    for filename in ("acmg_sf.csv", "release.json"):
        resp = httpx.get(f"{base}/{filename}", timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        payload[filename] = resp.content

    # Parse before writing: a 404 page or an HTML error that arrived with a 200 must not land on disk
    # as a snapshot, which is the `partial` state `prepare_lane` refuses to act on.
    release = json.loads(payload["release.json"])
    version = release.get("sf_version")
    genes = release.get("gene_count")
    if not version or not genes:
        raise ValueError(f"release.json from {base} names no sf_version/gene_count: {release!r}")
    header = payload["acmg_sf.csv"].split(b"\n", 1)[0].decode()
    if "gene" not in header:
        raise ValueError(f"acmg_sf.csv from {base} has no gene column, got header {header!r}")

    dest.mkdir(parents=True, exist_ok=True)
    for filename, content in payload.items():
        (dest / filename).write_bytes(content)
    return f"SF v{version}, {genes} genes → {dest}"


def _looks_like_auth(detail: str) -> bool:
    """Whether a provisioning failure reads like a missing HuggingFace token rather than an outage."""
    return "401" in detail or "not found" in detail.lower()


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
    counts: dict[str, int] = dict.fromkeys(("unchanged", "derived", "moved", "moved_build", "skipped"), 0)
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
    apply_purge(repo, _storage(settings), plan)
    typer.secho(
        f"purged {len(plan.modules)} module(s), {len(plan.namespaces)} namespace(s), "
        f"{len(plan.accounts)} account(s); {len(plan.disowned_versions)} version(s) disowned",
        fg=typer.colors.GREEN,
    )


# Last in the file on purpose. `python -m just_dna_registry.cli` executes the module top to bottom,
# so a guard placed mid-file calls `app()` before the commands below it are registered — this sat
# above the 0.11 operator block and cost six of them, `backup` included, on that entry point only.
# The console script (`registry`) imports the module and never trips the guard, so `--help` was
# right there and wrong under `python -m`, which is the hard direction to notice.
if __name__ == "__main__":
    app()
