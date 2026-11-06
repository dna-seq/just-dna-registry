"""Which spec columns arrived between two format releases (0.28, S18/S21, the liaison's C3).

The server's `format_advisory` says the two sides differ at patch grain and cannot say more, because an
older instance's row models lack the very column in question and its finding is pydantic's sentence for
a typo. This is the other half, computed **on the client** from the schema alone: for each authored
table the caller sends, the columns whose first release (upstream's `base.field_first_seen`, RM146) is
after the server's format and no later than the client's. A refused column in that list means the
instance is behind; one in no list is a typo. Nothing here reads an error string.

The filename → row model map is upstream's `model_for`, in the compiler tier, which a thin client may
not have installed: then `available()` is false and the renderer says so instead of listing nothing.
"""

from collections.abc import Iterable

from just_dna_format.base import field_first_seen
from just_dna_format.identity import parse_version

try:  # the compiler tier is an optional extra for a client
    from just_dna_compiler.draft import DraftError, model_for
except ImportError:  # pragma: no cover - exercised only on a base install
    model_for = None  # type: ignore[assignment]
    DraftError = LookupError  # type: ignore[assignment,misc]


def available() -> bool:
    """Whether this install can name the columns (it has the compiler tier's `model_for`)."""
    return model_for is not None


def columns_added_between(
    server_format: str | None, client_format: str | None, csv_names: Iterable[str]
) -> dict[str, dict[str, str]]:
    """`{csv: {column: release}}` for every column of the named authored tables that first appeared
    after `server_format` and no later than `client_format`. Empty when either version is unknown,
    when the client is not the newer side, or when the compiler tier is absent; a CSV this format does
    not read as an authored table is skipped."""
    if model_for is None or not server_format or not client_format:
        return {}
    try:
        server, client = parse_version(server_format), parse_version(client_format)
    except ValueError:
        return {}
    if client <= server:
        return {}
    out: dict[str, dict[str, str]] = {}
    for csv in sorted(set(csv_names)):
        try:
            model = model_for(csv)
        except DraftError:
            continue
        added = {
            field: release for field, release in field_first_seen(model).items()
            if server < parse_version(release) <= client
        }
        if added:
            out[csv] = dict(sorted(added.items()))
    return out
