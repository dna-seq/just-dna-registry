"""
Server-side publish (SPEC §7, §8.6–§8.7): the trust-bearing path.

The publisher uploads the **spec only** (as individual files or a zip/tar.gz archive); the server
enriches it, runs `compile_module` itself (so `compile_success`, input hashes, and the artifact
digest are produced by the trusted party), fills the registry-level manifest fields, stores the
compiled module under a version key, and indexes the manifest.

The 0.5 pipeline is **enrich → compile strict**, in that order and as two steps. The enricher
resolves rsIDs to coordinates and writes `resolution.csv`; the compiler then consumes that file and
never fetches anything itself. Running them as one call — `compile_module(ensembl_cache=…)` — is
deprecated upstream precisely because it reaches into the network tier from inside the compile path.

`strict` is what makes the registry's `compiled_by` token worth anything: it refuses to emit a
partial artifact when a variant was left without a position, rather than publishing something whose
`fully_resolved` is quietly false.

Legacy modules that ship only compiled parquets (the old zip format, no manifest) are imported by
reverse-engineering a spec (`reverse_module`) with the client supplying the missing display
metadata, then recompiling — same trust guarantee.
"""

import io
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Optional

import yaml
from eliot import start_action
from just_dna_compiler.compiler import (
    compile_module,
    content_signature,
    reverse_module,
    validate_spec,
)
from just_dna_format.identity import canonical_id
from just_dna_format.integrity import sha256_bytes
from just_dna_format.manifest import (
    LOGO_EXTENSIONS,
    MARKETPLACE_COMPILED_BY,
    FileEntry,
    ModuleManifest,
    write_manifest,
)
from just_dna_format.normalize import IDENTITY_AUTHORITY_KEYS
from just_dna_format.signing import sign_digest
from pydantic import BaseModel, Field

from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.services.enrich import enrich_spec, unresolved_hint
from just_dna_registry.services.ingest import ingest_manifest, now_iso
from just_dna_registry.specfiles import (
    README_FILE,
    REQUIRED_SPEC_FILES,
    SPEC_YAML,
    LayoutPlan,
    carries_spec_content,
    plan_layout,
)
from just_dna_registry.storage.base import StorageBackend, version_key
from just_dna_registry.testdata import (
    accepted_anyway,
    duplicate_scope_account,
    override_hint,
    test_data_refusal,
)

_REVERSE_MARKER: str = "weights.parquet"  # a legacy compiled module has this but no spec

# Manifest fields the registry fills itself on publish (SPEC §4) and is therefore the authority on:
# it stamps `identity.{namespace,canonical_id}` and `owner` from the request, overriding any authored
# value. The format calls these "authority keys" and ships the canonical set, which the registry
# injects rather than maintaining its own — `validate_spec`/`compile_module` take it as a parameter
# and report what they dropped on `ValidationResult.info`.
#
# `module.version` is deliberately NOT here any more. Through 0.10 the registry stripped it too,
# because format 0.4 made the `module:` block `extra="forbid"` and every pre-0.4 archive shipped one.
# Format 0.5 turned it back into a real, freeform, advisory field (coerced to SemVer at load, with
# the original kept as `version_coerced_from`), so stripping it now discards author intent for no
# gain: the registry stamps `Identity.version` from the request regardless, and that always wins.
_REGISTRY_OWNED_MODULE_KEYS: tuple[str, ...] = tuple(sorted(IDENTITY_AUTHORITY_KEYS))


def normalize_module_block(spec_dir: Path) -> list[str]:
    """Normalize `module_spec.yaml`'s `module:` block in place. Returns a description of each change.

    Two normalizations, both contract-independent housekeeping rather than a per-release migration:

    **Registry-owned keys are dropped.** The compiler's injected `authority_keys=` does the same job
    non-destructively, and we pass that too — but it is not a substitute, because
    `content_signature(spec_dir)` loads the YAML with **no** authority keys of its own. A stored spec
    still carrying `namespace:` fails that load, falls back to the default genome build, and quietly
    produces the wrong signature for a non-GRCh38 module. Normalizing on disk, first, is what stops
    that, and it keeps the *stored* spec self-consistent for everything that reads it back later:
    revalidate, upgrade, and signature re-derivation.

    **A non-string `module.version` is stringified.** `version: 3` in YAML is an integer, and format
    0.5's `ModuleInfo.version` is a freeform *string*, so the whole pre-0.4 corpus fails to load on a
    quoting accident. Through 0.10 the registry dropped the key outright to sidestep this; 0.5 made
    it a real advisory field, so discarding it now would throw away author intent for nothing —
    `"3"` is coerced to `3.0.0` with the original kept as `version_coerced_from`, and the registry's
    own stamped `Identity.version` wins regardless.

    A no-op leaves the file byte-identical, so a clean spec keeps its authored bytes.
    """
    spec_file = spec_dir / SPEC_YAML
    if not spec_file.is_file():
        return []
    doc = yaml.safe_load(spec_file.read_text(encoding="utf-8"))
    module = doc.get("module") if isinstance(doc, dict) else None
    if not isinstance(module, dict):
        return []

    changes = [
        f"dropped registry-owned `module.{key}` (the registry stamps it on publish)"
        for key in _REGISTRY_OWNED_MODULE_KEYS
        if module.pop(key, None) is not None
    ]
    version = module.get("version")
    if version is not None and not isinstance(version, str):
        module["version"] = str(version)
        changes.append(
            f"quoted `module.version: {version!r}` as {str(version)!r} "
            f"(YAML read it as {type(version).__name__}; the field is a freeform string)"
        )

    if changes:
        spec_file.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return changes


class PublishError(Exception):
    """A publish failure the router maps to an HTTP status."""

    def __init__(
        self,
        detail: str,
        *,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        info: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors or []
        self.warnings = warnings or []
        # `ValidationResult.info` — accepted-but-noteworthy findings, e.g. which authority keys were
        # dropped from the authored block, or that `module.version: v2` was coerced to `2.0.0`.
        # Carried so a publisher sees what the server changed about their spec, not just why it lost.
        self.info = info or []
        # Structured, already-JSON-safe fields for a refusal that has more to say than prose — the
        # variant ceiling carries the module-level verdict it computed before refusing. Additive by
        # construction: the router lets the four fixed keys above win a collision, so a client
        # branching on `error`/`errors` cannot be broken by anything put here.
        self.extra = extra or {}


async def collect_uploads(files: list[Any], settings: Settings) -> dict[str, bytes]:
    """Read a multipart spec upload into memory: counted, bounded, and containment-checked.

    Shared by every upload route (publish, import, validate, check) so the guards cannot be present
    on one and absent on another — which is how the traversal below survived: the archive path has
    always checked containment (`_extract_archive`), the multipart path never did.

    Order matters. Count and size are checked from `UploadFile.size` *before* anything is read —
    Starlette spools parts over 1 MiB to disk, so the sizes are known without materializing the
    payload, and a 2 GiB upload is rejected without ever being held in memory.

    Raises `PublishError` with `too_many_files` / `upload_too_large` / `unsafe_filename`.
    """
    named = [f for f in files if f.filename]
    if len(named) > settings.max_spec_files:
        raise PublishError(
            "too_many_files",
            errors=[f"{len(named)} files uploaded; the limit is {settings.max_spec_files}"],
        )

    total = sum(f.size or 0 for f in named)
    if total > settings.max_upload_bytes:
        raise PublishError(
            "upload_too_large",
            errors=[
                f"{total} bytes uploaded; the limit is {settings.max_upload_bytes} "
                f"({settings.max_upload_bytes // (1024 * 1024)} MiB)"
            ],
        )

    for upload in named:
        reject_unsafe_relpath(upload.filename)
    return {f.filename: await f.read() for f in named}


async def collect_archive(archive: Any, settings: Settings) -> dict[str, bytes]:
    """Read a spec archive upload into the same `{relative-name: bytes}` shape `collect_uploads`
    returns, so a pre-flight route can accept either form and know nothing about which it got.

    This exists because `/versions/import` accepted a compressed spec while `/validate` and `/check`
    did not, which made the large ClinVar panels publishable but impossible to rehearse: the raw
    multipart body is 180 MiB against a 25 MiB transfer bound, and the compressed form the publish
    route takes had no counterpart on the dry-run routes. A dry run that cannot accept what the
    publish accepts predicts nothing.

    Only recognized spec files are returned. A legacy parquet-only archive is *not* reversed here —
    that is a publish concern (`import_archive`), and reverse-engineering an artifact to validate it
    would report on a spec the caller never wrote.
    """
    size = archive.size or 0
    if size > settings.max_upload_bytes:
        raise PublishError(
            "upload_too_large",
            errors=[
                f"{size} bytes uploaded; the limit is {settings.max_upload_bytes} "
                f"({settings.max_upload_bytes // (1024 * 1024)} MiB)"
            ],
        )
    data = await archive.read()
    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp) / "extracted"
        extracted.mkdir()
        _extract_archive(data, extracted, settings)
        root = _module_root(extracted)
        if not (root / SPEC_YAML).is_file():
            raise PublishError(
                "no_module_content",
                errors=[f"archive contains no {SPEC_YAML}; a dry run needs an authored spec"],
            )
        uploads: dict[str, bytes] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            # Basename-aware, not name-exact: `derived/resolution.csv` and a legacy `MODULE.md` both
            # have to survive this filter to reach `normalize_spec_layout` in `_preflight_spec_dir`.
            if carries_spec_content(rel):
                uploads[rel] = path.read_bytes()
        if len(uploads) > settings.max_spec_files:
            raise PublishError(
                "too_many_files",
                errors=[f"{len(uploads)} spec files in archive; the limit is "
                        f"{settings.max_spec_files}"],
            )
        return uploads


def reject_unsafe_relpath(name: str) -> None:
    """Refuse a spec-file name that would write outside the spec directory.

    Checked structurally rather than by resolving against a real directory, so the verdict does not
    depend on which temp dir the caller later picks and cannot be raced by a symlink appearing
    between the check and the write. Backslashes are rejected outright: they are not path separators
    on POSIX, so `..\\..\\x` would pass a POSIX-only check and still escape on a Windows host.
    """
    candidate = PurePosixPath(name)
    if candidate.is_absolute() or PureWindowsPath(name).is_absolute() or "\\" in name:
        raise PublishError("unsafe_filename", errors=[f"absolute path not allowed: {name!r}"])
    if any(part == ".." for part in candidate.parts):
        raise PublishError("unsafe_filename", errors=[f"path escapes the spec directory: {name!r}"])
    if not candidate.name or candidate.name in {".", ".."}:
        raise PublishError("unsafe_filename", errors=[f"not a file path: {name!r}"])


class SpecNormalization(BaseModel):
    """Everything the server rewrote about an uploaded spec before reading it.

    One return value for the two normalizations because they have one audience: a publisher asking
    "what did the server change about what I sent?". `info` is `ValidationResult.info` grade —
    accepted and noteworthy; `warnings` is for what the author probably did not mean.
    """

    info: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    layout: LayoutPlan = Field(default_factory=LayoutPlan)


def normalize_spec(spec_dir: Path) -> SpecNormalization:
    """Bring an uploaded spec dir onto the canonical layout and the current `module:` block.

    The one entry point for both, called from exactly three places — `_finalize`, and the two dry-run
    workers — because those three are the only places a spec directory is built from an upload, and
    because a dry run that normalizes differently from the publish it predicts is worse than one that
    does not normalize at all.

    Layout first: `normalize_module_block` reads `module_spec.yaml` by name, and until the flatten
    has run there is no guarantee the file is at the root.
    """
    layout = normalize_spec_layout(spec_dir)
    return SpecNormalization(
        info=layout.notes + normalize_module_block(spec_dir),
        warnings=layout.warnings,
        layout=layout,
    )


def normalize_spec_layout(spec_dir: Path) -> LayoutPlan:
    """Flatten an uploaded spec tree onto the layout the compiler reads. Returns what it did.

    The applier for `specfiles.plan_layout`; the planning is name-level and lives there so the
    pre-flight and the publish cannot disagree about the answer. Raises `ambiguous_spec_layout`
    (422) on a conflict.

    Deliberately first — ahead of `normalize_module_block`, `validate_spec` and the signature — so
    everything downstream sees one canonical layout and no other code in this package has to know
    that a subfoldered upload is a thing that happens.
    """
    names = [p.relative_to(spec_dir).as_posix() for p in spec_dir.rglob("*") if p.is_file()]
    plan = plan_layout(names)
    if plan.conflicts:
        raise PublishError("ambiguous_spec_layout", errors=plan.conflicts)
    for source, dest in plan.renames.items():
        (spec_dir / source).replace(spec_dir / dest)
    # Deepest first, so `a/b/` empties before `a/` is considered. Cosmetic for the compile (which
    # ignores stray directories) but not for storage: the carry-forward loop walks this tree, and an
    # emptied `derived/` would otherwise be the one trace of a layout that no longer exists.
    for directory in sorted(
        (p for p in spec_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True
    ):
        if not any(directory.iterdir()):
            directory.rmdir()
    return plan


# ── Public entry points ───────────────────────────────────────────────────────


def publish_version(
    *,
    repo: Repository,
    storage: StorageBackend,
    settings: Settings,
    namespace: str,
    name: str,
    version: str,
    changelog: str,
    owner: str,
    files: Mapping[str, bytes],
    published_by: Optional[int] = None,
    gate: Optional[Any] = None,
    allow_test_data: bool = False,
) -> ModuleManifest:
    """Publish from individually-uploaded spec files.

    `gate` is an already-acquired `EnrichmentGate` permit, released here in the worker's own
    `finally` — see `import_archive` for why the release cannot live on the caller's side.
    """
    try:
        missing = [f for f in REQUIRED_SPEC_FILES if f not in files]
        if missing:
            raise PublishError("missing_spec_files", errors=[f"missing: {m}" for m in missing])
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "spec"
            for rel, data in files.items():
                # Re-checked at the point of the write, not only at the door: this function is a
                # public entry point and its callers (routers, the CLI, a future one) each supply
                # the mapping themselves. A containment check that lives only in the HTTP layer is
                # one refactor away from being absent.
                reject_unsafe_relpath(rel)
                dest = spec_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            return _finalize(
                repo=repo, storage=storage, settings=settings, namespace=namespace, name=name,
                version=version, changelog=changelog, owner=owner, published_by=published_by,
                spec_dir=spec_dir, allow_test_data=allow_test_data,
            )
    finally:
        if gate is not None:
            gate.release()


def import_archive(
    *,
    repo: Repository,
    storage: StorageBackend,
    settings: Settings,
    namespace: str,
    name: str,
    version: str,
    changelog: str,
    owner: str,
    archive: bytes,
    display: Optional[dict] = None,
    allow_test_data: bool = False,
    published_by: Optional[int] = None,
    gate: Optional[Any] = None,
) -> ModuleManifest:
    """Publish from a zip/tar.gz archive: a spec archive is compiled directly; a legacy
    parquet-only archive is reverse-engineered (with client-supplied `display` metadata) first.

    `gate` is an already-acquired `EnrichmentGate` permit. It is released **here**, in the worker's
    own `finally`, rather than by the coroutine that took it: a run that outlives its request keeps
    its thread (Python cannot kill one), so releasing on the caller's side would let a run that is
    still spending stop counting against occupancy. Same rule as `dry_run`.
    """
    try:
        with start_action(
            action_type="import_archive", namespace=namespace, name=name, version=version,
            archive_bytes=len(archive),
        ) as action:
            with tempfile.TemporaryDirectory() as tmp:
                extracted = Path(tmp) / "extracted"
                extracted.mkdir()
                _extract_archive(archive, extracted, settings)
                root = _module_root(extracted)
                is_spec = (root / "module_spec.yaml").is_file()
                action.log(message_type="archive_extracted", mode="spec" if is_spec else "reverse",
                           root=str(root.relative_to(extracted)) or ".")
                if is_spec:
                    spec_dir = root
                else:
                    spec_dir = Path(tmp) / "reversed"
                    reverse_module(root, spec_dir, module_name=name, **(_reverse_kwargs(display)))
                return _finalize(
                    repo=repo, storage=storage, settings=settings, namespace=namespace, name=name,
                    version=version, changelog=changelog, owner=owner, published_by=published_by,
                    spec_dir=spec_dir, allow_test_data=allow_test_data,
                )
    finally:
        if gate is not None:
            gate.release()


# ── Core ──────────────────────────────────────────────────────────────────────


def _finalize(
    *,
    repo: Repository,
    storage: StorageBackend,
    settings: Settings,
    namespace: str,
    name: str,
    version: str,
    changelog: str,
    owner: str,
    spec_dir: Path,
    published_by: Optional[int] = None,
    allow_test_data: bool = False,
) -> ModuleManifest:
    """Validate, enrich, recompile a prepared spec dir, store the version, and index it.

    `allow_test_data` waves a `test-`/`test_`prefixed identifier onto production deliberately (0.14).
    Off by default, so the guard still catches the typo it was built for.
    """
    with start_action(
        action_type="publish_finalize", namespace=namespace, name=name, version=version
    ) as action:
        # Layout and `module:` block, in that order, before anything reads the spec — so validation,
        # the signature and the carry-forward into storage all see one canonical flat directory, and
        # none of them has to know that a subfoldered or legacy-named upload is a thing that happens.
        normalization = normalize_spec(spec_dir)
        if normalization.info or normalization.warnings:
            action.log(
                message_type="normalized_spec",
                renames=normalization.layout.renames,
                info=normalization.info,
                warnings=normalization.warnings,
            )

        # Modeless on purpose, even though the compile below is strict. This pass exists to reject a
        # broken spec before spending enrichment on it; the strict-only findings are all judgements
        # about *resolved* data, and raising them here — before any coordinate exists — would point
        # the author at the wrong column. `compile_module` re-runs validation itself and then re-runs
        # the mode-ladder checks at their real severity, which is where strict belongs.
        validation = validate_spec(spec_dir, IDENTITY_AUTHORITY_KEYS)
        action.log(
            message_type="validated", valid=validation.valid,
            errors=validation.errors[:20], warnings=validation.warnings[:20],
            info=validation.info[:20],
        )
        if not validation.valid:
            raise PublishError(
                "invalid_spec",
                errors=validation.errors,
                warnings=validation.warnings + normalization.warnings,
                # What the server rewrote rides on the refusal too. A publisher whose `MODULE.md` was
                # renamed and whose spec then failed for an unrelated reason should not have to guess
                # which of the two happened.
                info=normalization.info + validation.info,
            )

        # Production refuses test data by default (0.12), and since 0.14 the refusal is overridable
        # rather than absolute. Checked here rather than at the route so every publish path shares it,
        # and before the dedup/enrich/compile spend because a refusal this certain should cost
        # nothing. The polygon accepts it regardless — that is what the instance is for.
        #
        # The default stays "refuse" because the failure it prevents is silent and permanent: a
        # mistyped namespace puts test data in the production catalog, where the version number and
        # the `content_hash` are spent and only a purge frees them. Asking for it explicitly is
        # cheap; discovering it afterwards is not.
        refusal = test_data_refusal(namespace, name, settings)
        if refusal is not None:
            if not allow_test_data:
                action.log(message_type="test_data_on_prod", namespace=namespace, name=name)
                raise PublishError("test_data_on_prod", errors=[f"{refusal} {override_hint()}"])
            # Logged rather than only returned: production is now holding test-prefixed data, and
            # that should be findable later by someone reading logs, not only by whoever passed it.
            action.log(
                message_type="test_data_on_prod_allowed", namespace=namespace, name=name,
                warning=accepted_anyway(refusal),
            )

        # Dedup before the compile, not after. The signature is a hash of the authored rows — no
        # reference, no parquet build — so it is cheap and available now, and rejecting here saves a
        # duplicate the entire cost of enrich + compile. Same value the compiler will stamp onto
        # `manifest.content_signature`.
        _reject_duplicate_content(
            repo, spec_dir, namespace, name, action,
            scope_account=published_by if duplicate_scope_account(settings) else None,
        )

        # The network tier, as a separate step ahead of the compile (CONSTITUTION Principle 2).
        # Writes `resolution.csv` into the spec dir; the compiler reads it from there.
        enriched = enrich_spec(spec_dir, settings, action=action)

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            result = compile_module(
                spec_dir,
                out_dir,
                # Always on: in 0.5 this is the master switch for consuming `resolution.csv` at all,
                # not just for network lookups (the compiler never fetches). Off would mean the
                # enrichment we just ran is ignored and every rsID-authored variant stays unresolved.
                # Deliberately not a setting — there is no coherent deployment that wants it off.
                resolve_with_ensembl=True,
                # NB: no `ensembl_cache=`. That parameter is deprecated (removal at 1.0) and its
                # implementation lazily imports the enricher from inside the compile path, which is
                # exactly the tier violation this two-step pipeline exists to avoid.
                authority_keys=IDENTITY_AUTHORITY_KEYS,
                strict=settings.compile_strict,
                ba1_threshold=settings.ba1_threshold,
                # Trust token stamped into the manifest + enforced by just-dna-format's
                # verify_manifest. Deliberately kept as the legacy value "marketplace-server" across
                # the registry rebrand: it's an internal token (not user-facing), and changing it
                # would invalidate every already-published manifest until re-baked. Retire at the
                # next just-dna-format major cleanup, not here.
                compiled_by=MARKETPLACE_COMPILED_BY,
                ensembl_reference=settings.ensembl_reference,
                # `log_files` / `provenance_file` / `logo_file` are left to the compiler's own
                # discovery over `spec_dir`, which finds exactly what the registry used to gather by
                # hand (`*.log`, `logs/**.log`, `provenance.json`, `logo.{png,jpg,jpeg}`) and copies
                # them into `out_dir` — so the carry-forward loop below already skips them.
            )
            action.log(
                message_type="compiled", success=result.success,
                errors=result.errors[:20], warnings=result.warnings[:20],
                strict=settings.compile_strict,
            )
            if not result.success or result.manifest is None:
                # The compiler names *which* variants have no position; it cannot know that the
                # reason was an offline enrichment against an unprovisioned snapshot. Supply that
                # half, so whichever of the two people can act — publisher or operator — can.
                errors = list(result.errors)
                if enriched.unresolved or not enriched.ran:
                    errors.append(unresolved_hint(enriched, settings))
                raise PublishError(
                    "compile_failed",
                    errors=errors,
                    warnings=result.warnings + enriched.notes + normalization.warnings,
                    info=normalization.info + validation.info,
                )

            manifest = result.manifest
            if manifest.identity.name != name:
                raise PublishError(
                    "name_mismatch",
                    errors=[f"module_spec name {manifest.identity.name!r} != path {name!r}"],
                )

            manifest.identity.namespace = namespace
            manifest.identity.version = version
            manifest.identity.canonical_id = canonical_id(namespace, name, version)
            manifest.owner = owner
            manifest.published_at = now_iso()
            if settings.signing_key is not None:
                # Sign the byte identity (SPEC §5); clients pin the pubkey served at /pubkey.
                manifest.signature = sign_digest(
                    manifest.artifact.digest,
                    settings.signing_key.read_bytes(),
                    signed_at=manifest.published_at,
                )
            write_manifest(manifest, out_dir / "manifest.json")

            # Carry spec inputs (yaml/csv/md/logo) into the module dir; skip parquets (the
            # recompiled ones in out_dir are authoritative) and anything compile produced (logs).
            for src in spec_dir.rglob("*"):
                if not src.is_file() or src.suffix == ".parquet":
                    continue
                dest = out_dir / src.relative_to(spec_dir).as_posix()
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)

            stored = {
                p.relative_to(out_dir).as_posix(): p.read_bytes()
                for p in out_dir.rglob("*")
                if p.is_file()
            }
            key = version_key(namespace, name, version)
            storage.store_module(key, stored)
            # The card's prose (S5). Read from what was actually stored rather than from the upload,
            # so the projection and the bytes a downloader gets cannot disagree. Absent → `None`,
            # which leaves an earlier version's readme in place instead of blanking the card.
            #
            # **Named by the manifest since 0.17**, falling back to the constant only for a compile
            # that attested none. That is the whole of what `manifest.readme` buys the projection: the
            # text itself is not in the manifest and cannot be (it is a hash, not a copy), but *which
            # file is the readme* now is — so a reindex no longer has to know the convention, and if
            # upstream's `README_CANDIDATES` ladder ever resolves a spelling ours does not, this
            # follows it rather than silently projecting nothing.
            readme_name = manifest.readme.name if manifest.readme is not None else README_FILE
            readme_bytes = stored.get(readme_name)
            ingest_manifest(
                repo,
                manifest,
                changelog=changelog,
                published_by=published_by,
                readme=readme_bytes.decode("utf-8", errors="replace") if readme_bytes else None,
            )
            action.add_success_fields(
                digest=manifest.artifact.digest,
                content_signature=manifest.content_signature,
                storage_key=key,
                n_files=len(stored),
                variant_count=manifest.stats.variant_count,
                logs=[e.name for e in manifest.logs],
                resolution_mode=manifest.compilation.resolution_mode,
                fully_resolved=manifest.compilation.fully_resolved,
            )
            return manifest


def _reject_duplicate_content(
    repo: Repository, spec_dir: Path, namespace: str, name: str, action: Any,
    *, scope_account: Optional[int] = None,
) -> str:
    """Refuse a republish of data already listed under a *different* `(namespace, name)`.

    `artifact.digest` cannot gate this: the module name is baked into the compiled parquets, so a
    rename produces different bytes and a different digest. The content signature is the identity
    built for the job — a hash of the authored rows, normalized, with `defaults:` folded in and the
    declared build included, so it survives a reformat, a row reorder, and a recompile against a
    different reference, and moves when the data genuinely differs.

    A collision under the *same* module (a later version with unchanged data) is fine and allowed.
    Returns the signature.

    `scope_account` narrows the search to versions that account published, which is what the polygon
    passes (`testdata.duplicate_scope_account`). On a shared test box a cross-account block is noise
    about somebody else's rehearsal; within-account still exercises the gate, so a publisher meets their
    own rename being refused here rather than for the first time on production. Production passes `None`
    and considers every version, because a name-independent signature exists precisely to catch a
    re-list under a new owner.

    Rows whose `content_hash` is empty are pre-0.5 and have not been re-derived yet
    (`registry rederive-signatures`); the repository filters them out rather than letting an empty
    string collide with itself and 409 every publish during the migration window.
    """
    signature = content_signature(spec_dir)
    elsewhere = [
        r for r in repo.find_versions_by_content(signature)
        if (r["namespace"], r["name"]) != (namespace, name)
        and (scope_account is None or r["published_by"] == scope_account)
    ]
    if elsewhere:
        where = ", ".join(f"{r['namespace']}/{r['name']}@{r['version']}" for r in elsewhere)
        action.log(message_type="duplicate_content", signature=signature, published_as=where)
        raise PublishError(
            "duplicate_content",
            errors=[f"identical module data already published as: {where}"],
        )
    return signature


def amend_logo(
    *,
    repo: Repository,
    storage: StorageBackend,
    namespace: str,
    name: str,
    version: str,
    filename: str,
    data: bytes,
) -> ModuleManifest:
    """Replace a published version's logo without a version bump.

    The logo is out of `artifact.digest` (SPEC §5 / manifest contract), so swapping it leaves the
    digest — and any signature over it — intact. Mirrors `amend_changelog`: metadata only,
    owner-gated at the router. Updates the stored `manifest.logo` entry, re-stores the logo bytes
    and the refreshed `manifest.json`, and refreshes the DB projection.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in LOGO_EXTENSIONS:
        raise PublishError(
            "invalid_logo", errors=[f"logo must be one of {sorted(LOGO_EXTENSIONS)}, got {filename!r}"]
        )
    raw = repo.get_manifest_json(namespace, name, version)
    if raw is None:
        raise PublishError("version_not_found")
    manifest = ModuleManifest.model_validate_json(raw)

    logo_name = f"logo.{ext}"
    manifest.logo = FileEntry(name=logo_name, sha256=sha256_bytes(data), size=len(data))

    key = version_key(namespace, name, version)
    storage.store_module(
        key,
        {logo_name: data, "manifest.json": manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"},
    )
    repo.set_version_manifest(namespace, name, version, manifest)
    return manifest


def amend_readme(
    *,
    repo: Repository,
    storage: StorageBackend,
    namespace: str,
    name: str,
    version: str,
    text: str,
) -> str:
    """Replace a published version's readme prose without a version bump.

    Mirrors `amend_logo`: prose about a module is not its content, so it is out of
    `artifact.digest` and swapping it leaves the digest — and any signature over it —
    intact. On an immutable registry that is the whole point: a caveat phrased badly must be
    fixable without burning a version number and claiming a second `content_hash`.

    **The asymmetry with the logo closed in 0.17.** Through 0.16 `amend_logo` recorded its swap on
    `manifest.logo` while this wrote bytes to storage and text to the DB, with the manifest saying
    nothing about either — so the readme was the one column no manifest could produce, and a
    re-ingest that did not know about readmes would have blanked every card (which is why
    `upsert_module(readme=None)` has to mean *leave it*). Format 0.6 added `manifest.readme` as the
    answer to S5, and this now sets it exactly as `amend_logo` does: the manifest is the source of
    truth again and the DB is a projection of it.

    The entry is a hash, not just a name, so an amended readme stays verifiable — a downloader
    re-hashes it via `verify_manifest(check_readme=True)`. That is the difference the attestation
    makes: before it, prose was bytes we served and no client could check; now it travels with the
    module. Still out of `artifact.digest` **and** `content_signature`, so amending it moves no
    identity and cannot collide with the `409 duplicate_content` claim of the module it describes.
    """
    raw = repo.get_manifest_json(namespace, name, version)
    if raw is None:
        raise PublishError("version_not_found")
    manifest = ModuleManifest.model_validate_json(raw)

    data = text.encode("utf-8")
    manifest.readme = FileEntry(name=README_FILE, sha256=sha256_bytes(data), size=len(data))

    key = version_key(namespace, name, version)
    storage.store_module(
        key,
        {
            README_FILE: data,
            "manifest.json": manifest.model_dump_json(indent=2).encode("utf-8") + b"\n",
        },
    )
    repo.set_version_manifest(namespace, name, version, manifest)
    repo.set_module_readme(namespace, name, text)
    return text


# ── Archive helpers ─────────────────────────────────────────────────────────────


def _reject_expansion(total: int, settings: Settings) -> None:
    """Refuse an archive that expands past `max_extracted_bytes`.

    Checked from the member headers, before a byte is written: a compression ratio is unbounded, so
    the transfer bound says nothing about what lands on disk. Without this the archive route was the
    one place a 25 MiB body could become an arbitrarily large extraction.
    """
    if total > settings.max_extracted_bytes:
        raise PublishError(
            "archive_too_large",
            errors=[
                f"archive expands to {total} bytes; the limit is {settings.max_extracted_bytes} "
                f"({settings.max_extracted_bytes // (1024 * 1024)} MiB)"
            ],
        )


def _extract_archive(data: bytes, dest: Path, settings: Settings) -> None:
    """Safely extract a zip or tar.gz archive into `dest`.

    Guards path traversal (always did) and expansion (0.11.1). Both are checked across every member
    before anything is written, so a refusal leaves nothing behind.
    """
    buf = io.BytesIO(data)
    if zipfile.is_zipfile(buf):
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            root = dest.resolve()
            for member in zf.namelist():
                if not (dest / member).resolve().is_relative_to(root):
                    raise PublishError("unsafe_archive", errors=[f"path escapes archive: {member}"])
            # `file_size` is the declared uncompressed size from the central directory. A lying
            # header is not a bypass: it can only *understate* what `extractall` then writes, and
            # the transfer bound already caps how much compressed input exists to inflate.
            _reject_expansion(sum(i.file_size for i in zf.infolist()), settings)
            zf.extractall(dest)
        return
    buf.seek(0)
    try:
        with tarfile.open(fileobj=buf, mode="r:*") as tf:
            # tar has no central directory, so this walks the headers — decompressing the stream
            # without writing files. Bounded by `max_upload_bytes` on the compressed input.
            _reject_expansion(sum(m.size for m in tf.getmembers() if m.isfile()), settings)
            tf.extractall(dest, filter="data")  # 'data' filter blocks traversal/special files
    except tarfile.TarError as exc:
        raise PublishError("bad_archive", errors=[f"not a valid zip or tar.gz: {exc}"])


def _module_root(extracted: Path) -> Path:
    """Locate the directory holding the module (spec or legacy parquets) within an extraction."""
    for marker in ("module_spec.yaml", _REVERSE_MARKER):
        hits = sorted(extracted.rglob(marker))
        if hits:
            return hits[0].parent
    raise PublishError(
        "no_module_content",
        errors=["archive contains neither module_spec.yaml nor weights.parquet"],
    )


def _reverse_kwargs(display: Optional[dict]) -> dict:
    """Filter client-supplied metadata to `reverse_module`'s accepted, non-null keys.

    `genome_build` is on this list and is not display metadata — it is the one value here that is
    inside `artifact.digest`. It reaches a compiled module through `manifest.json` and no parquet
    column, so `reverse_module` reads it from the artifact's own manifest and falls back to `GRCh38`
    for a bare parquet directory that has none. That fallback is right for the common case and
    silently wrong for a GRCh37 legacy archive: the build decides the identity key, so the recompile
    would mint `ga4gh:VA.…` ids for GRCh37 coordinates against GRCh38 accessions — an allele id
    naming a base 228 bp from the one the module meant, with a moved digest and nothing downstream
    able to notice. Passing it through gives the importer the override the compiler documents
    (`reference_examples/grch37_build/`); omitted, the manifest still wins.
    """
    allowed = ("title", "description", "report_title", "icon", "color", "genome_build")
    display = display or {}
    return {k: display[k] for k in allowed if display.get(k) is not None}
