"""What `registry upgrade`'s sweep says about each module, and the counts it ends on (0.28.2).

**The terminal gets one line per module and the counts; the run's log gets everything.** Through
0.28.1 the sweep printed every refusal's drift list, every publish's digest line and every enricher
warning to the terminal, so on a real catalog the per-module verdicts were lost among the detail. Each
module is now one `SweepItem`: a short head (a status and a code) and the detail that used to follow
it. The head is printed whole, once the module is done, so a sweep that processes modules concurrently
still prints whole lines; the detail goes to the log as one record (`just_dna_registry.sweep`, INFO,
which the run's file handler takes and the terminal's does not). `--verbose` prints the detail too.

**Every count is keyed by a code something already emitted, never by a sentence**: a refusal by
`PublishError.detail`, a hold by the sweep's own code, a failure by its exception type, a successor's
compile warnings by upstream's `compilation.warnings_summary` keys (split only by upstream's own
`CARRIED_WARNING_CODES`), and a logged warning by its logger's name. The *type* a code is grouped under
is a table here, and a code the table does not name is `other`, shown with its code, never dropped.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from just_dna_format.vocab import CARRIED_WARNING_CODES

PUBLISHED = "published"
REFUSED = "refused"
HELD = "held"
BLOCKED = "blocked"
FAILED = "failed"
WOULD_UPGRADE = "would upgrade"
UNCHANGED = "unchanged"
ANOMALY = "anomaly"

#: Statuses that end a module without a successor for a reason somebody has to act on.
PROBLEMS: tuple[str, ...] = (REFUSED, FAILED, HELD, BLOCKED, ANOMALY)

#: The sweep's own hold codes. Before 0.28.2 a hold was a sentence; the sentence is the detail now.
HELD_SNAPSHOT = "snapshot_not_current"
HELD_NEEDS_ONLINE = "needs_online"

#: How a problem's code is grouped on the summary line. Keyed by `(status, code)` for codes this
#: service emits; a failure is keyed by its exception's class name.
TYPE_OF: dict[tuple[str, str], str] = {
    (REFUSED, "rederive_drift_needs_reading"): "drift to read",
    (REFUSED, "invalid_spec"): "validation",
    (REFUSED, "compile_failed"): "validation",
    (REFUSED, "missing_spec_files"): "validation",
    (REFUSED, "ambiguous_spec_layout"): "validation",
    (REFUSED, "no_module_content"): "validation",
    (REFUSED, "name_mismatch"): "validation",
    (REFUSED, "short_description_not_one_line"): "validation",
    (REFUSED, "short_description_too_long"): "validation",
    (REFUSED, "invalid_logo"): "validation",
    (REFUSED, "enrich_failed"): "enrichment",
    (REFUSED, "enrichment_failed"): "enrichment",
    (REFUSED, "license_refused"): "enrichment",
    (REFUSED, "enrichment_unavailable"): "network",
    (REFUSED, "enrichment_busy"): "network",
    (REFUSED, "too_many_variants"): "network",
    (REFUSED, "enrichment_timeout"): "timeout",
    (REFUSED, "duplicate_content"): "catalog",
    (REFUSED, "version_exists"): "catalog",
    (REFUSED, "test_data_on_prod"): "catalog",
    (HELD, HELD_SNAPSHOT): "snapshot",
    (HELD, HELD_NEEDS_ONLINE): "network",
    (BLOCKED, "contract_rejects"): "contract",
    (ANOMALY, "identical_compiler_drift"): "reliability",
}

#: A failure's type by exception class name, for the failures this sweep can meet. Names rather than
#: classes so this module imports neither httpx nor the enricher; the class name is the structured fact.
FAILURE_TYPE_OF: dict[str, str] = {
    "TimeoutError": "timeout",
    "TimeoutException": "timeout",
    "ReadTimeout": "timeout",
    "ConnectTimeout": "timeout",
    "ConnectError": "network",
    "TransportError": "network",
    "RemoteProtocolError": "network",
    "HTTPStatusError": "network",
    "ConnectionError": "network",
    "OSError": "io",
    "PermissionError": "io",
    "FileNotFoundError": "io",
}

#: A logged warning's type by its logger's top-level package.
LOGGER_TYPE_OF: dict[str, str] = {
    # The enricher's retry lines (RM403, 0.8.1): one WARNING per retried attempt and per give-up.
    "just_dna_enricher.net": "network",
    "just_dna_enricher": "enrichment",
    "just_dna_compiler": "compile",
    "just_dna_format": "format",
    "just_dna_registry": "registry",
    "httpx": "network",
    "httpcore": "network",
    "urllib3": "network",
    "huggingface_hub": "storage",
}


def logger_type(name: str) -> str:
    """The type a logger's records count under: its longest dotted prefix in `LOGGER_TYPE_OF`, else `other`."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        if (kind := LOGGER_TYPE_OF.get(".".join(parts[:end]))) is not None:
            return kind
    return "other"


@dataclass
class SweepItem:
    """One module's outcome: the line the terminal gets, and the detail the log gets."""

    label: str
    status: str
    code: str
    head: str
    detail: list[str] = field(default_factory=list)
    #: The successor's `compilation.warnings_summary`, for a published module.
    warnings_summary: dict[str, int] = field(default_factory=dict)
    #: Recorded subjects an online re-derivation re-asked (or, in a dry run, would): its egress budget.
    online_subjects: int = 0

    def block(self) -> str:
        """The head with its detail indented under it: the shape `replay.SweepLines.parse` reads."""
        return "\n".join([self.head, *(f"    {line}" for line in self.detail)])

    @property
    def problem_type(self) -> str:
        if self.status == FAILED:
            return FAILURE_TYPE_OF.get(self.code, "unexpected")
        return TYPE_OF.get((self.status, self.code), "other")


class WarningCounter(logging.Handler):
    """Counts WARNING-and-above records by logger name while a sweep runs; formats nothing."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.by_logger: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        self.by_logger[record.name] += 1


@dataclass
class SweepResult:
    """Everything one sweep said, per module, plus the logged warnings it counted."""

    items: list[SweepItem] = field(default_factory=list)
    logged_warnings: Counter[str] = field(default_factory=Counter)

    def text(self) -> str:
        """Every module's block, as `--verbose` prints it."""
        return "\n".join(item.block() for item in self.items)

    def count(self, status: str) -> int:
        return sum(1 for item in self.items if item.status == status)

    def problem_lines(self) -> list[str]:
        """`<type> N (<status> <code> n, ...)`, most frequent type first, one entry per type."""
        by_type: dict[str, Counter[str]] = {}
        for item in self.items:
            if item.status in PROBLEMS:
                by_type.setdefault(item.problem_type, Counter())[f"{item.status} {item.code}"] += 1
        ordered = sorted(by_type.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
        return [
            f"{kind} {sum(codes.values())} ({', '.join(f'{c} {n}' for c, n in codes.most_common())})"
            for kind, codes in ordered
        ]

    def warning_lines(self) -> list[str]:
        """Compile warnings in the successors (actionable / carried, by code) and logged warnings by type."""
        lines: list[str] = []
        compiled: Counter[str] = Counter()
        for item in self.items:
            compiled.update(item.warnings_summary)
        if compiled:
            carried = Counter({c: n for c, n in compiled.items() if c in CARRIED_WARNING_CODES})
            actionable = compiled - carried
            parts = []
            for name, bucket in (("actionable", actionable), ("carried", carried)):
                if bucket:
                    codes = ", ".join(f"{c} {n}" for c, n in bucket.most_common())
                    parts.append(f"{name} {sum(bucket.values())}: {codes}")
            lines.append(f"compile warnings in published successors: {'; '.join(parts)}")
        if self.logged_warnings:
            by_type: dict[str, Counter[str]] = {}
            for name, n in self.logged_warnings.items():
                by_type.setdefault(logger_type(name), Counter())[name] += n
            ordered = sorted(by_type.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
            lines.append(
                "logged warnings: " + "; ".join(
                    f"{kind} {sum(names.values())} ({', '.join(f'{c} {n}' for c, n in names.most_common())})"
                    for kind, names in ordered
                )
            )
        return lines

    def to_json(self) -> dict[str, Any]:
        """The structured record kept beside `run.log` as `sweep.json` (served by `GET /admin/runs/{id}`).

        The same facts the terminal and the log got, keyed rather than worded, so an upstream reading why
        a module was held reads `status` and `code` and never parses a sentence. Paths are not scrubbed
        here: the file stays on this box, and the route scrubs on the way out."""
        return {
            "counts": dict(Counter(item.status for item in self.items)),
            "problems": self.problem_lines(),
            "warnings": self.warning_lines(),
            "logged_warnings": dict(self.logged_warnings),
            "items": [
                {
                    "label": item.label, "status": item.status, "code": item.code,
                    "problem_type": item.problem_type, "head": item.head, "detail": list(item.detail),
                    "warnings_summary": dict(item.warnings_summary),
                    "online_subjects": item.online_subjects,
                }
                for item in self.items
            ],
        }
