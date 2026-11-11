"""Keyed lookups of a snapshot lane's rows, from this box or from the lane's published repo (0.30).

The caching proxy's lane half. A caller with no snapshot asks for the rows of one lane's table that match
identifier keys, and gets the same rows the snapshot holds, read **locally** when this box has the lane and
**remotely** from the lane's published repo when it does not (the person dropped `alphagenome_avi` from the
server for its size and expected it proxied anyway). Upstream's own readers open local paths only (measured
2026-11-11; asked upstream as RM430/RM431), so this reads the snapshot's parquet directly with polars, whose
`hf://` reads prune row groups by the filter: a keyed read is not a download.

Four rules, from the person and the pm's requirements:

* **Keyed, always.** A request names identifier keys (rsID, gene, chromosome and position, ...); there is
  no unkeyed or enumerating query, whatever the lane's terms ("Serving = proxying to full snapshot. Any
  subslice = derivative work"). Keys and rows are bounded per request (`lane_max_keys`, `lane_max_rows`).
* **Bounded remotely too.** A remote table larger than `lane_remote_max_scan_bytes` needs a position key,
  which narrows the read to that chromosome's files; Ensembl by rsID alone cannot be pruned (upstream
  RM431 asks for an index).
* **No filesystem path leaves the process**: `served_from` is `local` or `remote:<repo>`.
* **A lane neither held nor published answers `lane_not_available`**, with why.
"""

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from just_dna_registry.config import Settings
from just_dna_registry.services.enrich import cache_lanes, lane_presence

logger = logging.getLogger("registry.lanes")

#: Columns a lookup may key on: identifiers, never a category. `chrom` only together with `start`.
KEY_COLUMNS: tuple[str, ...] = (
    "rsid", "id", "gene", "genes", "symbol", "variant_id", "variation_id", "pmid", "allele",
    "study_locus_id", "chrom", "start",
)
#: The position column under its spellings: a `start` key reads whichever one a table carries.
POSITION_COLUMNS: tuple[str, ...] = ("start", "pos", "position")
#: A shard or chromosome suffix on a file name, collapsed so one table is one name.
_SHARD = re.compile(r"-(chr[0-9XYMT]+|[0-9]+)$")
_CHROM_IN_NAME = re.compile(r"chr([0-9XYMT]+)$")


class LaneLookupError(ValueError):
    """A lookup this server will not make. `code` is the wire's `error`; `status` its HTTP status."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class LaneTable:
    name: str
    #: Where the files are: local paths, or `hf://` URLs with their sizes.
    files: list[str]
    sizes: list[int]
    kind: str  # parquet | json | csv
    keys: list[str] = field(default_factory=list)


@dataclass
class LaneRows:
    lane: str
    table: str
    served_from: str
    rows: list[dict[str, Any]]
    truncated: bool


def _table_name(stem: str) -> str:
    return _SHARD.sub("", stem)


def _repo(lane: str) -> str | None:
    from just_dna_enricher.locations import SNAPSHOT_REPO_IDS

    return SNAPSHOT_REPO_IDS.get(lane)


def _local_files(root: Path) -> list[tuple[str, int]]:
    return [
        (str(p), p.stat().st_size) for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix in (".parquet", ".json", ".csv") and p.name != "release.json"
        and not p.name.endswith("pull-record.json") and not p.name.startswith(".")
    ]


def _remote_files(repo: str) -> list[tuple[str, int]]:
    from huggingface_hub import HfFileSystem

    fs = HfFileSystem()
    found = fs.find(f"datasets/{repo}", detail=True)
    return [
        (f"hf://{path}", int(info.get("size") or 0)) for path, info in sorted(found.items())
        if path.endswith((".parquet", ".json", ".csv")) and not path.endswith(("release.json", "manifest.json"))
        and "/." not in path
    ]


def lane_source(lane: str, settings: Settings) -> tuple[str, dict[str, LaneTable]]:
    """`(served_from, tables)` for a lane: this box's copy when it holds one, else its published repo."""
    if lane not in cache_lanes():
        raise LaneLookupError("unknown_lane", f"no lane named {lane!r}", status=404)
    where = lane_presence(settings).get(lane)
    if where is not None:
        served_from, listed = "local", _local_files(Path(where))
    elif (repo := _repo(lane)) is not None:
        served_from, listed = f"remote:{repo}", _remote_files(repo)
    else:
        raise LaneLookupError(
            "lane_not_available",
            f"this box does not hold {lane}, and it has no published repo to read from",
            status=404,
        )
    tables: dict[str, LaneTable] = {}
    for path, size in listed:
        name = path.rsplit("/", 1)[-1]
        stem, _, suffix = name.rpartition(".")
        table = tables.setdefault(_table_name(stem), LaneTable(_table_name(stem), [], [], suffix))
        table.files.append(path)
        table.sizes.append(size)
    return served_from, tables


def _parquet_columns(table: LaneTable) -> list[str]:
    import polars as pl

    return list(pl.scan_parquet(table.files[0]).collect_schema().names())


def lane_tables(lane: str, settings: Settings) -> tuple[str, list[dict[str, Any]]]:
    """What a caller can ask of a lane: each table with the key columns it carries."""
    served_from, tables = lane_source(lane, settings)
    out = []
    for table in tables.values():
        columns = _parquet_columns(table) if table.kind == "parquet" else []
        keys = [c for c in KEY_COLUMNS if c in columns]
        if "start" not in keys and "chrom" in keys and any(c in columns for c in POSITION_COLUMNS):
            keys.append("start")
        out.append({
            "table": table.name, "kind": table.kind, "files": len(table.files),
            "keys": keys if columns else ["gene"],
        })
    return served_from, sorted(out, key=lambda t: t["table"])


def _chrom_forms(value: str) -> list[str]:
    bare = value.removeprefix("chr")
    return [bare, f"chr{bare}"]


def lookup(
    lane: str, table_name: str, keys: dict[str, list[Any]], settings: Settings
) -> LaneRows:
    """The rows of `lane`'s `table_name` matching every key given (a column → values filter, ANDed)."""
    if not keys or not any(keys.values()):
        raise LaneLookupError("lane_needs_keys", "a lane lookup needs at least one key; nothing enumerates")
    unknown = sorted(set(keys) - set(KEY_COLUMNS))
    if unknown:
        raise LaneLookupError("unknown_key", f"not a key column: {', '.join(unknown)}")
    if ("chrom" in keys) != ("start" in keys):
        raise LaneLookupError("position_needs_both", "a position key is chrom and start together")
    count = sum(len(v) for v in keys.values())
    if count > settings.lane_max_keys:
        raise LaneLookupError(
            "too_many_keys", f"{count} key values; this server answers at most {settings.lane_max_keys}"
        )
    served_from, tables = lane_source(lane, settings)
    table = tables.get(table_name)
    if table is None:
        raise LaneLookupError(
            "unknown_table", f"{lane} has no table {table_name!r} (it has {', '.join(sorted(tables))})",
            status=404,
        )
    if table.kind != "parquet":
        rows = _small_table_rows(table, keys)
    else:
        rows = _parquet_rows(table, keys, settings, remote=served_from != "local")
    truncated = len(rows) > settings.lane_max_rows
    return LaneRows(lane, table.name, served_from, rows[: settings.lane_max_rows], truncated)


def _parquet_rows(table: LaneTable, keys: dict[str, list[Any]], settings: Settings, *, remote: bool) -> list[dict]:
    import polars as pl

    files = table.files
    if "chrom" in keys:
        wanted = {c.removeprefix("chr") for c in map(str, keys["chrom"])}
        by_chrom = [
            f for f in files
            if (m := _CHROM_IN_NAME.search(f.rsplit("/", 1)[-1].rsplit(".", 1)[0])) and m.group(1) in wanted
        ]
        files = by_chrom or files
    if remote and "chrom" not in keys:
        scanned = sum(size for path, size in zip(table.files, table.sizes, strict=True) if path in files)
        if scanned > settings.lane_remote_max_scan_bytes:
            raise LaneLookupError(
                "remote_needs_position",
                f"{table.name} is {scanned / 1e9:.1f} GB on the hub and this box does not hold it; a key "
                f"without a position cannot be bounded there. Give chrom and start (upstream RM431 asks for "
                f"an index by rsID).",
            )
    frame = pl.scan_parquet(files)
    columns = set(frame.collect_schema().names())
    if "start" in keys and "start" not in columns:
        position = next((c for c in POSITION_COLUMNS if c in columns), None)
        if position is not None:
            keys = {(position if k == "start" else k): v for k, v in keys.items()}
    missing = sorted(set(keys) - columns)
    if missing:
        raise LaneLookupError("unknown_key", f"{table.name} has no column {', '.join(missing)}")
    condition = None
    for column, values in keys.items():
        values = [v for c in values for v in _chrom_forms(str(c))] if column == "chrom" else list(values)
        is_position = column in POSITION_COLUMNS
        if is_position:
            values = [int(v) for v in values]
        dtype = frame.collect_schema()[column]
        clause = (
            pl.col(column).list.eval(pl.element().is_in(values)).list.any()
            if isinstance(dtype, pl.List) else pl.col(column).cast(pl.String).is_in([str(v) for v in values])
            if not is_position else pl.col(column).is_in(values)
        )
        condition = clause if condition is None else condition & clause
    result = frame.filter(condition).head(settings.lane_max_rows + 1).collect()
    return json.loads(result.write_json())


def _small_table_rows(table: LaneTable, keys: dict[str, list[Any]]) -> list[dict]:
    """A JSON or CSV lane (STRchive's catalogue, the ACMG list): small, read whole, filtered by gene."""
    from huggingface_hub import HfFileSystem

    path = table.files[0]
    if path.startswith("hf://"):
        with HfFileSystem().open(path.removeprefix("hf://"), "rb") as handle:
            raw = handle.read()
    else:
        raw = Path(path).read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if table.kind == "csv":
        records = list(csv.DictReader(io.StringIO(text)))
    else:
        loaded = json.loads(text)
        records = loaded if isinstance(loaded, list) else loaded.get("loci") or loaded.get("rows") or []
    wanted = {str(v).upper() for col in ("gene", "symbol") for v in keys.get(col, [])}
    if not wanted:
        raise LaneLookupError("unknown_key", f"{table.name} answers by gene only")
    return [
        r for r in records if isinstance(r, dict)
        and str(r.get("gene") or r.get("symbol") or r.get("gene_symbol") or "").upper() in wanted
    ]
