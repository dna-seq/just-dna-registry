"""
Server/client version exchange + the compatibility guard.

A client that downloads a server-compiled artifact (and re-verifies its `artifact.digest`), or
publishes a spec the server recompiles, has to agree with the server on the **contract**
(`just-dna-format`) version. Across a format MAJOR — or, while the format is still `0.x`, across a
MINOR — the parquet column set and therefore `artifact.digest` change (the 0.4→0.5 bump is exactly
this: `variant_key` was re-baselined onto the VRS allele id, so every module recompiled under 0.5
gets a new digest), so a mismatched client/server pair produces cryptic digest / catalog-shape
collisions rather than a clear error. This module lets each side advertise its versions and turns an
incompatible pair into an actionable message.

Lives in the light (client) tier: it imports only `pydantic` + `just_dna_format.identity`, both
already present wherever the client runs. `just-dna-compiler` ships in the `compiler` and `server`
extras rather than the base install, so its version is reported as None on a bare client.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from just_dna_format.identity import parse_version
from pydantic import BaseModel, Field

# The REST API is versioned in the path (`/api/v1`); this is that major, exchanged so a client and a
# server that disagree on the wire contract fail fast instead of hitting a 404 maze.
API_VERSION: str = "v1"

_REGISTRY_PKG = "just-dna-registry"
_FORMAT_PKG = "just-dna-format"
_COMPILER_PKG = "just-dna-compiler"


def _installed(pkg: str) -> str | None:
    try:
        return _pkg_version(pkg)
    except PackageNotFoundError:
        return None


class VersionInfo(BaseModel):
    """The versions one side of the wire runs. Exchanged via `GET /api/v1/version`, the
    `X-Registry-Version` / `X-Format-Version` response headers, and the client's request headers."""

    api: str = Field(default=API_VERSION, description="REST API contract version (path `v1`)")
    registry: str = Field(description="just-dna-registry package version")
    format: str | None = Field(default=None, description="just-dna-format contract version")
    compiler: str | None = Field(
        default=None, description="just-dna-compiler version (server tier only; None on a client)"
    )
    mode: str | None = Field(
        default=None,
        description=(
            "`prod` or `test` — which deployment this is (server tier only; None on a client, and "
            "None from a server older than 0.13). Reported because `REGISTRY_MODE` governs every "
            "irreversible decision on the box and was otherwise only inferable from a hostname or "
            "from whether the delete routes happen to be mounted."
        ),
    )

    @classmethod
    def local(cls) -> "VersionInfo":
        """The running process's own versions, read from installed package metadata."""
        return cls(
            api=API_VERSION,
            registry=_installed(_REGISTRY_PKG) or "0.0.0+unknown",
            format=_installed(_FORMAT_PKG),
            compiler=_installed(_COMPILER_PKG),
        )


def installed_compiler() -> str | None:
    """The `just-dna-compiler` version this process would recompile with, or None if not installed.

    Public because the upgrade planner compares a stored manifest's compiler stamp against it to
    decide whether a version's parquet predates the current contract. `None` means *cannot say* there
    — a client install has no compiler tier at all — and must never be read as "up to date".
    """
    return _installed(_COMPILER_PKG)


def contract_compatible(server_format: str | None, client_format: str | None) -> bool:
    """Whether two `just-dna-format` versions can safely exchange compiled artifacts.

    Rule: same MAJOR, and while MAJOR is 0 (pre-1.0) also the same MINOR — a 0.x minor is a breaking
    contract change (the parquet schema / `artifact.digest` move, e.g. 0.4→0.5). Unknown on either
    side (None) is treated as compatible: don't block on missing information."""
    if not server_format or not client_format:
        return True
    try:
        s, c = parse_version(server_format), parse_version(client_format)
    except ValueError:
        return server_format == client_format
    if s.major != c.major:
        return False
    if s.major == 0:
        return s.minor == c.minor
    return True


def compatibility_error(server: VersionInfo, client: VersionInfo) -> str | None:
    """A human, actionable message if `server` and `client` are contract-incompatible, else None.

    Only genuine wire/artifact breakers are fatal (API version; `just-dna-format` contract). A
    differing registry *app* version is not fatal — the API is path-versioned — so it is not
    reported here; use `VersionInfo` directly if you want to surface it as a note."""
    if server.api != client.api:
        return (
            f"API version mismatch: server speaks {server.api!r}, client speaks {client.api!r}. "
            f"Upgrade the older side so both use the same /api/<version> contract."
        )
    if not contract_compatible(server.format, client.format):
        scope = "major.minor" if _is_pre_1_0(server.format, client.format) else "major"
        return (
            f"just-dna-format contract mismatch: server {server.format}, client {client.format}. "
            f"Compiled artifacts (and their digests) only interoperate within a matching {scope} — "
            f"align the client's just-dna-format to the server's (or vice versa) before publishing "
            f"or downloading."
        )
    return None


def _is_pre_1_0(*versions: str | None) -> bool:
    for v in versions:
        if v:
            try:
                if parse_version(v).major == 0:
                    return True
            except ValueError:
                pass
    return False
