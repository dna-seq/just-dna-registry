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
    side (None) is treated as compatible: don't block on missing information.

    **What this certifies, stated because a silence here was read as a broader claim (S18).** It is
    about *exchanging compiled artifacts*: whether a digest this pair computes on either side means
    the same thing. It says nothing about whether the **authored row schema** the server validates
    against is the one the client's tooling writes — that tightens at PATCH grain, because every row
    model is `extra="forbid"` and a patch release may add a column (`StudyRow.curator` arrived in
    format 0.6.5). So a `True` here is compatible-at-the-contract and still refusable at the row, and
    a consumer who read the handshake as certifying the whole exchange found out at a publish. Do not
    narrow this to PATCH to close that gap: within a minor the parquet contract really does hold, and
    refusing 0.6.6↔0.6.1 would reject every pair we actually run. `schema_gap_advisory` reports the
    residue instead."""
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


def schema_gap_advisory(server_format: str | None, client_format: str | None) -> str | None:
    """Context for a client whose `just-dna-format` is newer than the server's *within one minor*.

    The failure it exists for (S18): every spec row model is `extra="forbid"`, so a column added by a
    format PATCH is rejected by an older instance as `Extra inputs are not permitted` — pydantic's
    sentence for a **typo**. The two are byte-identical findings, verified: a `curator` column and a
    `curatr` column produce the same line on an instance that knows neither. So the server cannot
    diagnose the cause from the error, and does not try. It reports the one thing it does know for
    certain — that the two sides differ, and by how much — and lets the author decide.

    Deliberately **not** conditioned on the validation having failed. A version skew is a fact about
    the pair, true whether or not anything tripped over it, and a field that appears only on failures
    makes its own absence ambiguous — the sibling-field rule in CLAUDE.md, one altitude up.

    Returns None when either side is unknown or unparseable, when the versions match, when the
    *client* is the older side (a patch adds columns rather than removing them, so an older client's
    spec stays legal on a newer instance), and when the gap is a MINOR or MAJOR — that one is fatal
    and `compatibility_error` already says so in stronger terms.
    """
    if not server_format or not client_format or server_format == client_format:
        return None
    try:
        s, c = parse_version(server_format), parse_version(client_format)
    except ValueError:
        return None
    if (s.major, s.minor) != (c.major, c.minor) or c.patch <= s.patch:
        return None
    return (
        f"just-dna-format skew: your client reports {client_format}, this instance validates against "
        f"{server_format}. Columns and keys added between {server_format} and {client_format} do not "
        f"exist in this instance's row models, which refuse an unknown column with the same finding a "
        f"misspelled one gets. If a column you were told to author is rejected as an extra input, "
        f"check it against {server_format} before assuming a typo — and ask the operator to upgrade "
        f"the instance, since dropping the column would change your authored bytes and with them the "
        f"module's content_signature."
    )


def compatibility_error(server: VersionInfo, client: VersionInfo) -> str | None:
    """A human, actionable message if `server` and `client` are contract-incompatible, else None.

    Only genuine wire/artifact breakers are fatal (API version; `just-dna-format` contract). A
    differing registry *app* version is not fatal — the API is path-versioned — so it is not
    reported here; use `VersionInfo` directly if you want to surface it as a note.

    A PATCH-grain format gap is **not** an error and never becomes one here: it breaks no digest and
    no wire shape. It can still cost an author a publish, so it is reported as advice rather than as
    a refusal — `schema_gap_advisory`, carried on the dry-run reports where the refusal lands."""
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
