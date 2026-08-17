"""
HTTP client for the registry API — powers the `registry-client` CLI and live integration
tests. Depends only on `httpx` + the `just-dna-format` contract (for verify-then-install).
"""

import io
import logging
import tarfile
from pathlib import Path
from typing import Any, Optional

import httpx
from just_dna_format.integrity import verify_manifest
from just_dna_format.manifest import ModuleManifest, write_manifest

from just_dna_registry.models.api import CheckReport, ValidationReport, VersionRef
from just_dna_registry.specfiles import DERIVED_DIR, DERIVED_FILES
from just_dna_registry.version import VersionInfo, compatibility_error

API_PREFIX: str = "/api/v1"

#: Dropped into `DERIVED_DIR` by `download(layout="split")`, because a folder that appears in a
#: download and nowhere in the docs is a folder somebody deletes.
#:
#: Deliberately **not** named `README.md`: `plan_layout` hoists a recognized spec file out of any
#: subdirectory, so a readme written here would be lifted to the root on the next upload and would
#: either overwrite the module's own prose or collide with it.
_DERIVED_NOTE_FILE: str = "WHERE-THIS-CAME-FROM.md"
_DERIVED_NOTE: str = f"""\
# {DERIVED_DIR}/

The tables in here were written by `just-dna-enricher`, not by the module's author: rsID→coordinate
resolution, gnomAD frequencies, gene metrics, citations, and the source records merged in beside
whatever the author declared. The authored spec is the flat set beside this folder.

The split is this registry's presentation of the module and nothing else depends on it. The manifest
names every one of these files at the spec root, which is also where `just-dna-compiler` reads them,
so a re-upload is flattened back automatically and `content_signature` is unaffected either way.
"""

_log = logging.getLogger("registry.client")

# Spec inputs a publisher uploads; compiled outputs are produced server-side, never uploaded.
# `WHERE-THIS-CAME-FROM.md` is this client's own note to a reader, written by `download(layout=
# "split")` — uploading it back would publish our explanation as if the author had written it.
_SKIP_UPLOAD_SUFFIXES: frozenset[str] = frozenset({".parquet"})
_SKIP_UPLOAD_NAMES: frozenset[str] = frozenset({"manifest.json", "WHERE-THIS-CAME-FROM.md"})


_ARCHIVE_SUFFIXES: tuple[str, ...] = (".tar.gz", ".tgz", ".zip")


def is_archive(path: Path) -> bool:
    """Whether `path` names a spec archive rather than a spec directory."""
    name = Path(path).name.lower()
    return any(name.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES)


def pack_spec(spec_dir: Path) -> bytes:
    """Tar+gzip a spec directory into the archive form the upload routes accept.

    For a spec whose raw parts exceed the server's transfer bound this is the only way through: the
    ClinVar panels are 34–180 MiB authored and 1.8–10.2 MB compressed. Deterministic (no mtimes,
    no owners) so the same spec packs to the same bytes.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for rel, data in gather_spec_files(spec_dir):
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def spec_upload(spec_dir: Path, *, pack: bool) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Build the multipart payload for a spec: loose `files` parts, or one `archive` part.

    One place decides the wire form, so `validate`, `check` and any future pre-flight cannot
    disagree about it.
    """
    spec_dir = Path(spec_dir)
    if is_archive(spec_dir):
        return [("archive", (spec_dir.name, spec_dir.read_bytes(), "application/gzip"))]
    if pack:
        return [("archive", ("spec.tar.gz", pack_spec(spec_dir), "application/gzip"))]
    return [
        ("files", (rel, data, "application/octet-stream"))
        for rel, data in gather_spec_files(spec_dir)
    ]


def gather_spec_files(spec_dir: Path) -> list[tuple[str, bytes]]:
    """Collect uploadable spec files (yaml/csv/md/logo + any logs), as (relative-name, bytes).

    Excludes compiled parquets and manifest.json — the server recompiles. Preserves the `logs/`
    subtree so per-role logs keep their paths.
    """
    spec_dir = Path(spec_dir)
    out: list[tuple[str, bytes]] = []
    for path in sorted(spec_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in _SKIP_UPLOAD_SUFFIXES or path.name in _SKIP_UPLOAD_NAMES:
            continue
        out.append((path.relative_to(spec_dir).as_posix(), path.read_bytes()))
    return out


def split_derived(module_dir: Path) -> list[str]:
    """Move a downloaded module's machine-written tables into `DERIVED_DIR`. Returns what moved.

    Presentation only, and it runs **after** `verify_manifest`: the manifest names these files at the
    root, so a tree split before verification is a tree that fails to verify. Re-uploading the split
    tree is safe in the other direction — the server flattens it back, and none of these files is in
    `SIGNATURE_INPUTS`, so the module's content identity does not move either way.

    Today this moves less than it will: the derived CSVs are stored server-side but the manifest
    attests none of them, so a downloader only receives what `artifact.files`/`inputs`/`logs` list.
    Filed upstream (see `docs/CONSUMER_SUGGESTIONS.md` in `just-dna-format`); the folder is created
    only when something actually lands in it.
    """
    module_dir = Path(module_dir)
    derived_dir = module_dir / DERIVED_DIR
    moved: list[str] = []
    for name in DERIVED_FILES:
        source = module_dir / name
        if not source.is_file():
            continue
        derived_dir.mkdir(exist_ok=True)
        source.replace(derived_dir / name)
        moved.append(name)
    if moved:
        (derived_dir / _DERIVED_NOTE_FILE).write_text(_DERIVED_NOTE, encoding="utf-8")
    return moved


class RegistryError(RuntimeError):
    """A non-2xx response from the registry API."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class VersionMismatchError(RegistryError):
    """The server and this client disagree on the API / `just-dna-format` contract, so exchanging
    compiled artifacts would collide. Raised before publish/download rather than letting a cryptic
    digest or shape error surface downstream."""

    def __init__(self, message: str, *, server: VersionInfo, client: VersionInfo) -> None:
        # 409 Conflict mirrors the API's "your request conflicts with server state" family.
        super().__init__(409, message)
        self.server = server
        self.client = client


class ModeMismatchError(RegistryError):
    """The server is not the deployment the caller said they were aiming at.

    Raised before the first request that could spend anything, because this is the one mistake the
    service cannot undo: a publish that lands on production burns a version number and claims the
    data's `content_hash` globally, and `yank` releases neither. The delete verb that would repair it
    exists only on the polygon — which is the same fact from the other side.
    """

    def __init__(self, *, expected: str, actual: Optional[str], base_url: str) -> None:
        seen = actual or "nothing (a server older than 0.13 does not report its mode)"
        super().__init__(
            409,
            f"{base_url} reports mode {seen}, but this client was told to expect {expected!r}. "
            f"Refusing before anything is spent.",
        )
        self.expected = expected
        self.actual = actual


class RegistryClient:
    """Thin sync client over the registry REST API."""

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: float = 600.0,  # publishes recompile server-side; large modules take minutes
        transport: Optional[httpx.BaseTransport] = None,
        check_version: bool = True,
        expect_mode: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.local_version = VersionInfo.local()
        headers = {
            # Advertise the client's versions so the server can log/guard the exchange too.
            "X-Registry-Client-Version": self.local_version.registry,
            "X-Format-Version": self.local_version.format or "",
            "X-API-Version": self.local_version.api,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # `transport` lets tests drive the ASGI app in-process (httpx.ASGITransport).
        self._http = httpx.Client(
            base_url=self.base_url + API_PREFIX,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self._check_version = check_version
        self._compat_checked = False  # guard runs once per client, lazily
        # `prod` | `test` | None. Asserted lazily beside the version guard rather than in `__init__`,
        # so constructing a client still costs no request — and checked against what the *server*
        # says, never against the hostname, which is the second source of truth this exists to avoid.
        #
        # It therefore fires on the same calls `assert_compatible` already guards: publish, import,
        # download, validate, check, is_published. That is the set that exchanges artifacts or spends
        # a version number, which is the set worth refusing. Cheap reads (`whoami`, listings) are not
        # guarded and do not need to be — landing one on the wrong instance costs nothing and undoes
        # itself. Call `assert_compatible()` directly to settle the question up front.
        self._expect_mode = expect_mode

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "RegistryClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Version guard ───────────────────────────────────────────────────────────

    def server_version(self) -> Optional[VersionInfo]:
        """The server's advertised versions, or None if it's too old to report them (pre-0.7.1:
        `GET /version` 404s). Never raises for a plain missing endpoint."""
        resp = self._http.get("/version")
        if resp.status_code == 404:
            return None
        return VersionInfo.model_validate(self._json(resp))

    def assert_compatible(self) -> None:
        """Fail fast if the server is not one this client should be talking to. Runs once per client.

        Two guards over one `/version` fetch. The contract check is a no-op when
        `check_version=False`, and a server too old to report its version cannot be checked, so it
        only warns. The **mode** check runs whenever `expect_mode` was given, independently of
        `check_version` — the two answer different questions, and someone who turned off the version
        guard has not thereby consented to publishing on an unidentified instance.

        An unreported mode is a failure rather than a pass: a caller who asked for the deployment to
        be verified is worse off believing it was than knowing it could not be. That direction is
        also the cheap one, since the remedy is upgrading the server, while the other direction's
        failure mode is an irreversible publish.
        """
        if self._compat_checked or (not self._check_version and self._expect_mode is None):
            return
        server = self.server_version()
        if self._expect_mode is not None and (server is None or server.mode != self._expect_mode):
            raise ModeMismatchError(
                expected=self._expect_mode,
                actual=server.mode if server else None,
                base_url=self.base_url,
            )
        if not self._check_version:
            self._compat_checked = True
            return
        if server is None:
            _log.warning(
                "server does not report its version (pre-0.7.1); skipping the compatibility guard"
            )
            self._compat_checked = True
            return
        message = compatibility_error(server, self.local_version)
        if message is not None:
            raise VersionMismatchError(message, server=server, client=self.local_version)
        self._compat_checked = True  # only cache a clean pass, so a mismatch re-raises on retry

    def _json(self, resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RegistryError(resp.status_code, detail)
        return resp.json()

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """`_json`'s error handling for a route that returns no body.

        A `204` has nothing to parse, so calling `_json` on one would raise on the *success* path. Shares
        the error extraction rather than duplicating it, so a failure from a bodiless endpoint reads the
        same as any other (`RegistryError(status, detail)`).
        """
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RegistryError(resp.status_code, detail)

    # ── Reads ─────────────────────────────────────────────────────────────────

    def list_modules(
        self,
        *,
        q: Optional[str] = None,
        category: Optional[str] = None,
        gene: Optional[str] = None,
        genome_build: Optional[str] = None,
        owner: Optional[str] = None,
        license: Optional[str] = None,
        namespace: Optional[str] = None,
        featured: Optional[bool] = None,
        include_blacklisted: bool = False,
        has_gene_validity: Optional[bool] = None,
        has_clinical_assertions: Optional[bool] = None,
        has_gwas_effects: Optional[bool] = None,
        has_frequencies: Optional[bool] = None,
        weighting_declared: Optional[bool] = None,
        group: Optional[str] = None,
        sort: str = "name",
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """A page of catalog cards: `{items, total, page, per_page}` (`per_page` max 100).

        Every filter is named rather than swept up from `**kwargs`, because the server ignores a
        query param it does not know: a misspelled facet used to come back as a *wider* result set
        that looks like a working search. `group` ∈ `all|featured|curated|popular|new|test`,
        `sort` ∈ `downloads|recent|name|stars|popular` — the server 422s on anything else.
        `None` filters are dropped rather than sent empty.

        The five fact-table filters (0.17) select on what a module's **current** version carries, and
        are tri-state: omitted is "do not filter", which is not `False`. `weighting_declared=False`
        is the useful negative — it finds modules that have not said what their `weight` column
        means, which is the population you must not aggregate across.
        """
        params: dict[str, Any] = {
            "q": q, "category": category, "gene": gene, "genome_build": genome_build,
            "owner": owner, "license": license, "namespace": namespace, "featured": featured,
            "include_blacklisted": include_blacklisted, "group": group,
            "has_gene_validity": has_gene_validity,
            "has_clinical_assertions": has_clinical_assertions,
            "has_gwas_effects": has_gwas_effects,
            "has_frequencies": has_frequencies,
            "weighting_declared": weighting_declared,
            "sort": sort, "page": page, "per_page": per_page,
        }
        clean = {k: v for k, v in params.items() if v is not None}
        return self._json(self._http.get("/modules", params=clean))

    def get_module(self, namespace: str, name: str) -> dict:
        return self._json(self._http.get(f"/modules/{namespace}/{name}"))

    def resolve_version(self, namespace: str, name: str, version: str) -> str:
        """Map the sentinel `"latest"` to the module's current latest (non-yanked) version; any other
        value passes through unchanged. Raises `RegistryError` if the module has no live version."""
        if version != "latest":
            return version
        latest = self.get_module(namespace, name).get("latest_version")
        if not latest:
            raise RegistryError(404, f"{namespace}/{name} has no published version")
        return latest

    def versions(self, namespace: str, name: str, *, page: int = 1, per_page: int = 20) -> dict:
        """A page of the module's versions: `{items, total, page, per_page}` (`per_page` max 100).
        The listing is paged server-side, so a module with a long history needs the second page."""
        return self._json(
            self._http.get(
                f"/modules/{namespace}/{name}/versions",
                params={"page": page, "per_page": per_page},
            )
        )

    def manifest(self, namespace: str, name: str, version: str) -> ModuleManifest:
        data = self._json(self._http.get(f"/modules/{namespace}/{name}/versions/{version}/manifest"))
        return ModuleManifest.model_validate(data)

    def logs(self, namespace: str, name: str, version: str) -> list[dict]:
        return self._json(
            self._http.get(f"/modules/{namespace}/{name}/versions/{version}/logs")
        )["items"]

    def lookup_by_digest(self, digest: str) -> list[dict]:
        return self._json(self._http.get("/modules/lookup", params={"digest": digest}))["matches"]

    def lookup_by_digests(self, digests: list[str]) -> dict[str, list[dict]]:
        """Batch digest lookup → `{digest: matches}`. Classify many local modules in one request."""
        results = self._json(self._http.post("/modules/lookup", json={"digests": digests}))["results"]
        return {r["digest"]: r["matches"] for r in results}

    # ── Onboarding (community self-service) ──────────────────────────────────

    def register(self, install_id: str, account: str) -> dict:
        """Register an install-id → `{token, account, namespaces}`. No auth (mints the token)."""
        return self._json(
            self._http.post("/auth/register", json={"install_id": install_id, "account": account})
        )

    def namespace_available(self, namespace: str) -> dict:
        return self._json(self._http.get(f"/namespaces/{namespace}"))

    def claim_namespace(self, namespace: str, *, allow_test_data: bool = False) -> dict:
        """Claim an available namespace for the token's account (bearer).

        `allow_test_data=True` claims a `test-`prefixed name on a production instance, which is
        refused by default with `422 test_data_on_prod`. The response then carries a `warnings`
        entry saying so — production is holding test-prefixed data, and `registry purge-test-data`
        selects on exactly that prefix.

        `namespace_available()` predicts this: its `requires_allow_test_data` is the machine-readable
        form of the same rule, so a caller can settle it before spending the claim.
        """
        return self._json(
            self._http.post(
                "/namespaces",
                json={"namespace": namespace, "allow_test_data": allow_test_data},
            )
        )

    def _fetch_file(self, namespace: str, name: str, version: str, rel: str) -> bytes:
        resp = self._http.get(f"/modules/{namespace}/{name}/versions/{version}/files/{rel}")
        if resp.status_code >= 400:
            raise RegistryError(resp.status_code, resp.text)
        return resp.content

    def pubkey(self) -> Optional[str]:
        """The server's Ed25519 public key (base64) for pinning, or None if it doesn't sign."""
        resp = self._http.get("/pubkey")
        if resp.status_code == 404:
            return None
        return self._json(resp)["public_key"]

    def download(
        self,
        namespace: str,
        name: str,
        version: str,
        dest: Path,
        *,
        include_logs: bool = True,
        include_inputs: bool = False,
        public_key: Optional[str] = None,
        layout: str = "flat",
    ) -> ModuleManifest:
        """Download a version's artifact (+ logs/logo/provenance) into `dest` and verify it.

        `version` may be `"latest"`. When `public_key` (base64 raw, pinned out-of-band) is given, the
        manifest's Ed25519 signature over `artifact.digest` is enforced. Returns the verified manifest.

        `include_inputs=True` also fetches the **authored** spec — `module_spec.yaml`, `variants.csv`
        and the table CSVs — and hash-checks each against `manifest.inputs`. Off by default because
        an installer wants the parquets and nothing else; on, this is the difference between a
        downloaded artifact and a downloaded *module*, and it is what makes `layout` mean anything.

        **Since 0.17 it also fetches the machine-written sidecars**, which is what makes a downloaded
        module recompile where it lands. Through 0.16 it could not: `resolution.csv` and the fact
        tables are in neither `artifact.files` nor `manifest.inputs`, so nothing attested them and a
        client had no name to ask for — filed upstream as S26 and answered by format 0.6's
        `manifest.derived`. `verify_manifest(check_derived=True)` re-hashes them like everything else.

        `layout="split"` moves those tables into `derived/` afterwards, so a reader can tell the
        author's files from the enricher's. **Afterwards is the whole of the design:** the manifest
        attests the names as stored, so verification runs on the tree as attested and the split is
        applied to one already proven. Default `"flat"` — nothing existing changes.

        The readme travels too, and is re-hashed (`check_readme`). Before 0.6 it was prose the server
        served and no client could check; `manifest.readme` (S5) is what lets it come along as part
        of the module rather than as a page on a website."""
        if layout not in {"flat", "split"}:
            raise ValueError(f"layout must be 'flat' or 'split', got {layout!r}")
        self.assert_compatible()  # a format mismatch shows up as a digest failure — catch it first
        version = self.resolve_version(namespace, name, version)
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        listing = self._json(
            self._http.get(f"/modules/{namespace}/{name}/versions/{version}/download")
        )
        manifest = self.manifest(namespace, name, version)
        names = [f["name"] for f in listing["files"]]
        if include_logs:
            names += [e["name"] for e in self.logs(namespace, name, version)]
        if include_inputs:
            # `/download` lists `artifact.files` only, so the authored spec is reachable but never
            # arrives unasked. Taken off the manifest rather than a second listing endpoint: these
            # are the entries `check_inputs` verifies against, so one source decides both.
            names += [e.name for e in manifest.inputs]
            # And the derived half, on the same reasoning and from the same place. An authored spec
            # without `resolution.csv` does not recompile to the same artifact — the compiler never
            # fetches, so the coordinates have to arrive with it.
            names += [e.name for e in manifest.derived or []]
        if manifest.logo is not None:
            names.append(manifest.logo.name)
        if manifest.readme is not None:
            names.append(manifest.readme.name)
        if manifest.provenance is not None and manifest.provenance.file:
            names.append(manifest.provenance.file)
        for rel in names:
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(self._fetch_file(namespace, name, version, rel))
        write_manifest(manifest, dest / "manifest.json")
        verify_manifest(
            dest,
            manifest,
            check_logs=include_logs,
            check_inputs=include_inputs,
            check_derived=include_inputs and bool(manifest.derived),
            check_logo=manifest.logo is not None,
            check_readme=manifest.readme is not None,
            check_provenance=manifest.provenance is not None,
            public_key=public_key,
        )
        if layout == "split":
            split_derived(dest)
        return manifest

    # ── Pre-flight: predict a publish before spending one ──────────────────────

    def content_signature(self, spec_dir: Path) -> str:
        """The canonical content signature of a *local* spec. Computed here — no HTTP, no recompile.

        `just_dna_compiler.compiler.content_signature` reads the authored CSVs as parsed rows, with
        no Ensembl resolution and no parquet build, so a publisher can ask "is this already
        published?" before uploading anything. That is the whole point: the registry gates
        `409 duplicate_content` on this value, and until 0.11 a client had no way to compute it.

        Needs the compiler tier, which is not in the base install: `pip install
        just-dna-registry[compiler]` (the `server` extra includes it).
        """
        try:
            from just_dna_compiler.compiler import content_signature
        except ImportError:
            raise RegistryError(
                0,
                "computing a content signature needs just-dna-compiler — install "
                "`just-dna-registry[compiler]`",
            )
        return content_signature(Path(spec_dir))

    def lookup_by_signature(self, signature: str) -> list[VersionRef]:
        """Published versions built from identical authored data, under any name.

        Unlike `lookup_by_digest`, this ignores the module name and the reference the module was
        compiled against — so it catches the rename/rebrand a digest cannot.
        """
        resp = self._http.get("/modules/lookup", params={"signature": signature})
        return [VersionRef.model_validate(m) for m in self._json(resp)["matches"]]

    def lookup_by_signatures(self, signatures: list[str]) -> dict[str, list[VersionRef]]:
        """Batch `lookup_by_signature` — classify a whole local corpus in one request."""
        resp = self._http.post("/modules/lookup", json={"signatures": signatures})
        return {
            r["signature"]: [VersionRef.model_validate(m) for m in r["matches"]]
            for r in self._json(resp)["results"]
        }

    def is_published(
        self, spec_dir: Path, *, namespace: Optional[str] = None, name: Optional[str] = None
    ) -> list[VersionRef]:
        """Where this spec's data is already published, under any name.

        The pre-publish dedup check, in one call. Calls `assert_compatible` first because the
        signature it sends was computed by *this* client's compiler, and a signature computed under a
        different format minor answers about a different algorithm.

        **Pass `namespace=`/`name=` when you are asking "may I publish *this module*", and then an
        empty list means free to publish.** Without them the answer is name-independent, and a hit
        may well be your own earlier version — publish allows a later version of the same module with
        unchanged data (a review pass), and refuses only a re-list under a different name. The
        unfiltered call is still the right one for classifying a local corpus; it is the wrong one
        for a verdict, and reading it as one is what the server-side `published_as` field did until
        0.16 (S10).
        """
        if (namespace is None) != (name is None):
            raise ValueError("pass both namespace and name, or neither — a half-named module "
                             "matches nothing and would silently answer the unfiltered question")
        self.assert_compatible()
        matches = self.lookup_by_signature(self.content_signature(spec_dir))
        if namespace is None:
            return matches
        return [m for m in matches if (m.namespace, m.name) != (namespace, name)]

    def validate(
        self, namespace: str, name: str, spec_dir: Path, *, strict: bool = True, pack: bool = False
    ) -> ValidationReport:
        """Validate a spec server-side without publishing it. Writes nothing.

        The module need not exist; `name` is the name you intend to publish under. A spec that would
        be rejected still returns normally, with `valid=False` and the reasons — findings are data,
        not exceptions.

        `spec_dir` may be a directory or a `.tar.gz`/`.zip` archive. `pack=True` compresses a
        directory client-side, which is what a spec larger than the server's transfer bound needs —
        the raw parts are refused `413` at that size while the archive sails through.

        `report.would_publish_module_level` is the one field to branch on when you want a verdict
        without paying for the network tier: the publish gates that do not scale with the variant
        count, composed server-side so a caller never reimplements them. It has no ceiling and costs
        no egress. It is **not** `would_publish` — `true` means nothing module-level blocks a
        publish, not that one would succeed, since only `check()` runs the tier that can still
        refuse on a reference mismatch or a withdrawn rsID.

        Since 0.16 the dedup half of that verdict quantifies over `report.published_elsewhere` — data
        published under a *different* `(namespace, name)` — rather than over `published_as`, which
        also lists earlier versions of this same module. Republishing your own unchanged data as a
        new version is legal, and the verdict used to say otherwise (S10).
        """
        self.assert_compatible()
        resp = self._http.post(
            f"/modules/{namespace}/{name}/validate",
            params={"strict": strict},
            files=spec_upload(spec_dir, pack=pack),
        )
        return ValidationReport.model_validate(self._json(resp))

    def check(
        self,
        namespace: str,
        name: str,
        spec_dir: Path,
        *,
        strict: bool = True,
        offline: bool = False,
        frequencies: bool = False,
        literature: bool = False,
        identifiers: bool = False,
        acmg: bool = False,
        pgx: bool = False,
        declared_use: Optional[str] = None,
        pack: bool = False,
    ) -> CheckReport:
        """The full publish dry run: validation plus what the server's network tier finds.

        `spec_dir` may be a directory or a `.tar.gz`/`.zip` archive; `pack=True` compresses a
        directory client-side. Use it for a spec too large to send raw — see `validate`.

        Blocks for as long as the server takes — minutes with `frequencies=True`, which is paced at
        roughly six seconds per twenty variants. The client's 600s default timeout covers the
        server's own 300s cap.

        `identifiers=True` adds trait-CURIE (OLS4) and gene-symbol (HGNC) currency. Online only —
        neither publishes a snapshot — so with `offline=True` it reports that nothing was asked
        rather than that nothing was found, and it never moves `would_publish`, since a publish does
        not run it.

        `pgx=True` adds the PharmVar / CPIC / ClinPGx / ClinGen cross-checks. They are gated by
        `declared_use` (`unstated` | `non_commercial` | `commercial`) — every PGx upstream forbids
        sale, so on the server's default each is skipped with a reason rather than queried. Pass
        `non_commercial` to run them.

        The server's variant ceiling applies to **online** runs only, since it bounds paced outbound
        requests and an `offline=True` run makes none — so a panel too large to check online is
        still checkable against the server's snapshots. Over the ceiling you get
        `RegistryError(422, {"error": "too_many_variants", ...})`, whose detail carries the
        `validation` report and `would_publish_module_level` the server had already computed, so a
        refusal still answers the module-level half without a second upload.

        Raises `RegistryError(503, {"error": "enrichment_unavailable", ...})` when the server's
        network tier cannot run at all (`just-dna-enricher` is not installed there) — retrying is
        pointless until an operator changes the deployment. A server that merely holds no snapshot
        answers `200`: the shortfall arrives as a note on `enrichment.notes`, since an online run
        resolves through live Ensembl without one.
        """
        self.assert_compatible()
        resp = self._http.post(
            f"/modules/{namespace}/{name}/check",
            params={
                "strict": strict, "offline": offline, "frequencies": frequencies,
                "literature": literature, "identifiers": identifiers, "acmg": acmg, "pgx": pgx,
                **({"declared_use": declared_use} if declared_use else {}),
            },
            files=spec_upload(spec_dir, pack=pack),
        )
        return CheckReport.model_validate(self._json(resp))

    # ── Publish ────────────────────────────────────────────────────────────────

    def publish(
        self,
        namespace: str,
        name: str,
        version: str,
        spec_dir: Path,
        changelog: str = "",
        *,
        allow_test_data: bool = False,
    ) -> ModuleManifest:
        """Upload a spec directory and publish it as a new version (server-side recompile).

        A `README.md` in `spec_dir` becomes the module's card prose; `amend_readme()` fixes it later
        without a version bump.

        `allow_test_data=True` publishes a `test-`prefixed namespace or `test_`prefixed module name
        onto production, which is refused by default. Deliberate rather than convenient: what it
        buys past the refusal is a version number and a global `content_hash` claim that only a
        purge releases — and `registry purge-test-data` matches that prefix, so data kept here on
        purpose is data a routine cleanup would remove.
        """
        self.assert_compatible()
        files = [
            ("files", (rel, data, "application/octet-stream"))
            for rel, data in gather_spec_files(spec_dir)
        ]
        resp = self._http.post(
            f"/modules/{namespace}/{name}/versions",
            data={
                "version": version, "changelog": changelog,
                "allow_test_data": str(allow_test_data).lower(),
            },
            files=files,
        )
        return ModuleManifest.model_validate(self._json(resp))

    def import_module(
        self,
        namespace: str,
        name: str,
        version: str,
        archive_path: Path,
        *,
        changelog: str = "",
        display: Optional[dict] = None,
    ) -> ModuleManifest:
        """Publish from a zip/tar.gz archive (spec archive or legacy parquet-only + `display`).

        `display` carries the reverse-engineering metadata for a parquet-only archive: `title`,
        `description`, `report_title`, `icon`, `color` — and `genome_build`, which is not display
        metadata at all. The build decides the identity key (`variant_key` is minted against the
        assembly's refget accession), so reversing a GRCh37 archive as the format's GRCh38 default
        mints ids naming a base the module never carried. Pass it for a bare parquet archive that
        carries no `manifest.json` and is not GRCh38; an explicit value always wins.
        """
        self.assert_compatible()
        archive_path = Path(archive_path)
        data = {"version": version, "changelog": changelog}
        for key in ("title", "description", "report_title", "icon", "color", "genome_build"):
            if display and display.get(key) is not None:
                data[key] = display[key]
        resp = self._http.post(
            f"/modules/{namespace}/{name}/versions/import",
            data=data,
            files={"archive": (archive_path.name, archive_path.read_bytes(), "application/octet-stream")},
        )
        return ModuleManifest.model_validate(self._json(resp))

    def amend_changelog(
        self, namespace: str, name: str, version: str, changelog: str, *, append: bool = False
    ) -> dict:
        """Amend a published version's changelog (metadata only; owner token). Returns the new state."""
        resp = self._http.patch(
            f"/modules/{namespace}/{name}/versions/{version}",
            json={"changelog": changelog, "append": append},
        )
        return self._json(resp)

    def amend_logo(
        self, namespace: str, name: str, version: str, logo_path: Path
    ) -> dict:
        """Replace a published version's logo (owner token; out-of-digest, no version bump)."""
        logo_path = Path(logo_path)
        resp = self._http.post(
            f"/modules/{namespace}/{name}/versions/{version}/logo",
            files={"logo": (logo_path.name, logo_path.read_bytes(), "application/octet-stream")},
        )
        return self._json(resp)

    def amend_readme(
        self, namespace: str, name: str, version: str, readme: "Path | str"
    ) -> dict:
        """Replace a published version's readme — the prose on the module's card.

        Owner token; out-of-digest, no version bump, exactly like `amend_logo`. Takes a path to a
        markdown file or the text itself, since both are natural here: a tool usually has the file,
        a human fixing one sentence usually has the string.

        The readme is the field where a module says what it is *not* — that its findings are
        candidates, that an association was not significant. `description` is one sentence and
        cannot carry that, which is why this is amendable at all on an otherwise immutable registry.
        """
        text = readme if isinstance(readme, str) else Path(readme).read_text(encoding="utf-8")
        resp = self._http.post(
            f"/modules/{namespace}/{name}/versions/{version}/readme",
            files={"readme": ("README.md", text.encode("utf-8"), "text/markdown")},
        )
        return self._json(resp)

    def get_tarball(self, namespace: str, name: str, version: str, dest: Path) -> Path:
        """Download a version as a single streamable `tar.gz` to `dest`. `version` may be `"latest"`.
        Returns the path."""
        version = self.resolve_version(namespace, name, version)
        resp = self._http.get(
            f"/modules/{namespace}/{name}/versions/{version}/download", params={"format": "tarball"}
        )
        if resp.status_code >= 400:
            raise RegistryError(resp.status_code, resp.text)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    # ── Identity & profile ──────────────────────────────────────────────────────

    def whoami(self) -> dict:
        """The caller's identity + profile (`account`, `namespaces`, `type`, `display_name`,
        `avatar_url`, `email`). `email` is only ever returned to the account itself."""
        return self._json(self._http.get("/auth/whoami"))

    def update_profile(
        self,
        *,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        funding_url: Optional[str] = None,
    ) -> dict:
        """Edit the caller's own profile. Only the fields passed are sent; pass `""` to clear one.
        `type` is not self-editable. Returns the updated identity."""
        body = {
            k: v
            for k, v in (
                ("email", email), ("display_name", display_name),
                ("avatar_url", avatar_url), ("funding_url", funding_url),
            )
            if v is not None
        }
        return self._json(self._http.patch("/auth/whoami", json=body))

    # ── Namespace membership (admin+ mutations; role grants are owner-gated) ─────

    def members(self, namespace: str) -> list[dict]:
        """List a namespace's members `[{account, role}]` (any member may read)."""
        return self._json(self._http.get(f"/namespaces/{namespace}/members"))["members"]

    def add_member(self, namespace: str, account: str, role: str = "member") -> dict:
        """Add or re-role a member. `role` = `owner` | `admin` | `member`. Adding a member needs
        admin+; granting admin/owner needs owner."""
        return self._json(
            self._http.post(f"/namespaces/{namespace}/members", json={"account": account, "role": role})
        )

    def remove_member(self, namespace: str, account: str) -> dict:
        """Revoke a member's namespace access (admin+; removing an owner needs owner)."""
        return self._json(self._http.delete(f"/namespaces/{namespace}/members/{account}"))

    # ── Orgs (0.9.0) ────────────────────────────────────────────────────────────

    def create_org(self, name: str) -> dict:
        """Create an org account; the caller becomes its owner."""
        return self._json(self._http.post("/orgs", json={"name": name}))

    def org_members(self, org: str) -> list[dict]:
        """List an org's members `[{account, role}]` (any org member may read)."""
        return self._json(self._http.get(f"/orgs/{org}/members"))["members"]

    def add_org_member(self, org: str, account: str, role: str = "member") -> dict:
        """Add or re-role an org member (admin+; granting admin/owner needs owner)."""
        return self._json(
            self._http.post(f"/orgs/{org}/members", json={"account": account, "role": role})
        )

    def set_org_role(self, org: str, member: str, role: str) -> dict:
        """Change an org member's role (owner-only)."""
        return self._json(self._http.put(f"/orgs/{org}/members/{member}/role", json={"role": role}))

    def remove_org_member(self, org: str, member: str) -> dict:
        """Remove an org member (admin+; removing an owner needs owner)."""
        return self._json(self._http.delete(f"/orgs/{org}/members/{member}"))

    def update_org_settings(self, org: str, **fields: Optional[str]) -> dict:
        """Edit an org's profile (owner-only): `funding_url`, `display_name`, `avatar_url`, `email`."""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._json(self._http.patch(f"/orgs/{org}/settings", json=body))

    def create_org_namespace(self, org: str, namespace: str) -> dict:
        """Claim a namespace owned by the org (admin+; access flows via the org-role cascade)."""
        return self._json(
            self._http.post(f"/orgs/{org}/namespaces", json={"namespace": namespace})
        )

    # ── Yank / un-yank (owner-gated) ────────────────────────────────────────────

    def yank(self, namespace: str, name: str, version: str) -> dict:
        """Yank a version — drop it from default listings + `latest`, keep it fetchable."""
        return self._json(
            self._http.post(
                f"/modules/{namespace}/{name}/versions/{version}/yank", json={"yanked": True}
            )
        )

    def unyank(self, namespace: str, name: str, version: str) -> dict:
        """Reverse a yank."""
        return self._json(
            self._http.post(
                f"/modules/{namespace}/{name}/versions/{version}/yank", json={"yanked": False}
            )
        )

    def delete_version(self, namespace: str, name: str, version: str) -> None:
        """**Test instances only.** Hard-delete a version: rows, artifacts, and its content claim.

        Not `yank`, and not a substitute for it. Yank is what production offers: the version stops being
        listed but stays fetchable, so anyone who already installed it keeps verifying. This removes it,
        which is only defensible where nothing downstream is entitled to keep working.

        It exists so a rehearsal on the polygon (`REGISTRY_MODE=test`) is repeatable: a published version
        is immutable and its authored data is claimed by a name-independent `content_hash` that yank does
        **not** release, so without this every test publish permanently burns both a version number and
        the right to publish that data under any other name.

        Against a production registry the verb is not mounted at all, so this raises `405`. That is the
        intended answer rather than a rough edge — a client cannot delete production data by pointing at
        the wrong host.
        """
        self._raise_for_status(
            self._http.delete(f"/modules/{namespace}/{name}/versions/{version}")
        )

    def delete_module(self, namespace: str, name: str) -> None:
        """**Test instances only.** Hard-delete every version of a module, its artifacts and its claims.

        The whole-module form because a rehearsal usually leaves several versions behind, and deleting
        them one at a time is how a cleanup job half-finishes. See `delete_version` for why this exists
        and why production answers `405`; on production, `yank` each version instead.
        """
        self._raise_for_status(self._http.delete(f"/modules/{namespace}/{name}"))

    # ── Social: stars & reviews ─────────────────────────────────────────────────

    def star(self, namespace: str, name: str) -> dict:
        """Star a module (idempotent). Returns `{namespace, name, stars, starred_by_me}`."""
        return self._json(self._http.put(f"/modules/{namespace}/{name}/star"))

    def unstar(self, namespace: str, name: str) -> dict:
        """Remove the caller's star (idempotent)."""
        return self._json(self._http.delete(f"/modules/{namespace}/{name}/star"))

    def reviews(self, namespace: str, name: str, version: Optional[str] = None) -> list[dict]:
        """Reviews/audits for a module, or one version — highlighted first. Anonymous."""
        path = f"/modules/{namespace}/{name}"
        path += f"/versions/{version}/reviews" if version is not None else "/reviews"
        return self._json(self._http.get(path))

    def review(
        self,
        namespace: str,
        name: str,
        version: str,
        *,
        rating: int,
        verdict: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> list[dict]:
        """Post/update the caller's review of a version (one per account per version). Returns the
        version's current review list."""
        body: dict[str, Any] = {"rating": rating}
        if verdict is not None:
            body["verdict"] = verdict
        if notes is not None:
            body["notes"] = notes
        return self._json(
            self._http.put(f"/modules/{namespace}/{name}/versions/{version}/reviews", json=body)
        )

    def delete_review(self, namespace: str, name: str, version: str) -> list[dict]:
        """Remove the caller's own review of a version."""
        return self._json(
            self._http.delete(f"/modules/{namespace}/{name}/versions/{version}/reviews")
        )

    def highlight_review(
        self, namespace: str, name: str, version: str, reviewer: str, *, highlighted: bool = True
    ) -> list[dict]:
        """Owner action: highlight (or un-highlight) a reviewer's review — the `curated` signal."""
        path = f"/modules/{namespace}/{name}/versions/{version}/reviews/{reviewer}/highlight"
        resp = self._http.put(path) if highlighted else self._http.delete(path)
        return self._json(resp)

    # ── Discovery & aggregate stats ─────────────────────────────────────────────

    def groups(self) -> list[dict]:
        """The listing groups (tabs) the catalog defines: `[{key, label, description}]`."""
        return self._json(self._http.get("/modules/groups"))

    def catalog_stats(self, namespace: Optional[str] = None, *, group: Optional[str] = None) -> dict:
        """Aggregate catalog stats by paging the listing — there is no dedicated stats endpoint, so
        this rolls up the card fields (`get_module`/`list_modules`). Optionally scoped to a namespace
        or a group. Returns totals across the matched modules."""
        agg = {
            "modules": 0, "namespaces": 0, "downloads": 0, "stars": 0, "views": 0,
            "reviews": 0, "curated": 0, "variants": 0, "studies": 0, "genes": 0,
        }
        seen_namespaces: set[str] = set()
        page = 1
        while True:
            body = self.list_modules(page=page, per_page=100, namespace=namespace, group=group)
            items = body.get("items", [])
            for card in items:
                stats = card.get("stats") or {}
                agg["modules"] += 1
                seen_namespaces.add(card["namespace"])
                agg["downloads"] += card.get("downloads", 0)
                agg["stars"] += card.get("stars", 0)
                agg["views"] += card.get("views", 0)
                agg["reviews"] += card.get("review_count", 0)
                agg["curated"] += 1 if card.get("curated") else 0
                agg["variants"] += stats.get("variant_count", 0)
                agg["studies"] += stats.get("study_count", 0)
                agg["genes"] += stats.get("gene_count", 0)
            if not items or page * 100 >= body.get("total", 0):
                break
            page += 1
        agg["namespaces"] = len(seen_namespaces)
        return agg

    # ── Ops ────────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        """Server liveness: `{status, version, storage}`.

        Note the absolute URL. `/health` is mounted *outside* `/api/v1` (it answers whether the
        process is up, which is not an API-versioned question) while this client bakes the prefix
        into its base URL — that mismatch is why the endpoint went unwrapped until 0.11.
        """
        resp = self._http.get(f"{self.base_url}/health")
        return self._json(resp)

    def issue_jwt_token(self, api_key: str) -> dict:
        """Exchange a static API key for a short-lived JWT session: `{token, expires_in}`.

        Raises `RegistryError(501, "jwt_disabled")` when the server has no `jwt_secret` configured —
        static keys keep working either way, so this is an optional upgrade rather than a
        prerequisite.
        """
        resp = self._http.post("/auth/tokens", json={"api_key": api_key})
        return self._json(resp)
