"""A log file for the long catalog-wide commands, written by the command itself.

`registry upgrade` mints immutable PATCHes and holds modules whose drift a person has to read, and
through 0.28.0 everything it said went to the terminal only: a dropped SSH session or a scrolled-off
buffer lost the list of held modules, the one output the operator has to act on next. So the command
keeps its own record: everything printed (colour codes stripped), the log records at INFO and above,
the command line, and when it started and ended. Nothing to remember to `tee`.

Beside the DB by default (`logs/`), as backups are, so a log sits next to the catalog it describes;
`REGISTRY_RUN_LOG_DIR` moves it. One file per run, never appended to or rotated: the files are small
and an operator prunes them deliberately.
"""

import io
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import click

from just_dna_registry.config import Settings
from just_dna_registry.logging_setup import NOISY_LOGGERS

RUN_LOG_DIRNAME = "logs"


def run_log_dir(settings: Settings) -> Path:
    """Where run logs go: `REGISTRY_RUN_LOG_DIR`, else `logs/` beside the DB."""
    return settings.run_log_dir or (settings.db_path.resolve().parent / RUN_LOG_DIRNAME)


class _Tee(io.TextIOBase):
    """Writes to the live stream as it was, and to the log without colour codes.

    **Outlives the run on purpose.** Anything that captured `sys.stdout` while the run held it (a
    logging handler `configure_logging` builds inside a command, say) keeps this object, and logging
    flushes every handler at interpreter exit. So the log is detached when the run ends, and the tee
    then passes through to the live stream alone, rather than flushing into a closed file.
    """

    def __init__(self, live: TextIO, log: TextIO) -> None:
        self._live: TextIO = live
        self._log: TextIO | None = log

    def detach_log(self) -> None:
        self._log = None

    def write(self, text: str) -> int:
        self._live.write(text)
        if self._log is not None:
            self._log.write(click.unstyle(text))
        return len(text)

    def flush(self) -> None:
        self._live.flush()
        if self._log is not None:
            self._log.flush()

    def isatty(self) -> bool:  # colour on the terminal decides as it would without the log
        return self._live.isatty()

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self._live, "encoding", None) or "utf-8"


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def run_log(settings: Settings, command: str, invocation: str) -> Iterator[Path]:
    """Copy this command's output and log records into a new file, and say where it is, first and last."""
    directory = run_log_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    started = _stamp()
    stem = f"{command}-{settings.mode}-{started.replace(':', '').replace('-', '')}"
    path = directory / f"{stem}.log"
    serial = 1
    while path.exists():  # two runs in one second; `open("x")` below still refuses a race
        serial += 1
        path = directory / f"{stem}-{serial}.log"
    live_out, live_err = sys.stdout, sys.stderr
    root = logging.getLogger()
    previous_level = root.level
    with path.open("x", encoding="utf-8") as log:
        log.write(f"# {invocation}\n# started {started}\n")
        handler = logging.StreamHandler(log)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
        handler.setLevel(logging.INFO)
        # With no handler on the root, a WARNING reached the terminal through `logging.lastResort`;
        # adding ours would silence that, so the terminal gets a handler of its own at the same level.
        console = logging.StreamHandler(live_err) if not root.handlers else None
        if console is not None:
            console.setLevel(logging.WARNING)
            root.addHandler(console)
        root.addHandler(handler)
        root.setLevel(min(previous_level or logging.WARNING, logging.INFO))
        for name in NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
        click.echo(f"log: {path}")
        log.write(f"log: {path}\n")
        outcome = "ended"
        tees = (_Tee(live_out, log), _Tee(live_err, log))
        try:
            with redirect_stdout(tees[0]), redirect_stderr(tees[1]):
                yield path
        except BaseException as exc:
            outcome = f"ended by {type(exc).__name__}"
            exit_code = getattr(exc, "exit_code", None)
            if exit_code is not None:
                outcome += f" (exit {exit_code})"
            raise
        finally:
            for tee in tees:
                tee.detach_log()
            root.removeHandler(handler)
            if console is not None:
                root.removeHandler(console)
            root.setLevel(previous_level)
            log.write(f"# {outcome} {_stamp()}\n")
            click.echo(f"log: {path}", file=live_out)
