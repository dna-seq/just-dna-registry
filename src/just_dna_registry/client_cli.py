"""
`registry-client` — a test/ops CLI for the registry API.

Points at a running server via `--url` (or `$REGISTRY_URL`) and authenticates publish/update
with `--token` (or `$REGISTRY_TOKEN`). `--help` lists the commands; the enumeration that used to sit
here went stale twice, and a partial list of commands reads as a complete one.
"""

import os
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from just_dna_format.identity import parse_version
from just_dna_format.manifest import read_manifest, write_manifest

from just_dna_registry.client import RegistryClient, RegistryError
from just_dna_registry.installid import generate_install_id
from just_dna_registry.ui import standalone
from just_dna_registry.version import compatibility_error

load_dotenv()  # pick up REGISTRY_URL / REGISTRY_TOKEN from a local .env

app = typer.Typer(help="Registry test client", no_args_is_help=True)

_URL_ENV = "REGISTRY_URL"
_TOKEN_ENV = "REGISTRY_TOKEN"
_SKIP_VERSION_ENV = "REGISTRY_SKIP_VERSION_CHECK"

#: The `/check` passes whose `unreachable` list `check` renders. Named here rather than written into
#: the loop so a test can pin it against `EnrichmentReport`'s own fields: the model side already
#: fails when a sixth pass ships without an `unreachable` list, and this is the other half of that
#: guard, because a field nothing prints is a field that does not reach the person running the check.
#: Three of the five (`frequencies`, `literature`, `acmg`) print no summary line of their own, so for
#: them this loop is the only place an outage becomes visible at all.
_UNREACHABLE_PASSES: tuple[str, ...] = (
    "frequencies", "literature", "identifiers", "acmg", "pgx",
)


def _client(url: str | None, token: str | None, *, need_token: bool = False) -> RegistryClient:
    base = url or os.getenv(_URL_ENV) or "http://127.0.0.1:8000"
    tok = token or os.getenv(_TOKEN_ENV)
    if need_token and not tok:
        raise typer.BadParameter(f"a token is required (pass --token or set ${_TOKEN_ENV})")
    timeout = float(os.getenv("REGISTRY_TIMEOUT", "600"))  # big modules recompile for minutes
    # Escape hatch: set REGISTRY_SKIP_VERSION_CHECK=1 to bypass the contract guard knowingly.
    check_version = os.getenv(_SKIP_VERSION_ENV, "").strip().lower() not in ("1", "true", "yes")
    return RegistryClient(base, tok, timeout=timeout, check_version=check_version)


UrlOpt = typer.Option(None, "--url", help=f"Registry base URL (or ${_URL_ENV})")
TokenOpt = typer.Option(None, "--token", help=f"API key for publish (or ${_TOKEN_ENV})")


@app.command("version")
def show_versions(url: str | None = UrlOpt) -> None:
    """Show this client's and the server's versions, and whether they're contract-compatible."""
    with _client(url, None) as c:
        local = c.local_version
        server = c.server_version()
    typer.echo(
        f"client:  registry {local.registry}  format {local.format}  api {local.api}"
    )
    if server is None:
        typer.secho("server:  (pre-0.7.1 — does not report its version)", fg=typer.colors.YELLOW)
        raise typer.Exit(0)
    typer.echo(
        f"server:  registry {server.registry}  format {server.format}  "
        f"compiler {server.compiler}  api {server.api}"
    )
    message = compatibility_error(server, local)
    if message is not None:
        typer.secho(f"INCOMPATIBLE — {message}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho("compatible ✓", fg=typer.colors.GREEN)


@app.command("caches")
def cache_status(
    url: str | None = UrlOpt,
    absent_only: bool = typer.Option(
        False, "--absent-only", help="Show only the lanes this deployment cannot read"
    ),
) -> None:
    """Which snapshot lanes the registry holds, and for an absent one the route and the reason.

    Anonymous. Ask it before deciding whether to lean on a registry for authoring work instead of
    provisioning fourteen multi-gigabyte snapshots locally, and after a `check` reports that a source
    was skipped — the reason is usually here rather than in the spec.

    **The three states are not two.** `partial` is a directory holding something that is not a
    readable snapshot, and it is the one state provisioning declines to act on rather than
    overwriting — so it needs a different move from the operator than `absent` does. Printing it as a
    plain cross is how a renderer comes to say "run a pull" about a pull that is going to refuse.
    """
    with _client(url, None) as c:
        report = c.cache_status()

    if not report.enricher_available:
        typer.secho(
            "the network tier is not installed on that deployment, so it holds no lanes at all "
            "(the `server` extra is what carries just-dna-enricher)",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    typer.echo(f"declared use: {report.declared_use}")
    shown = 0
    for lane in report.lanes:
        if absent_only and lane.state == "present":
            continue
        shown += 1
        tag = f"[{lane.group}]" if lane.group else "[not read there]"
        if lane.state == "present":
            # The release is printed beside the state rather than instead of it, and an unreadable
            # `release.json` says so: present-and-unprovenanced is a real state, and it is not absent.
            label = lane.release or ("(unreadable release.json)" if lane.release_unreadable else "")
            typer.secho(f"  ✓ {lane.name:14} present  {tag} {label}", fg=typer.colors.GREEN)
            continue
        if lane.state == "partial":
            typer.secho(
                f"  ! {lane.name:14} partial  {tag} — holds no readable snapshot; provisioning "
                f"refuses rather than deleting, so move it aside first",
                fg=typer.colors.RED,
            )
            continue
        how = {
            "pullable": "pull it",
            "buildable": f"build it: {lane.build_command or '(no command recorded)'}",
        }.get(lane.route, "no route in that tier")
        typer.secho(f"  ✗ {lane.name:14} absent   {tag} — {how}", fg=typer.colors.YELLOW)
        if lane.route_reason:
            typer.echo(f"      {lane.route_reason}")
        # The half that makes "absent" actionable: a lane the deployment's declared use declines will
        # never arrive from a pull, however many times one is run.
        if lane.licence_skip:
            typer.secho(f"      licence: {lane.licence_skip}", fg=typer.colors.YELLOW)
        if lane.parents:
            typer.echo(f"      derived from: {', '.join(lane.parents)}")

    if absent_only and not shown:
        typer.secho("every lane is provisioned there", fg=typer.colors.GREEN)


@app.command("list")
def list_modules(
    q: str | None = typer.Option(None, help="Full-text query"),
    gene: str | None = typer.Option(None),
    category: str | None = typer.Option(None),
    genome_build: str | None = typer.Option(None, "--genome-build"),
    namespace: str | None = typer.Option(None),
    owner: str | None = typer.Option(None),
    license: str | None = typer.Option(None),
    featured: bool | None = typer.Option(None, "--featured/--not-featured"),
    group: str | None = typer.Option(None, help="Tab: all|featured|curated|popular|new|test"),
    sort: str = typer.Option("name", help="downloads|recent|name|stars|popular"),
    page: int = typer.Option(1, help="1-based page number"),
    per_page: int = typer.Option(20, "--per-page", help="Page size (max 100)"),
    url: str | None = UrlOpt,
) -> None:
    """List / search catalog modules."""
    with _client(url, None) as c:
        body = c.list_modules(
            q=q, gene=gene, category=category, genome_build=genome_build, namespace=namespace,
            owner=owner, license=license, featured=featured, group=group, sort=sort,
            page=page, per_page=per_page,
        )
    typer.echo(f"{body['total']} module(s), page {body['page']} of {body['per_page']}-sized pages:")
    for item in body["items"]:
        typer.echo(
            f"  {item['namespace']}/{item['name']}@{item['latest_version']}"
            f"  [{item['stats']['variant_count']} variants, {item['stats']['gene_count']} genes]"
            f"  ↓{item['downloads']}  — {item['title']}"
        )


@app.command()
def download(
    namespace: str,
    name: str,
    version: str = typer.Argument(..., help="A version, or 'latest' for the current latest"),
    dest: Path = typer.Argument(..., help="Directory to extract into, or the .tar.gz path with --tarball"),
    tarball: bool = typer.Option(False, "--tarball", help="Fetch a single streamable tar.gz instead"),
    with_inputs: bool = typer.Option(
        False, "--with-inputs", help="Also fetch and hash-check the authored spec (CSVs + yaml)"
    ),
    layout: str = typer.Option(
        "flat", "--layout",
        help="flat (as the manifest names them) | split (machine-written tables under derived/)",
    ),
    url: str | None = UrlOpt,
) -> None:
    """Download a version's artifact (+ logs): verify-then-install, or a single tar.gz.
    `version` accepts `latest`.

    `--with-inputs` adds the authored spec, which a bare download leaves behind — the listing is the
    compiled parquets. `--layout split` then sorts the enricher's tables into `derived/`, once
    verification has passed, so a reader can tell them from the author's. Re-uploading either layout
    publishes the same module."""
    with _client(url, None) as c:
        if tarball:
            path = c.get_tarball(namespace, name, version, dest)
            typer.echo(f"✓ downloaded {namespace}/{name}@{version} → {path}")
            return
        manifest = c.download(
            namespace, name, version, dest, include_inputs=with_inputs, layout=layout
        )
    typer.echo(f"✓ downloaded + verified {namespace}/{name}@{version} → {dest}")
    typer.echo(f"  digest {manifest.artifact.digest}")
    if manifest.logs:
        typer.echo(f"  logs: {', '.join(e.name for e in manifest.logs)}")


@app.command("import-module")
def import_module(
    namespace: str,
    name: str,
    version: str,
    archive: Path = typer.Argument(..., help="A zip/tar.gz spec archive (or legacy parquet-only)"),
    changelog: str = typer.Option("", "--changelog"),
    title: str | None = typer.Option(None, help="Display metadata for legacy parquet-only imports"),
    description: str | None = typer.Option(None),
    report_title: str | None = typer.Option(None),
    icon: str | None = typer.Option(None),
    color: str | None = typer.Option(None),
    genome_build: str | None = typer.Option(
        None,
        "--genome-build",
        help="Assembly of a bare parquet archive that carries no manifest.json (default GRCh38). "
        "Not display metadata: the build decides the variant_key identity.",
    ),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Publish a module from a zip/tar.gz archive (in-house packaging / legacy import)."""
    display = {
        "title": title, "description": description, "report_title": report_title,
        "icon": icon, "color": color, "genome_build": genome_build,
    }
    with _client(url, token, need_token=True) as c:
        manifest = c.import_module(namespace, name, version, archive, changelog=changelog, display=display)
    typer.echo(f"✓ imported {manifest.identity.canonical_id}  digest {manifest.artifact.digest}")


@app.command()
def publish(
    namespace: str,
    name: str,
    version: str,
    spec_dir: Path = typer.Argument(..., help="Spec directory (module_spec.yaml + CSVs [+ logs])"),
    changelog: str = typer.Option("", "--changelog"),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Publish a spec as a new module version (server-side recompile)."""
    with _client(url, token, need_token=True) as c:
        manifest = c.publish(namespace, name, version, spec_dir, changelog)
    # Stamp the published identity into the local spec dir so it's discernible as "published-by-me".
    write_manifest(manifest, Path(spec_dir) / "manifest.json")
    typer.echo(f"✓ published {manifest.identity.canonical_id}")
    typer.echo(f"  digest {manifest.artifact.digest}  compile_success={manifest.compilation.compile_success}")
    typer.echo(f"  stamped {spec_dir}/manifest.json (identity + published_at)")


@app.command()
def register(
    account: str,
    install_id: str | None = typer.Option(
        None, "--install-id", help="Existing install-id; omit to grind a fresh one"
    ),
    difficulty: int = typer.Option(20, help="Proof-of-work bits when generating an install-id"),
    url: str | None = UrlOpt,
) -> None:
    """Self-register an account from an install-id (proof-of-work) and print an API key."""
    if not install_id:
        typer.echo(f"grinding install-id (difficulty {difficulty})…")
        install_id = generate_install_id(difficulty)
    with _client(url, None) as c:
        result = c.register(install_id, account)
    typer.echo(f"✓ registered account={result['account']} namespaces={result['namespaces']}")
    typer.echo(f"install-id: {install_id}")
    typer.echo(f"API key: {result['token']}")


@app.command("namespace-available")
def namespace_available(namespace: str, url: str | None = UrlOpt) -> None:
    """Check whether a namespace is free to claim."""
    with _client(url, None) as c:
        info = c.namespace_available(namespace)
    state = "available" if info["available"] else "taken"
    valid = "" if info["valid"] else " (invalid name)"
    typer.echo(f"{namespace}: {state}{valid}")


@app.command("claim-namespace")
def claim_namespace(
    namespace: str, url: str | None = UrlOpt, token: str | None = TokenOpt
) -> None:
    """Claim an available namespace for your account (token)."""
    with _client(url, token, need_token=True) as c:
        result = c.claim_namespace(namespace)
    note = " (already yours)" if result.get("already_owned") else ""
    typer.echo(f"✓ {result['namespace']} → owner {result['owner']}{note}")


@app.command("find-by-hash")
def find_by_hash(
    digest: str | None = typer.Argument(None, help="sha256:… artifact digest"),
    manifest_path: Path | None = typer.Option(
        None, "--manifest", help="Read the digest from a local manifest.json instead"
    ),
    url: str | None = UrlOpt,
) -> None:
    """Check whether an artifact digest is already published (dedup / provenance check)."""
    if manifest_path is not None:
        digest = read_manifest(manifest_path).artifact.digest
    if not digest:
        raise typer.BadParameter("provide a DIGEST or --manifest")
    with _client(url, None) as c:
        matches = c.lookup_by_digest(digest)
    if not matches:
        typer.echo(f"not published: {digest}")
        raise typer.Exit(code=1)
    typer.echo(f"{len(matches)} match(es) for {digest}:")
    for m in matches:
        flag = " (yanked)" if m["yanked"] else ""
        typer.echo(f"  {m['namespace']}/{m['name']}@{m['version']}{flag}")


@app.command("amend-changelog")
def amend_changelog(
    namespace: str,
    name: str,
    version: str,
    changelog: str,
    append: bool = typer.Option(False, "--append", help="Append to the existing changelog"),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Amend a published version's changelog (metadata only; the artifact stays immutable)."""
    with _client(url, token, need_token=True) as c:
        result = c.amend_changelog(namespace, name, version, changelog, append=append)
    typer.echo(f"✓ {namespace}/{name}@{version} changelog updated:\n{result['changelog']}")


@app.command("amend-logo")
def amend_logo(
    namespace: str,
    name: str,
    version: str,
    logo: Path = typer.Argument(..., help="Logo image (png/jpg/jpeg)"),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Replace a published version's logo (metadata only; out of the digest, so no version bump)."""
    with _client(url, token, need_token=True) as c:
        result = c.amend_logo(namespace, name, version, logo)
    logo_entry = result.get("logo") or {}
    typer.echo(f"✓ {namespace}/{name}@{version} logo updated → {logo_entry.get('name')}")


@app.command("set-short-description")
def set_short_description(
    namespace: str,
    name: str,
    text: str | None = typer.Argument(None, help="The subtitle, at most 120 characters, one line"),
    clear: bool = typer.Option(
        False, "--clear", help="Remove the override so the card falls back to `module.description`"
    ),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Set the registry-held subtitle a listing shows for this module (format 0.7).

    Module-level, not per version, and out of the module's identity: the authored subtitle stays in
    `module_spec.yaml` and this overrides only what a card renders, so rewording it spends no version
    number and moves no `content_signature`.

    `--clear` and an empty string are **two different requests**, which is why `--clear` is a flag
    rather than a spelling of `""`: clearing falls back to the authored `module.description`, while
    `""` is a subtitle deliberately blanked. A card cannot show both, and neither can a CLI that
    collapsed them.
    """
    if clear and text is not None:
        typer.secho("pass either TEXT or --clear, not both", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    if not clear and text is None:
        typer.secho("pass TEXT, or --clear to remove the override", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    with _client(url, token, need_token=True) as c:
        result = c.set_short_description(namespace, name, None if clear else text)
    now = result.get("short_description")
    if now is None:
        typer.echo(f"✓ {namespace}/{name} override cleared — the card shows module.description")
    else:
        typer.echo(f"✓ {namespace}/{name} card subtitle → {now!r}")


@app.command("amend-readme")
def amend_readme(
    namespace: str,
    name: str,
    version: str,
    readme: Path | None = typer.Argument(
        None, help="Markdown file with the card prose, or `-` to read it from stdin"
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Blank the card instead of setting prose (no PATH)"
    ),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Replace a published version's readme — the prose on its card (out of the digest, no bump).

    The one amend that had no command until 0.15 (S9), which left an author with a published module,
    a blank card and no Python with nothing to run. It is the amend that matters most: the readme is
    where a module says what it is *not*.

    `RegistryClient.amend_readme` takes a path *or* the text, and a shell has both too, so `PATH` is
    a file and `-` is stdin (`… amend-readme ns name 1.0.0 - <<'EOF'`). Not a `--text` flag: prose is
    multi-line and the shell already has a way to hand a command multi-line input.

    An empty file is refused rather than obeyed. Blanking a published card is a real operation — the
    API takes `""` — but it is indistinguishable from a typo'd path or an editor that saved nothing,
    and a silently blank card is the exact failure `amend_readme` exists to repair, so it needs
    `--clear` said out loud.
    """
    if clear and readme is not None:
        raise typer.BadParameter("pass either a PATH or --clear, not both")
    if not clear and readme is None:
        raise typer.BadParameter("provide a PATH (or `-` for stdin), or --clear to blank the card")
    text = ""
    if readme is not None:
        text = sys.stdin.read() if str(readme) == "-" else readme.read_text(encoding="utf-8")
        if not text.strip():
            raise typer.BadParameter(
                f"{readme} is empty — pass --clear if blanking the card is what you meant"
            )
    with _client(url, token, need_token=True) as c:
        result = c.amend_readme(namespace, name, version, text)
    prose = result.get("readme") or ""
    shape = f"{len(prose)} chars" if prose else "cleared"
    typer.echo(f"✓ {namespace}/{name}@{version} readme updated ({shape})")


@app.command("update-module-version")
def update_module_version(
    namespace: str,
    name: str,
    version: str,
    spec_dir: Path = typer.Argument(..., help="Updated spec directory"),
    changelog: str = typer.Option("", "--changelog"),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Publish a higher version of an existing module (checks it supersedes the current latest)."""
    with _client(url, token, need_token=True) as c:
        try:
            detail = c.get_module(namespace, name)
        except RegistryError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(
                    f"{namespace}/{name} does not exist yet — use `publish` for the first version"
                ) from exc
            raise
        latest = detail.get("latest_version")
        if latest and parse_version(version) <= parse_version(latest):
            raise typer.BadParameter(f"version {version} must be greater than current latest {latest}")
        manifest = c.publish(namespace, name, version, spec_dir, changelog)
    typer.echo(f"✓ updated {namespace}/{name}: {latest} → {manifest.identity.version}")


@app.command()
def ui(
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
    host: str = typer.Option("127.0.0.1", help="Interface to listen on"),
    port: int = typer.Option(8765, help="Port to listen on (0 picks a free one)"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the console in a browser"),
    expose_token: bool = typer.Option(
        False, "--expose-token",
        help="Allow --token together with a non-loopback --host (anyone reaching the port acts as you)",
    ),
) -> None:
    """Open the registry console in a browser, against the registry at --url.

    The page is the same one a server mounts at `/ui/`; this serves it locally and proxies `/api`,
    `/health` and `/docs` to the upstream, because the API sets no CORS policy and a page on one
    origin cannot call another. Reads work with no token. With `--token` (or `$REGISTRY_TOKEN`) the
    proxy adds the bearer to every request that carries none, so the key never enters the browser.

    That also means the listening socket is worth exactly what the key is worth: it binds to
    loopback, and combining a token with any other host needs `--expose-token` said out loud.
    """
    upstream = url or os.getenv(_URL_ENV) or "http://127.0.0.1:8000"
    tok = token or os.getenv(_TOKEN_ENV)
    if tok and host not in ("127.0.0.1", "localhost", "::1") and not expose_token:
        raise typer.BadParameter(
            f"--token with --host {host} lets anyone who reaches the port act as that key; "
            "pass --expose-token if that is what you mean"
        )
    suffix = "  (bearer injected by the proxy)" if tok else ""
    standalone.serve(
        upstream=upstream, host=host, port=port, token=tok, open_browser=open_browser,
        announce=lambda origin: typer.echo(f"console on {origin} → {upstream}{suffix}"),
    )


if __name__ == "__main__":
    app()


# ── Pre-flight (0.11) ─────────────────────────────────────────────────────────


_PACK_HELP: str = (
    "Compress the spec client-side and send one archive. Needed for a spec whose raw parts exceed "
    "the server's transfer bound (the ClinVar panels: 34-180 MiB raw, 2-10 MB packed)."
)


def _echo_findings(report) -> None:
    # A finding the author cannot clear is marked, not hidden. `carried` (format 0.7) is the subset
    # no edit to the spec directory removes — a limit of the tier, or a fact of a source — and a
    # publisher shown twelve yellow lines with no way to tell which four are theirs goes looking for
    # a mistake that is not there. Membership, never a substring test: a code survives a rewording.
    carried = set(getattr(report, "carried", ()) or ())
    for line in report.errors:
        typer.secho(f"  ✗ {line}", fg=typer.colors.RED)
    for line in report.warnings:
        if line in carried:
            typer.secho(f"  · {line}", fg=typer.colors.BRIGHT_BLACK)
        else:
            typer.secho(f"  ! {line}", fg=typer.colors.YELLOW)
    if carried:
        typer.secho(
            f"  ({len(carried)} of {len(report.warnings)} warning(s) marked · are carried: no edit "
            f"to the spec clears them)",
            fg=typer.colors.BRIGHT_BLACK,
        )
    for line in report.info:
        typer.echo(f"  · {line}")
    # Printed above the verdict and in yellow, because it is the context that decides whether an
    # error above is a typo or a version skew — and a field that reaches only the JSON is how this
    # project already rendered an outage as `✓ would publish` once. Shared by `validate` and
    # `check`, which is the whole reason the two call one renderer.
    if report.format_advisory:
        typer.secho(f"  ! {report.format_advisory}", fg=typer.colors.YELLOW)


@app.command()
def validate(
    namespace: str,
    name: str,
    spec_dir: Path,
    strict: bool = typer.Option(
        True, "--strict/--no-strict", help="Grade findings under the mode publish compiles in"
    ),
    pack: bool = typer.Option(False, "--pack", help=_PACK_HELP),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Validate a spec directory server-side, without publishing. Exits 1 when it would be rejected.

    `spec_dir` may also be a `.tar.gz`/`.zip` archive, in which case it is sent as-is.
    """
    with _client(url, token, need_token=True) as c:
        report = c.validate(namespace, name, spec_dir, strict=strict, pack=pack)
    _echo_findings(report)
    typer.echo(
        f"  {report.stats.variant_count} variant(s), {report.stats.gene_count} gene(s)"
        f"  signature={(report.content_signature or 'n/a')[:23]}…"
    )
    if not report.name_matches_path:
        typer.secho(
            f"  ✗ the spec's module.name is not {name!r} — publish would refuse", fg=typer.colors.RED
        )
    # Two lists, two colours: only `published_elsewhere` is a refusal. A hit under this same module
    # is a later version of your own unchanged data, which publish allows — printing it red is how a
    # publisher concludes a legal review pass is blocked.
    if report.published_elsewhere:
        where = ", ".join(f"{v.namespace}/{v.name}@{v.version}" for v in report.published_elsewhere)
        typer.secho(f"  ✗ identical data already published as: {where}", fg=typer.colors.RED)
    same_module = [v for v in report.published_as if v not in report.published_elsewhere]
    if same_module:
        where = ", ".join(f"{v.namespace}/{v.name}@{v.version}" for v in same_module)
        typer.secho(f"  · identical data already in this module: {where}", fg=typer.colors.YELLOW)
    # The server's own verdict, not a fourth local copy of the three gates it composes: this exit
    # code is a claim about what publish will do, so it has to come from the side that decides.
    if report.would_publish_module_level:
        typer.secho(
            "✓ valid — nothing module-level blocks a publish (the network tier is `check`)",
            fg=typer.colors.GREEN,
        )
        return
    raise typer.Exit(code=1)


@app.command()
def check(
    namespace: str,
    name: str,
    spec_dir: Path,
    strict: bool = typer.Option(True, "--strict/--no-strict"),
    offline: bool = typer.Option(False, "--offline", help="Clamp to the server's local caches"),
    frequencies: bool = typer.Option(
        False, "--frequencies", help="gnomAD allele frequencies (slow: ~6s per 20 variants)"
    ),
    literature: bool = typer.Option(False, "--literature", help="Citation existence + DOI agreement"),
    identifiers: bool = typer.Option(
        False, "--identifiers", help="trait_efo_id vs OLS4 and gene vs HGNC (online: no snapshot)"
    ),
    acmg: bool = typer.Option(False, "--acmg", help="acmg_sf flags vs the ACMG SF list"),
    pgx: bool = typer.Option(
        False, "--pgx", help="function_status vs PharmVar/CPIC/ClinPGx/ClinGen (needs --use)"
    ),
    use: str | None = typer.Option(
        None,
        "--use",
        help="unstated | non-commercial | commercial. Every PGx source forbids sale, so without a "
             "declaration each is skipped rather than queried.",
    ),
    pack: bool = typer.Option(False, "--pack", help=_PACK_HELP),
    url: str | None = UrlOpt,
    token: str | None = TokenOpt,
) -> None:
    """Full publish dry run: validation plus the network-tier checks. Exits 1 unless it would publish.

    Slow by design. It spends the server's standing with rate-limited public APIs (gnomAD throttles
    by IP and offers no key), so the server limits it hard. Start with `--offline` and add passes as
    you need them.
    """
    with _client(url, token, need_token=True) as c:
        try:
            report = c.check(
                namespace, name, spec_dir, strict=strict, offline=offline,
                frequencies=frequencies, literature=literature, identifiers=identifiers,
                acmg=acmg, pgx=pgx, pack=pack,
                # The CLI spells it with a hyphen (matching `just-dna-enricher --use`); the column
                # vocabulary uses an underscore. Normalize here so a hand-typed flag cannot 422.
                declared_use=use.replace("-", "_") if use else None,
            )
        except RegistryError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if detail.get("error") == "too_many_variants":
                # The refusal carries the module-level verdict the server computed before stopping,
                # so print it rather than a bare "HTTP 422: {...}". Same reasoning as the 503 below:
                # a dead end an author cannot navigate becomes a support ticket.
                verdict = detail.get("would_publish_module_level")
                typer.secho(
                    f"✗ too large for an ONLINE check: {detail.get('subject_count')} enrichment "
                    f"subject(s), limit {detail.get('limit')}.",
                    fg=typer.colors.RED,
                )
                if verdict is not None:
                    mark, colour = (
                        ("✓", typer.colors.GREEN) if verdict else ("✗", typer.colors.RED)
                    )
                    typer.secho(
                        f"  {mark} module-level checks (validity, name, dedup): "
                        f"{'nothing blocks a publish' if verdict else 'a publish would be refused'}"
                        f" — the network tier was not run, so this is not a `would publish`.",
                        fg=colour,
                    )
                for line in detail.get("validation", {}).get("errors", []):
                    typer.secho(f"  ✗ {line}", fg=typer.colors.RED)
                typer.secho(
                    "  Re-run with --offline for everything the server's snapshots can answer "
                    "(no ceiling), or ask the operator to raise REGISTRY_ENRICH_MAX_VARIANTS.",
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(code=1) from None
            if detail.get("error") != "enrichment_unavailable":
                raise
            # A bare "HTTP 503: {...}" here becomes a support ticket. Name the fix instead, for both
            # of the people who could apply one.
            missing = ", ".join(detail.get("missing", []))
            typer.secho(
                f"✗ the server has no reference snapshot provisioned ({missing}).\n"
                f"  Ask the operator to run `registry warm-caches --apply`, or re-run with "
                f"--offline for the checks that need no reference.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1) from None

    _echo_findings(report.validation)
    if report.skipped_reason:
        typer.secho(f"  enrichment skipped: {report.skipped_reason}", fg=typer.colors.YELLOW)
    e = report.enrichment
    if e is not None:
        if e.unresolved:
            typer.secho(
                f"  ! {len(e.unresolved)} variant(s) unresolved: {', '.join(e.unresolved[:5])}",
                fg=typer.colors.YELLOW,
            )
        # Printed directly under the unresolved line, because it is what decides the response to it: an
        # unanswered request is a re-run, not an authoring fix (S20).
        if e.unreachable_rsids:
            typer.secho(
                f"  · live Ensembl could not be asked about {len(e.unreachable_rsids)} rsID(s) "
                f"({', '.join(e.unreachable_rsids[:5])}) — unchecked, not absent. Re-run before "
                f"authoring coordinates for them.",
                fg=typer.colors.YELLOW,
            )
        for m in e.ref_mismatches:
            shift = f" — likely a wrong `start`, off by {m.shift:+d}" if m.shift else ""
            typer.secho(
                f"  ✗ ref mismatch {m.variant_key} at {m.chrom}:{m.start}: "
                f"authored {m.claimed!r}, genome has {m.actual!r}{shift}",
                fg=typer.colors.RED,
            )
        for conflict in e.clin_sig_conflicts:
            typer.secho(
                f"  ! clin_sig {conflict.variant_key}: you say {conflict.authored!r}, "
                f"ClinVar says {conflict.clinvar!r} ({conflict.confidence})",
                fg=typer.colors.YELLOW,
            )
        for stale in e.stale_rsids:
            colour = typer.colors.RED if stale.fatal else typer.colors.YELLOW
            typer.secho(f"  {'✗' if stale.fatal else '!'} rsID {stale.rsid} is {stale.state}", fg=colour)
        # Before any pass's findings, because it decides how to read them. A pass that reached
        # nothing reports nothing, which is indistinguishable on screen from a pass that found
        # nothing — and unlike `unreachable_rsids` above, this one is not visible in any other line:
        # the frequency, literature and ACMG passes print no summary at all, so without this a gnomAD
        # outage would show as a clean check. Yellow, never red: an upstream being down is not a
        # finding about the module and `would_publish` does not move for it.
        for pass_name in _UNREACHABLE_PASSES:
            result = getattr(e, pass_name)
            if result is not None and result.unreachable:
                typer.secho(
                    f"  · {pass_name}: no answer from {', '.join(result.unreachable)} — that part "
                    f"of the check is unchecked, not clean. Re-run.",
                    fg=typer.colors.YELLOW,
                )
        # The literature pass has no summary line, so a finding that lives only in a list has to be
        # printed here or it reaches nobody (the 0.17 lesson: a new report field is only half a fix).
        # Yellow: a quote that is its own article's title grounds nothing, but it is a defect in the
        # *evidence*, not a reason to refuse the module, and `would_publish` does not move for it.
        if e.literature is not None and e.literature.titles_as_quotes:
            pmids = e.literature.titles_as_quotes
            typer.secho(
                f"  ! {len(pmids)} quote(s) are the cited article's own title "
                f"(PMID {', '.join(pmids[:5])}{'…' if len(pmids) > 5 else ''}) — counted as found, "
                f"but a title cannot fail a fulltext check, so they ground nothing. Quote the "
                f"sentence that states the claim.",
                fg=typer.colors.YELLOW,
            )
        if e.identifiers is not None:
            for line in e.identifiers.stale_traits + e.identifiers.stale_genes:
                typer.secho(f"  ! {line}", fg=typer.colors.YELLOW)
            # A gene naming a chromosome its own variant is not on (S24). Red where a stale symbol is
            # yellow: a retired name still describes the right locus, while this says one of the two
            # identifiers on the row is about something else entirely.
            for line in e.identifiers.gene_loci:
                typer.secho(f"  ✗ {line}", fg=typer.colors.RED)
            # Never asked is not answered-clean, so the two print differently on purpose.
            if e.identifiers.gene_loci_not_checked:
                typer.echo(
                    f"  · gene/variant chromosome agreement was not checked: "
                    f"{e.identifiers.gene_loci_not_checked}"
                )
            for line in e.identifiers.unchecked:
                typer.echo(f"  · {line}")
            for line in e.identifiers.warnings:
                typer.echo(f"  · {line}")
        if e.pgx is not None:
            for conflict in e.pgx.conflicts:
                typer.secho(
                    f"  ! {conflict.source} {conflict.gene}*{conflict.allele}: you say "
                    f"{conflict.authored!r}, {conflict.source} reports {conflict.reported!r}",
                    fg=typer.colors.YELLOW,
                )
            for line in e.pgx.skipped:
                typer.echo(f"  · {line}")
            typer.echo(
                f"  PGx: declared_use={e.pgx.declared_use}"
                f"  pharmvar_key={'yes' if e.pgx.pharmvar_enabled else 'no'}"
                f"  consulted: {', '.join(e.pgx.sources) or 'nothing'}"
            )
        typer.echo(
            f"  VRS identity: {e.vrs.identified}/{e.vrs.alleles} allele(s)"
            f"   sources: {', '.join(e.sources) or 'none'}   [{report.elapsed_seconds}s]"
        )

    if report.would_publish:
        typer.secho("✓ would publish", fg=typer.colors.GREEN)
        return
    typer.secho("✗ would NOT publish", fg=typer.colors.RED)
    raise typer.Exit(code=1)


@app.command()
def signature(
    spec_dir: Path,
    lookup: bool = typer.Option(
        False, "--lookup", help="Also ask the registry whether this data is already published"
    ),
    url: str | None = UrlOpt,
) -> None:
    """Print a spec's content signature, computed locally — no upload, no recompile.

    NOTE the exit code with `--lookup` is the **inverse** of `find-by-hash`'s. That one asks "is this
    artifact published?" and fails when it is not. This one is a pre-publish dedup gate, so a match
    is the failure: exit 1 means the registry already has this data under some name.
    """
    with _client(url, None) as c:
        sig = c.content_signature(spec_dir)
        typer.echo(sig)
        if not lookup:
            return
        matches = c.lookup_by_signature(sig)
    if not matches:
        typer.secho("✓ not published — free to publish", fg=typer.colors.GREEN)
        return
    where = ", ".join(f"{v.namespace}/{v.name}@{v.version}" for v in matches)
    typer.secho(f"✗ identical data already published as: {where}", fg=typer.colors.RED)
    raise typer.Exit(code=1)
