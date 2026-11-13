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
"""

import json
import shutil
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

    def stale_reason(self) -> str | None:
        """Why this result may not be published now, or `None` when it may."""
        recorded = self.record.get("toolchain") or {}
        now = toolchain()
        moved = [f"{p} {recorded.get(p)} → {now[p]}" for p in TOOLCHAIN if recorded.get(p) != now[p]]
        if moved:
            return f"re-derived under another toolchain ({', '.join(moved)}); re-derive it"
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
) -> HeldRederivation:
    """Keep `spec_dir` as the re-derivation of `predecessor` left it; replaces an older held one."""
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
