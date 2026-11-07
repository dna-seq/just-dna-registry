"""Maintenance runs over REST (0.28.3): the enricher-facing runs' records, sweeps and logs, for site admins.

What `registry upgrade` and its kin say about the enricher (which modules were held, by which code, which
upstream logged what, how many attempts a give-up took) is the most useful diagnostic the format project
gets from a real catalog, and until now it lived in `runs/` on the box and reached upstream only as a zip
the person carried. These routes serve it. Three rules.

* **Only the commands that exercise the enricher** (`DIAGNOSTIC_COMMANDS`). An account merge's or rename's
  log names accounts and is nobody's diagnostic; a run of any other command is answered `404`, the same
  as a run that does not exist, so the listing cannot be used to probe for one.
* **Site admins only, on both instances** (the person, 2026-11-07). A run log is operator material.
* **No filesystem path leaves the process.** Every root this box resolves (the runs, the catalog's
  directory, local storage, each snapshot lane, the shared cache base, the interpreter, the working
  directory, home) is replaced by a label, longest first, and then any absolute path still left is
  replaced by `<path>`. Scrubbed on the way out, never on disk: the operator's copy keeps its paths.
  API keys never reached the file (`maintenance.redact`).

A run id is never joined onto a path: it is looked up among `list_runs`, the allow-list.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from just_dna_registry.config import Settings
from just_dna_registry.maintenance import (
    LOG_FILE,
    SWEEP_FILE,
    list_runs,
    read_record,
    run_root,
)
from just_dna_registry.models.api import RunDetail, RunSummary, RunSweep
from just_dna_registry.services.cache_drop import lane_directories

#: The commands whose runs are served: the ones that call the enricher or provision its snapshots.
DIAGNOSTIC_COMMANDS: frozenset[str] = frozenset({"upgrade", "replay-upgrade", "revalidate", "warm-caches"})

#: Any absolute path the known roots did not cover. Not after a word character, `:` or `/`, so an allele
#: (`A/G`), a ratio (`3/5`) and a URL (`https://host/x`) are left alone; the API's own routes are kept.
_LEFTOVER_PATH = re.compile(r"(?<![\w:/.~<>-])/(?!api/)(?:[\w.@+%-]+/)*[\w.@+%-]+/?")


class PathScrubber:
    """Replaces this box's filesystem roots with labels in text bound for a client."""

    def __init__(self, settings: Settings) -> None:
        roots: list[tuple[Path, str]] = [
            (run_root(settings), "<runs>"),
            (settings.db_path.resolve().parent, "<data>"),
            (settings.local_storage_dir, "<storage>"),
            (Path(sys.prefix), "<venv>"),
            (Path(sys.base_prefix), "<python>"),
            (Path.cwd(), "<cwd>"),
            (Path.home(), "~"),
        ]
        base = os.environ.get("JUST_DNA_PIPELINES_CACHE_DIR")
        if base:
            roots.append((Path(base), "<cache>"))
        roots += [(where, f"<cache:{name}>") for name, where in lane_directories(settings).items()]
        spellings: dict[str, str] = {}
        for path, label in roots:
            for form in {str(path), str(path.resolve())}:
                if len(form) > 1:
                    spellings.setdefault(form.rstrip("/"), label)
        #: Longest first, so a lane under the cache base is named as the lane, not as the base.
        self._roots = sorted(spellings.items(), key=lambda kv: -len(kv[0]))

    def __call__(self, text: str) -> str:
        for form, label in self._roots:
            text = text.replace(form, label)
        return _LEFTOVER_PATH.sub("<path>", text)


def _served(settings: Settings) -> dict[str, Path]:
    """`{run id: path}` for every served run, newest first. The allow-list a request's id is read against."""
    out: dict[str, Path] = {}
    for path in reversed(list_runs(settings)):
        try:
            record = read_record(path)
        except (OSError, ValueError):
            continue
        if record.get("command") in DIAGNOSTIC_COMMANDS:
            out[path.name] = path
    return out


def _summary(path: Path, record: dict[str, Any], scrub: PathScrubber) -> RunSummary:
    return RunSummary(
        id=path.name,
        command=str(record.get("command")),
        invocation=scrub(str(record.get("invocation") or "")),
        started=record.get("started"),
        ended=record.get("ended"),
        outcome=record.get("outcome"),
        changed=record.get("changed"),
        pruned=record.get("pruned"),
        reverted_by=record.get("reverted_by"),
        has_log=(path / LOG_FILE).is_file(),
        has_sweep=(path / SWEEP_FILE).is_file(),
    )


def list_served_runs(
    settings: Settings, *, command: str | None, page: int, per_page: int
) -> tuple[list[RunSummary], int]:
    """One page of served runs, newest first, optionally of one command."""
    scrub = PathScrubber(settings)
    runs = [(path, read_record(path)) for path in _served(settings).values()]
    if command is not None:
        runs = [(path, record) for path, record in runs if record.get("command") == command]
    start = (page - 1) * per_page
    return [_summary(path, record, scrub) for path, record in runs[start:start + per_page]], len(runs)


def run_detail(settings: Settings, run_id: str) -> RunDetail | None:
    """The run's record and its structured sweep, scrubbed; `None` for a run not served."""
    path = _served(settings).get(run_id)
    if path is None:
        return None
    scrub = PathScrubber(settings)
    sweep: RunSweep | None = None
    if (path / SWEEP_FILE).is_file():
        sweep = RunSweep.model_validate(json.loads(scrub((path / SWEEP_FILE).read_text(encoding="utf-8"))))
    return RunDetail(run=_summary(path, read_record(path), scrub), sweep=sweep)


def run_log(settings: Settings, run_id: str, *, tail: int | None) -> str | None:
    """The run's `run.log`, scrubbed, or its last `tail` lines; `None` for a run not served or no log."""
    path = _served(settings).get(run_id)
    if path is None or not (path / LOG_FILE).is_file():
        return None
    lines = (path / LOG_FILE).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if tail is not None:
        lines = lines[-tail:]
    scrub = PathScrubber(settings)
    return "".join(scrub(line) for line in lines)
