"""Removing a snapshot lane from this box, selectively: the inverse of `registry warm-caches`.

Provisioning never deletes (`rebuild_derived_lane` renames the old build aside; `prepare_lane` refuses a
partial directory rather than overwrite it), so before 0.28.3 the only way to give a lane's disk back
was an `rm -rf` on a path the operator had to work out. Upstream's `just-dna-enricher cache prune` is a
different thing: it deletes stray files from a *published* repo, never a local snapshot.

Four rules, each of which a hand `rm` gets wrong somewhere:

* **The path is the one the running server would read**, resolved through `lane_presence` and, for a
  lane that does not resolve, the same configured-or-default directory `lane_status` reports as
  `partial`. Never a path the operator types: a removal that misses the directory the server opens
  frees nothing and leaves the operator believing it did.
* **A path that contains anything else is never removed.** A lane variable pointed at the shared cache
  base (or at `/`, or at the catalog's own directory) would otherwise take every other lane, the catalog
  or the run backups with it. Refused outright, `--force` or not.
* **Two kinds of lane need `--force`**: one anything here reads (`lane_readers`: every enrichment, a
  `/check` pass, a proxy route, or a build of one of those; removing `ensembl` makes publishing an
  rsID-authored module refuse), and one with no published snapshot to pull back (PharmVar needs a
  personal key, ACMG a workbook). Both are recoverable; neither is cheap. OpenTargets left the second kind
  with enricher 0.8.2 (RM408), which published it, so a pulled one drops without `--force`.
* **Leftovers are offered separately** (`--leftovers`): `<lane>.pre-<version>` builds that a derived-lane
  rebuild kept, `.<lane>.rebuild-*` staging that a failed one left, and `.<lane>.dropping-*` from an
  interrupted removal, beside the lanes; since 0.28.6 also every **partial** lane directory (one that
  holds files and is not a readable snapshot, which provisioning refuses to overwrite) and the staging an
  interrupted download or build leaves **inside** a present lane (`INNER_LEFTOVERS`). No resolver reads
  any of them. A lane being provisioned at this moment reads as partial, so not during a `warm-caches`.

The enricher is imported lazily through `services.enrich`, as everywhere: a client install has none.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from just_dna_registry.config import Settings
from just_dna_registry.lane_tags import PUBLISH, reader_tag
from just_dna_registry.maintenance import run_root
from just_dna_registry.services.enrich import (
    RESOLUTION_REFERENCES,
    _lane_directory,
    cache_lanes,
    lane_destinations,
    lane_presence,
)
from just_dna_registry.services.lane_readers import lane_readers

#: Sibling names that no resolver reads, by the prefix each writer gives them.
LEFTOVER_PATTERNS: tuple[str, ...] = ("{name}.pre-*", ".{name}.rebuild-*", ".{name}.dropping-*")

#: What an interrupted download or build leaves inside a lane's own directory, by upstream's private
#: names (a test reads each one off the enricher's source, so a rename fails there rather than here):
#: `*.part`, the temporary file every fetch streams into before its rename (`net.stream_to_file`,
#: `download`); `data.building`, a snapshot build's staging beside the live `data/`
#: (`opentargets_build.build_snapshot`); and `source/`, the Open Targets raw mirror (about 22 GB) a
#: local build downloads into the lane and removes only after a good build (`caches._rebuild_opentargets`).
#: A killed 0.8.1 build left exactly these (2026-11-10). Resolvers read `data/` and the records beside it.
INNER_LEFTOVERS: tuple[str, ...] = ("**/*.part", "**/data.building", "source")


@dataclass(frozen=True)
class LaneDrop:
    """One path this command would remove, and everything an operator needs to decide about it."""

    lane: str
    path: Path
    #: `present` (a readable snapshot), `partial` (a directory that is not one), `leftover`.
    state: str
    size: int
    #: What in this server opens the lane (`lane_readers`); `()` for a lane nothing here opens.
    readers: tuple[str, ...]
    #: How it comes back: `pull`, `build`, or `none`.
    route: str
    #: Why this removal needs `--force`. Empty when it does not.
    needs_force: tuple[str, ...] = ()
    #: Why this removal is refused whatever the flags say, or `None`.
    refused: str | None = None
    #: Present derived lanes built from this one: they keep working, their next rebuild will not.
    feeds: tuple[str, ...] = ()

    def blocked(self, force: bool) -> bool:
        return self.refused is not None or (bool(self.needs_force) and not force)


@dataclass
class DropPlan:
    drops: list[LaneDrop] = field(default_factory=list)
    #: Selected lanes with nothing on disk.
    absent: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(drop.size for drop in self.drops)


def path_bytes(path: Path) -> int:
    """Bytes on disk under `path` — every regular file, symlinks not followed, or the file itself."""
    if path.is_symlink():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            child = Path(root) / name
            if not child.is_symlink():
                total += child.stat().st_size
    return total


def _route(lane: Any) -> str:
    if lane.ensure is not None:
        return "pull"
    return "build" if lane.rebuild is not None else "none"


def _state(where: Path, present: Path | None) -> str | None:
    """`present`, `partial` (a directory holding something that is not a readable snapshot), or `None`."""
    if present is not None:
        return "present"
    if where.is_dir() and not where.is_symlink() and any(where.iterdir()):
        return "partial"
    return None


def inner_leftovers(where: Path) -> list[Path]:
    """`INNER_LEFTOVERS` under a lane's directory, outermost only (a `.part` inside `source/` goes with it)."""
    found: set[Path] = set()
    for pattern in INNER_LEFTOVERS:
        found.update(path for path in where.glob(pattern) if not path.is_symlink())
    return sorted(path for path in found if not any(other in path.parents for other in found))


def partial_lanes(settings: Settings) -> dict[str, Path]:
    """Every lane whose directory holds files and does not resolve as a snapshot."""
    present = lane_presence(settings)
    return {
        name: where for name, where in lane_directories(settings).items()
        if _state(where, present.get(name)) == "partial"
    }


def lane_directories(settings: Settings) -> dict[str, Path]:
    """Every lane's directory on this box: where it resolves, else where it would be provisioned."""
    present = lane_presence(settings)
    configured = lane_destinations(settings)
    out: dict[str, Path] = {}
    for name, lane in cache_lanes().items():
        where = present.get(name) or _lane_directory(lane, configured.get(name))
        if where is not None:
            out[name] = Path(where)
    return out


def _protected(settings: Settings, directories: dict[str, Path], own: str) -> list[tuple[str, Path]]:
    """Paths no removal may contain: the catalog, its storage and runs, and every *other* lane."""
    paths = [
        ("the catalog", settings.db_path),
        ("local artifact storage", settings.local_storage_dir),
        ("the maintenance runs", run_root(settings)),
    ]
    paths += [(f"lane {name}", where) for name, where in directories.items() if name != own]
    return [(label, Path(path).resolve()) for label, path in paths]


def refusal(path: Path, settings: Settings, directories: dict[str, Path], own: str) -> str | None:
    """Why removing `path` would take something else with it, or `None` when it would not."""
    if path.is_symlink():
        return f"{path} is a symlink; remove its target by hand if that is what you mean"
    resolved = path.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve() or len(resolved.parts) < 3:
        return f"{resolved} is too close to the filesystem root to be one lane's directory"
    for label, other in _protected(settings, directories, own):
        if other == resolved or resolved in other.parents:
            return f"{resolved} contains {label} ({other}); point the lane at a directory of its own"
    return None


def plan_drops(settings: Settings, names: list[str], *, leftovers: bool) -> DropPlan:
    """What removing `names` (and, with `leftovers`, every lane's leftovers) would delete.

    Reads only. `names` must be lane names `cache_lanes()` knows; the CLI checks before calling.
    """
    lanes = cache_lanes()
    present = lane_presence(settings)
    directories = lane_directories(settings)
    readers_of = lane_readers()
    plan = DropPlan()
    for name in names:
        lane = lanes[name]
        where = directories.get(name)
        state = None if where is None else _state(where, present.get(name))
        if where is None or state is None:
            plan.absent.append(name)
            continue
        readers = readers_of.get(name, ())
        route = _route(lane)
        force: list[str] = []
        if readers:
            if name in RESOLUTION_REFERENCES:
                consequence = "publishing an rsID-authored module refuses without it"
            elif PUBLISH in readers:
                consequence = "every enrichment (publish, /check, derived) runs without it"
            else:
                consequence = "those routes skip or refuse without it"
            force.append(f"read here {reader_tag(readers)}: {consequence}")
        if route != "pull" and state == "present":
            why = lane.unpublished if route == "build" else lane.unbuilt
            force.append(f"no published snapshot to pull back ({why or route})")
        feeds = tuple(
            other for other, other_lane in lanes.items()
            if name in other_lane.parents and present.get(other) is not None
        )
        plan.drops.append(LaneDrop(
            lane=name, path=where, state=state, size=path_bytes(where), readers=readers, route=route,
            needs_force=tuple(force), refused=refusal(where, settings, directories, name), feeds=feeds,
        ))
    if leftovers:
        planned = {drop.path for drop in plan.drops}
        for name, where in directories.items():
            found = [
                path for pattern in LEFTOVER_PATTERNS
                for path in sorted(where.parent.glob(pattern.format(name=where.name)))
            ]
            state = _state(where, present.get(name))
            if state == "present":
                found += inner_leftovers(where)
            elif state == "partial" and where not in planned:
                # Nothing reads it (it does not resolve), and provisioning refuses to write over it, so
                # it is in the way as well as on the disk. No `--force`: whatever reads the lane reads
                # a snapshot, which this is not.
                plan.drops.append(LaneDrop(
                    lane=name, path=where, state="partial", size=path_bytes(where), readers=(),
                    route=_route(lanes[name]), refused=refusal(where, settings, directories, name),
                ))
            for path in found:
                if path in planned:
                    continue
                plan.drops.append(LaneDrop(
                    lane=name, path=path, state="leftover", size=path_bytes(path),
                    readers=(), route=_route(lanes[name]),
                    refused=refusal(path, settings, directories, name),
                ))
    return plan


def drop(target: LaneDrop) -> int:
    """Remove one planned path, renaming it aside first so no resolver ever reads it half-deleted."""
    path = target.path
    if path.is_symlink():
        raise OSError(f"{path} is a symlink; refusing")
    # An interrupted removal's own leftover is already aside.
    aside = path if ".dropping-" in path.name else path.with_name(f".{path.name}.dropping-{os.getpid()}")
    if aside != path:
        path.rename(aside)
    if aside.is_dir():
        shutil.rmtree(aside)
    else:
        aside.unlink()
    return target.size
