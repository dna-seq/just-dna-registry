"""Re-derivations held for reading, kept so publishing them costs no second re-derivation (0.31.1).

`registry upgrade --withhold-rederive` refuses a re-derived module whose drift wants reading, as 0.28.0
to 0.31.0 always did. Those releases then dropped the re-derived spec with the publish's temporary
directory, so `--accept-drift` re-derived it again: every online request spent twice, for a result
already in hand (the person, 2026-11-13: "a pathway that does dry run under disguise of upgrade"; and
"if that was ever acceptable it is at the time where only ensembl parquet was queried"). Here the spec
directory as the re-derivation left it (authored files, the re-derived `resolution.csv`, the fact
sidecars) is copied out before the refusal, and `--accept-drift` publishes that copy.

One held result per `(namespace, name, predecessor version)`, under `held/` beside the catalog
(`REGISTRY_HELD_DIR`). Not under the run's directory: runs are pruned (`REGISTRY_RUN_KEEP`), and a prune
would take a held result with it. A held result is **stale**, and never published, when the compiler or
enricher installed now is not the one that produced it, or when the predecessor is no longer the
module's latest version: a different toolchain would publish a result it did not derive. Publishing one
removes it; `revert-run` of that publish does not bring it back (it is not catalog or storage).

**A strict compile refusal keeps the re-derivation too (0.33.1).** Production's online upgrade of 2026-11-17
re-derived three ClinVar modules for about 37 hours, then the compile refused all three over an upstream
placement defect (their S158), and the specs went with the temporary directory: the retry after upstream's fix
would have spent the 37 hours again. A `compile_failed` hold (`reason`) is kept for exactly that retry, so its
staleness rule differs: the **compiler may move**, since a new compiler is what the retry waits for, while the
enricher version and the snapshot releases the re-derivation read (`snapshots`) may not, because either would
derive a different table. A stale one of these is re-derived as before, and the sweep says why.
"""

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any

from just_dna_registry.config import Settings

HELD_DIRNAME = "held"
RECORD = "held.json"
SPEC = "spec"
#: The packages whose installed version a held result must match to be published.
TOOLCHAIN: tuple[str, ...] = ("just-dna-compiler", "just-dna-enricher")
#: Why a re-derivation was kept: its drift wants reading (`--withhold-rederive`, 0.31.1), or the strict
#: compile refused it (0.33.1), which keeps it for a retry under a newer compiler.
DRIFT = "rederive_drift_needs_reading"
COMPILE_FAILED = "compile_failed"
#: What a `compile_failed` hold must still match: the deriving tier only.
DERIVING: tuple[str, ...] = ("just-dna-enricher",)


def held_root(settings: Settings) -> Path:
    return settings.held_dir or (settings.db_path.resolve().parent / HELD_DIRNAME)


def toolchain() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for package in TOOLCHAIN:
        try:
            found[package] = installed_version(package)
        except PackageNotFoundError:
            found[package] = None
    return found


@dataclass(frozen=True)
class HeldRederivation:
    path: Path
    record: dict[str, Any]

    @property
    def changelog(self) -> str:
        """The re-derivation's paragraph (`enrich.rederive_changelog`), for the successor it becomes."""
        return str(self.record.get("changelog") or "")

    @property
    def drift_to_read(self) -> list[str]:
        return list(self.record.get("drift_to_read") or [])

    @property
    def run(self) -> str | None:
        return self.record.get("run")

    @property
    def reason(self) -> str:
        """Why it was kept; a record from 0.31.1 to 0.33.0 names none and was a drift hold."""
        return str(self.record.get("reason") or DRIFT)

    def stale_reason(self, snapshots_now: Mapping[str, str | None] | None = None) -> str | None:
        """Why this result may not be published now, or `None` when it may.

        A drift hold must match the whole toolchain. A `compile_failed` hold must match the enricher and the
        snapshot releases it was derived under (`snapshots_now`: the box's labels as
        `upgrade.installed_snapshot_releases` reads them). Without `snapshots_now` they cannot be shown
        unchanged, so the hold is stale."""
        recorded = self.record.get("toolchain") or {}
        now = toolchain()
        packages = DERIVING if self.reason == COMPILE_FAILED else TOOLCHAIN
        moved = [f"{p} {recorded.get(p)} → {now[p]}" for p in packages if recorded.get(p) != now[p]]
        if moved:
            return f"re-derived under another toolchain ({', '.join(moved)}); re-derive it"
        if self.reason != COMPILE_FAILED:
            return None
        if snapshots_now is None:
            return "the snapshot releases on this box were not read, so they cannot be shown unchanged; re-derive it"
        then = self.record.get("snapshots") or {}
        changed = [
            f"{authority} {then.get(authority)} → {snapshots_now.get(authority)}"
            for authority in sorted(set(then) | set(snapshots_now))
            if then.get(authority) != snapshots_now.get(authority)
        ]
        if changed:
            return f"re-derived under other snapshot releases ({', '.join(changed)}); re-derive it"
        return None

    def files(self) -> dict[str, bytes]:
        spec = self.path / SPEC
        return {
            p.relative_to(spec).as_posix(): p.read_bytes() for p in sorted(spec.rglob("*")) if p.is_file()
        }

    def release(self) -> None:
        shutil.rmtree(self.path)


def _slot(settings: Settings, namespace: str, name: str, predecessor: str) -> Path:
    return held_root(settings) / namespace / name / predecessor


def hold(
    settings: Settings,
    namespace: str,
    name: str,
    predecessor: str,
    spec_dir: Path,
    *,
    drift: dict[str, int],
    drift_to_read: list[str],
    changelog: str,
    offline: bool,
    run: str | None,
    reason: str = DRIFT,
    snapshots: Mapping[str, str | None] | None = None,
) -> HeldRederivation:
    """Keep `spec_dir` as the re-derivation of `predecessor` left it; replaces an older held one.

    `reason` says why (`DRIFT` or `COMPILE_FAILED`); a `COMPILE_FAILED` hold records the `snapshots` it was
    derived under, which its staleness compares."""
    slot = _slot(settings, namespace, name, predecessor)
    if slot.exists():
        shutil.rmtree(slot)
    slot.parent.mkdir(parents=True, exist_ok=True)
    staging = slot.with_name(f".{slot.name}.partial")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(spec_dir, staging / SPEC)
    record = {
        "namespace": namespace, "name": name, "predecessor": predecessor,
        "toolchain": toolchain(), "drift": drift, "drift_to_read": drift_to_read,
        "changelog": changelog, "offline": offline, "run": run,
        "reason": reason, "snapshots": dict(snapshots) if snapshots is not None else None,
        "held_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (staging / RECORD).write_text(json.dumps(record, indent=2, sort_keys=True))
    staging.rename(slot)  # whole or absent: a crash mid-copy leaves only the `.partial` name
    return HeldRederivation(slot, record)


def find(settings: Settings, namespace: str, name: str, predecessor: str) -> HeldRederivation | None:
    slot = _slot(settings, namespace, name, predecessor)
    record = slot / RECORD
    if not record.is_file() or not (slot / SPEC).is_dir():
        return None
    return HeldRederivation(slot, json.loads(record.read_text()))
