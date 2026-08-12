"""
`registry-client` — a test/ops CLI for the registry API.

Points at a running server via `--url` (or `$REGISTRY_URL`) and authenticates publish/update
with `--token` (or `$REGISTRY_TOKEN`). Commands: list, download, publish, find-by-hash,
update-module-version.
"""

import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from just_dna_format.identity import parse_version
from just_dna_format.manifest import read_manifest, write_manifest

from just_dna_registry.client import RegistryClient, RegistryError
from just_dna_registry.installid import generate_install_id
from just_dna_registry.version import compatibility_error

load_dotenv()  # pick up REGISTRY_URL / REGISTRY_TOKEN from a local .env

app = typer.Typer(help="Registry test client", no_args_is_help=True)

_URL_ENV = "REGISTRY_URL"
_TOKEN_ENV = "REGISTRY_TOKEN"
_SKIP_VERSION_ENV = "REGISTRY_SKIP_VERSION_CHECK"


def _client(url: Optional[str], token: Optional[str], *, need_token: bool = False) -> RegistryClient:
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
def show_versions(url: Optional[str] = UrlOpt) -> None:
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


@app.command("list")
def list_modules(
    q: Optional[str] = typer.Option(None, help="Full-text query"),
    gene: Optional[str] = typer.Option(None),
    category: Optional[str] = typer.Option(None),
    genome_build: Optional[str] = typer.Option(None, "--genome-build"),
    namespace: Optional[str] = typer.Option(None),
    owner: Optional[str] = typer.Option(None),
    license: Optional[str] = typer.Option(None),
    featured: Optional[bool] = typer.Option(None, "--featured/--not-featured"),
    group: Optional[str] = typer.Option(None, help="Tab: all|featured|curated|popular|new|test"),
    sort: str = typer.Option("name", help="downloads|recent|name|stars|popular"),
    page: int = typer.Option(1, help="1-based page number"),
    per_page: int = typer.Option(20, "--per-page", help="Page size (max 100)"),
    url: Optional[str] = UrlOpt,
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
    url: Optional[str] = UrlOpt,
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
    title: Optional[str] = typer.Option(None, help="Display metadata for legacy parquet-only imports"),
    description: Optional[str] = typer.Option(None),
    report_title: Optional[str] = typer.Option(None),
    icon: Optional[str] = typer.Option(None),
    color: Optional[str] = typer.Option(None),
    genome_build: Optional[str] = typer.Option(
        None,
        "--genome-build",
        help="Assembly of a bare parquet archive that carries no manifest.json (default GRCh38). "
        "Not display metadata: the build decides the variant_key identity.",
    ),
    url: Optional[str] = UrlOpt,
    token: Optional[str] = TokenOpt,
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
    url: Optional[str] = UrlOpt,
    token: Optional[str] = TokenOpt,
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
    install_id: Optional[str] = typer.Option(
        None, "--install-id", help="Existing install-id; omit to grind a fresh one"
    ),
    difficulty: int = typer.Option(20, help="Proof-of-work bits when generating an install-id"),
    url: Optional[str] = UrlOpt,
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
def namespace_available(namespace: str, url: Optional[str] = UrlOpt) -> None:
    """Check whether a namespace is free to claim."""
    with _client(url, None) as c:
        info = c.namespace_available(namespace)
    state = "available" if info["available"] else "taken"
    valid = "" if info["valid"] else " (invalid name)"
    typer.echo(f"{namespace}: {state}{valid}")


@app.command("claim-namespace")
def claim_namespace(
    namespace: str, url: Optional[str] = UrlOpt, token: Optional[str] = TokenOpt
) -> None:
    """Claim an available namespace for your account (token)."""
    with _client(url, token, need_token=True) as c:
        result = c.claim_namespace(namespace)
    note = " (already yours)" if result.get("already_owned") else ""
    typer.echo(f"✓ {result['namespace']} → owner {result['owner']}{note}")


@app.command("find-by-hash")
def find_by_hash(
    digest: Optional[str] = typer.Argument(None, help="sha256:… artifact digest"),
    manifest_path: Optional[Path] = typer.Option(
        None, "--manifest", help="Read the digest from a local manifest.json instead"
    ),
    url: Optional[str] = UrlOpt,
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
    url: Optional[str] = UrlOpt,
    token: Optional[str] = TokenOpt,
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
    url: Optional[str] = UrlOpt,
    token: Optional[str] = TokenOpt,
) -> None:
    """Replace a published version's logo (metadata only; out of the digest, so no version bump)."""
    with _client(url, token, need_token=True) as c:
        result = c.amend_logo(namespace, name, version, logo)
    logo_entry = result.get("logo") or {}
    typer.echo(f"✓ {namespace}/{name}@{version} logo updated → {logo_entry.get('name')}")


@app.command("update-module-version")
def update_module_version(
    namespace: str,
    name: str,
    version: str,
    spec_dir: Path = typer.Argument(..., help="Updated spec directory"),
    changelog: str = typer.Option("", "--changelog"),
    url: Optional[str] = UrlOpt,
    token: Optional[str] = TokenOpt,
) -> None:
    """Publish a higher version of an existing module (checks it supersedes the current latest)."""
    with _client(url, token, need_token=True) as c:
        try:
            detail = c.get_module(namespace, name)
        except RegistryError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(
                    f"{namespace}/{name} does not exist yet — use `publish` for the first version"
                )
            raise
        latest = detail.get("latest_version")
        if latest and parse_version(version) <= parse_version(latest):
            raise typer.BadParameter(f"version {version} must be greater than current latest {latest}")
        manifest = c.publish(namespace, name, version, spec_dir, changelog)
    typer.echo(f"✓ updated {namespace}/{name}: {latest} → {manifest.identity.version}")


if __name__ == "__main__":
    app()


# ── Pre-flight (0.11) ─────────────────────────────────────────────────────────


_PACK_HELP: str = (
    "Compress the spec client-side and send one archive. Needed for a spec whose raw parts exceed "
    "the server's transfer bound (the ClinVar panels: 34-180 MiB raw, 2-10 MB packed)."
)


def _echo_findings(report) -> None:
    for line in report.errors:
        typer.secho(f"  ✗ {line}", fg=typer.colors.RED)
    for line in report.warnings:
        typer.secho(f"  ! {line}", fg=typer.colors.YELLOW)
    for line in report.info:
        typer.echo(f"  · {line}")


@app.command()
def validate(
    namespace: str,
    name: str,
    spec_dir: Path,
    strict: bool = typer.Option(
        True, "--strict/--no-strict", help="Grade findings under the mode publish compiles in"
    ),
    pack: bool = typer.Option(False, "--pack", help=_PACK_HELP),
    url: Optional[str] = UrlOpt,
    token: Optional[str] = TokenOpt,
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
    if report.published_as:
        where = ", ".join(f"{v.namespace}/{v.name}@{v.version}" for v in report.published_as)
        typer.secho(f"  ✗ identical data already published as: {where}", fg=typer.colors.RED)
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
    use: Optional[str] = typer.Option(
        None,
        "--use",
        help="unstated | non-commercial | commercial. Every PGx source forbids sale, so without a "
             "declaration each is skipped rather than queried.",
    ),
    pack: bool = typer.Option(False, "--pack", help=_PACK_HELP),
    url: Optional[str] = UrlOpt,
    token: Optional[str] = TokenOpt,
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
                raise typer.Exit(code=1)
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
            raise typer.Exit(code=1)

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
    url: Optional[str] = UrlOpt,
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
