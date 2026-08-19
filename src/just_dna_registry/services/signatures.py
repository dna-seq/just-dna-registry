"""
One-time re-derivation of every version's content signature (0.11).

Through 0.10 the registry computed its own name-independent identity: a Merkle root over the
manifest's `inputs[]` file hashes, minus `module_spec.yaml`. Format 0.5 promoted that idea into the
compiler as `content_signature(spec_dir)`, and the two are not the same value. The compiler's reads
the authored rows *as parsed* — normalized, with `module_spec.yaml`'s `defaults:` folded into each
row and the declared genome build mixed in — so it survives a reformat, a row reorder, and a
recompile against a different reference, where a raw-byte hash does not.

Adopting it means every stored `content_hash` is stale, and they cannot be recomputed from the
manifest: the new algorithm needs the CSVs, which live in storage. Hence an ops command
(`registry rederive-signatures`) rather than a schema migration —

1. `init_db(conn)` holds a connection and nothing else. Threading a `StorageBackend` into it would
   make `registry init-db` do HuggingFace I/O, and make the first request after a deploy wait on it.
2. Re-derivation can fail per row: a legacy CSV that 0.5's models reject raises `ValueError`. A
   migration has nowhere to report a partial result; a command has a dry run and an exit code.
3. It changes the value the dedup gate keys on. That deserves a human in a maintenance window, not a
   side effect of starting the server.

Two findings the report must not bury, because they are behaviour changes rather than noise:

* **split** (RM37) — one old hash resolving into several new ones. Two modules differing only in
  `defaults.curator` currently hash *equal*, so a genuinely distinct module may have been rejected
  as a duplicate. Re-derivation separates them, and whatever was refused becomes publishable.
* **merge** — several old hashes collapsing into one, under different `(namespace, name)`. That is
  two already-published modules that the gate will now consider duplicates of each other, so the
  next version of one of them gets a 409. Never applied without an explicit `--allow-merges`.
"""

import logging
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from just_dna_compiler.compiler import content_signature
from just_dna_format.manifest import ModuleManifest

from just_dna_registry.db.repository import Repository
from just_dna_registry.services.publish import normalize_module_block
from just_dna_registry.specfiles import SIGNATURE_INPUTS, SPEC_YAML
from just_dna_registry.storage.base import StorageBackend, version_key

logger = logging.getLogger("registry.signatures")


@dataclass(frozen=True)
class SignatureChange:
    """One version's before/after, and why it moved."""

    version_id: int
    namespace: str
    name: str
    version: str
    old: str
    new: str | None
    genome_build: str
    error: str | None = None

    @property
    def module(self) -> str:
        return f"{self.namespace}/{self.name}@{self.version}"

    @property
    def bucket(self) -> str:
        """How to read this row.

        `moved_build` is called out separately from `moved` because it is an *expected* consequence
        of RM36 (the declared build is now part of the content — identical rows on two assemblies are
        two different loci) rather than something to investigate.
        """
        if self.error is not None or self.new is None:
            return "skipped"
        if self.new == self.old:
            return "unchanged"
        if not self.old:
            return "derived"  # never had one (pre-0.5 manifest); not a move
        if self.genome_build != "GRCh38":
            return "moved_build"
        return "moved"


def rederive_version_signature(
    storage: StorageBackend, namespace: str, name: str, version: str
) -> tuple[str | None, str | None]:
    """Recompute one version's signature from its stored spec. Returns `(signature, error)`.

    Reads what storage actually holds rather than what `manifest.inputs` lists: the two disagree for
    a legacy import that shipped no inputs, and the manifest is the wrong authority for "what can I
    still fetch".

    Normalizes the module block first, and that is required rather than tidy —
    `content_signature(spec_dir)` loads the YAML with no authority keys of its own, so a stored spec
    still carrying `namespace:` fails the load, silently falls back to the default genome build, and
    yields the wrong signature for a non-GRCh38 module.
    """
    key = version_key(namespace, name, version)
    present = [n for n in SIGNATURE_INPUTS if storage.exists(key, n)]
    if SPEC_YAML not in present:
        return None, "no module_spec.yaml in storage (legacy parquet-only import)"

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp)
        for iname in present:
            (spec / iname).write_bytes(storage.read_file(key, iname))
        normalize_module_block(spec)
        try:
            return content_signature(spec), None
        except ValueError as exc:
            # A CSV the 0.5 models reject. Reported per row rather than aborting the sweep — this is
            # exactly the case a schema migration could not have handled.
            return None, str(exc)


def plan_rederivation(
    repo: Repository, storage: StorageBackend, *, namespace: str | None = None
) -> list[SignatureChange]:
    """Recompute every version's signature (optionally within one namespace). Writes nothing."""
    changes: list[SignatureChange] = []
    for row in repo.all_versions_for_signature(namespace):
        manifest = ModuleManifest.model_validate_json(row["manifest_json"])
        signature, error = rederive_version_signature(
            storage, row["namespace"], row["name"], row["version"]
        )
        changes.append(
            SignatureChange(
                version_id=row["id"],
                namespace=row["namespace"],
                name=row["name"],
                version=row["version"],
                old=row["content_hash"] or "",
                new=signature,
                genome_build=manifest.genome_build,
                error=error,
            )
        )
    return changes


def collision_report(
    changes: list[SignatureChange],
) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    """`(splits, merges)` — the two ways re-derivation changes who collides with whom.

    A split lists an old hash and the modules that no longer share one. A merge lists a new hash and
    the distinct modules that now do. Both are keyed on `(namespace, name)`, not on version: two
    versions of the *same* module sharing a signature is normal and allowed.
    """
    by_old: dict[str, set[str]] = defaultdict(set)
    by_new: dict[str, set[str]] = defaultdict(set)
    for change in changes:
        if change.new is None:
            continue
        module = f"{change.namespace}/{change.name}"
        if change.old:
            by_old[change.old].add(module)
        by_new[change.new].add(module)

    # A split is one old hash whose modules land on more than one new hash.
    new_by_module: dict[str, set[str]] = defaultdict(set)
    for change in changes:
        if change.new is not None:
            new_by_module[f"{change.namespace}/{change.name}"].add(change.new)

    splits = [
        (old, sorted(modules))
        for old, modules in sorted(by_old.items())
        if len({n for m in modules for n in new_by_module[m]}) > 1
    ]
    merges = [
        (new, sorted(modules)) for new, modules in sorted(by_new.items()) if len(modules) > 1
    ]
    return splits, merges


def apply_rederivation(repo: Repository, changes: list[SignatureChange]) -> int:
    """Write the recomputed signatures. Returns how many rows changed."""
    written = 0
    for change in changes:
        if change.new is None or change.new == change.old:
            continue
        repo.set_version_content_hash(change.version_id, change.new)
        written += 1
    repo.conn.commit()
    return written
