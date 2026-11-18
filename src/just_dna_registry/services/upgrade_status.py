"""Which current versions `registry upgrade` has not brought up to date (0.32, `GET /upgrade/status`).

Built after two wrong answers in one day (2026-11-14) to "are the held modules on the polygon published?":
`needs_upgrade` read `false` on all 47 listed modules, four of which the 0.8 sweep had held, because that
flag is `revalidate`'s and says nothing about the sweep; and a desk question kept saying "12 held" a week
after 8 were published. The person: "build a proper endpoint to see the held numbers".

**Two witnesses, never folded.**

* **The recorded sweeps.** Every `upgrade` run keeps `sweep.json` (0.28.3 on, never pruned): one item per
  module, labelled `ns/name@version` with the version it planned from. A version's verdict is the newest
  run's item for that exact version, so a successor published since supersedes the hold by not matching
  it. A hold is any status in `PROBLEMS`: the drift hold is a *refusal* (`rederive_drift_needs_reading`),
  not `held`. Reverted runs are skipped (their catalog changes were undone); `replay-upgrade` runs are
  another command and never read (they sweep a scratch copy). A dry run counts and says so.
* **The version comparison.** A sweep before 0.28.3 kept no record, and the polygon's 0.8 sweep was one:
  its four held modules have no item anywhere. Their manifests still say which compiler built them, and
  `gap_from_stamp` compares that with this server's, as the sweep's own planner does first. It reads the
  catalog row (`json_extract`), never storage, so the planner's storage-reading reasons (a resolution table
  to re-derive, a measured drift) reach this report only through a sweep.

**Zero is never bare.** `swept`, `sweeps_on_record` and `sweeps_since` say how much the first witness
covered, and `behind`/`unknown` are counted apart from `current`, so "nothing held" reads as what was
checked. Codes only leave the process: no run id, no head or detail sentence, no path (the detail is
`GET /admin/runs/{id}`, site admins).
"""

import json
from dataclasses import dataclass

from just_dna_registry.config import Settings
from just_dna_registry.db.repository import Repository
from just_dna_registry.maintenance import SWEEP_FILE, list_runs, read_record
from just_dna_registry.models.api import UpgradeStatusItem, UpgradeStatusReport, UpgradeSweepVerdict
from just_dna_registry.services import held as held_store
from just_dna_registry.services.upgrade import (
    GAP_CONTRACT,
    GAP_UNKNOWN,
    gap_from_stamp,
    installed_snapshot_releases,
)
from just_dna_registry.sweep_report import PROBLEMS, WOULD_UPGRADE
from just_dna_registry.version import installed_compiler

UPGRADE_COMMAND = "upgrade"

HELD = "held"
WOULD = "would_upgrade"
BEHIND = "behind"
UNKNOWN = "unknown"
CURRENT = "current"
#: Every state, in the order a reader acts on them.
STATES: tuple[str, ...] = (HELD, WOULD, BEHIND, UNKNOWN, CURRENT)


@dataclass(frozen=True)
class RecordedSweeps:
    """The newest verdict per `(namespace, name, version)`, and how many runs were read."""

    verdicts: dict[tuple[str, str, str], UpgradeSweepVerdict]
    runs: int
    since: str | None


def _split_label(label: str) -> tuple[str, str, str] | None:
    module, sep, version = label.rpartition("@")
    namespace, slash, name = module.partition("/")
    if not (sep and slash and namespace and name and version):
        return None
    return namespace, name, version


def recorded_sweeps(settings: Settings, repo: Repository) -> RecordedSweeps:
    """Read every live `upgrade` run's `sweep.json`, newest first, keeping the first verdict per version."""
    verdicts: dict[tuple[str, str, str], UpgradeSweepVerdict] = {}
    runs = 0
    since: str | None = None
    for path in reversed(list_runs(settings)):
        try:
            record = read_record(path)
        except (OSError, ValueError):
            continue
        if record.get("command") != UPGRADE_COMMAND or record.get("reverted_by"):
            continue
        sweep_file = path / SWEEP_FILE
        if not sweep_file.is_file():
            continue
        try:
            sweep = json.loads(sweep_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runs += 1
        started = record.get("started")
        since = started or since
        applied = "--apply" in str(record.get("invocation") or "").split()
        for item in sweep.get("items") or []:
            key = _split_label(str(item.get("label") or ""))
            if key is None:
                continue
            # A namespace renamed since (0.29) is looked up under its current name.
            key = (repo.resolve_namespace(key[0]), key[1], key[2])
            if key in verdicts:
                continue
            verdicts[key] = UpgradeSweepVerdict(
                started=started, applied=applied,
                status=str(item.get("status") or ""), code=str(item.get("code") or ""),
                problem_type=str(item.get("problem_type") or ""),
                drift_to_read=int(item.get("drift_to_read") or 0),
            )
    return RecordedSweeps(verdicts, runs, since)


def _state(gap: str, verdict: UpgradeSweepVerdict | None, kept: bool) -> str:
    if kept or (verdict is not None and verdict.status in PROBLEMS):
        return HELD
    if verdict is not None and verdict.status == WOULD_UPGRADE:
        return WOULD
    if verdict is not None:
        # The sweep weighed this version and left it (unchanged), or it is a successor's predecessor
        # entry (published), which `latest_version` has moved past and never reaches here.
        return CURRENT
    if gap == GAP_CONTRACT:
        return BEHIND
    if gap == GAP_UNKNOWN:
        return UNKNOWN
    return CURRENT


def upgrade_status(
    settings: Settings, repo: Repository, *, state: str | None, page: int, per_page: int
) -> UpgradeStatusReport:
    sweeps = recorded_sweeps(settings, repo)
    releases: dict[str, str | None] | None = None
    items: list[UpgradeStatusItem] = []
    for row in repo.current_versions_for_status():
        ns, name, version = row["namespace"], row["name"], row["version"]
        gap = gap_from_stamp(row["compiler_stamp"], has_signature=bool(row["has_signature"]))
        verdict = sweeps.verdicts.get((ns, name, version))
        kept = held_store.find(settings, ns, name, version)
        if kept is not None and releases is None:
            releases = installed_snapshot_releases(settings)  # read once, and only when something is kept
        items.append(UpgradeStatusItem(
            namespace=ns, name=name, version=version,
            state=_state(gap.scale, verdict, kept is not None),
            compiled_under=gap.compiled_under, gap=gap.scale, last_sweep=verdict,
            kept=kept is not None, kept_stale=kept.stale_reason(releases) if kept is not None else None,
        ))
    counts = dict.fromkeys(STATES, 0)
    for item in items:
        counts[item.state] += 1
    swept = sum(1 for item in items if item.last_sweep is not None)
    chosen = [item for item in items if state is None or item.state == state]
    start = (page - 1) * per_page
    return UpgradeStatusReport(
        items=chosen[start:start + per_page], total=len(chosen), page=page, per_page=per_page,
        counts=counts, compiler=installed_compiler(), swept=swept,
        sweeps_on_record=sweeps.runs, sweeps_since=sweeps.since,
    )
