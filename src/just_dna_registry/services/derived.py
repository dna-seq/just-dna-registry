"""The enriched `derived/` tree, handed back (0.25) — the one thing a cacheless client cannot make.

`resolution.csv` and the fact sidecars are produced by the network tier from snapshots that run to
artifacts running to tens of gigabytes. A module author on a laptop has none of them, and the
compiler never fetches — so `resolution.csv` has to *travel with* a spec for it to compile anywhere
else. This service already builds that tree on every publish and on every `/check`, and then throws
it away. Returning it is the smallest possible version of the whole caching-proxy idea.

**It runs what a publish runs, not what `/check` runs.** `_dry_run_inner` also executes the opt-in
check passes — frequencies, literature, identifiers, ACMG, PGx — which are egress spent producing a
*verdict*, and a caller asking for the tree did not ask for one. The sequence here is
`normalize_spec` then `enrich_spec`, which is `publish_version`'s own order, so what comes back is
what would have gone into the catalog rather than a parallel derivation of it.

**The tree is flat on disk and the split is constructed on the way out.** `normalize_spec_layout`
applies the renames and then removes the directories it emptied, so `derived/` does not exist at the
moment enrichment finishes — `resolution.csv` and the sidecars are at the spec root. The folder in
the archive is a layout for readers, exactly as it is for `download(layout="split")`, and it is safe
to put them there for the same reason: `SIGNATURE_INPUTS` is entirely root-level, so nothing that can
live in `derived/` can move a module's content identity.
"""

import hashlib
import io
import json
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from just_dna_registry.config import Settings
from just_dna_registry.models.api import ValidationReport
from just_dna_registry.services.enrich import EnrichOutcome, enrich_spec, validation_report
from just_dna_registry.services.publish import PublishError, normalize_spec
from just_dna_registry.specfiles import (
    DERIVED_DIR,
    DERIVED_FILES,
    DERIVED_NOTE_FILE,
    DERIVED_REPORT_FILE,
)

_COLLISION_NOTE = f"""# The derived tables for this spec

Produced by `POST /api/v1/modules/{{ns}}/{{name}}/derived` on a registry that holds the snapshot
caches, so that a client without them can still compile this module. The compiler never fetches:
`{DERIVED_DIR}/resolution.csv` is what places rsID-authored rows onto coordinates, and it has to
travel with the spec for the module to compile anywhere else.

`{DERIVED_REPORT_FILE}` carries the validation report for the spec that was uploaded, and a `files` list with
a SHA-256 and a size for every member here. Those digests let you check what arrived; they are not an
attestation, because there is no manifest before a compile. The attestation is the publish's — to
hold this service to "these are the bytes it would have compiled", publish and compare
`artifact.digest`.

## Two things to watch when you merge this back

**The licence ledger arrives under its preferred spelling.** `{DERIVED_DIR}/licensing.csv` is
genuinely both provenances: your authored rows with the enricher's merged into them. It is always
named `licensing.csv` here — `sources.csv` is the deprecated spelling of the same table and is never
emitted — so **if your spec directory still carries a `sources.csv`, delete it and keep this file**.
Leaving both is two spellings of one fact table, and the next upload is a `422 ambiguous_spec_layout`
rather than a publish: `just_dna_format.layout.resolve_sidecar` raises on two copies rather than
preferring one.

**Resolve the name rather than string-matching it**, or a tool that looks for whichever spelling your
spec happens to use will report no change while a file lands under the other one. Portable today:
`layout.SIDECAR_SPELLINGS` maps each table *key* to every spelling of it, and `layout.DEPRECATED_SPELLINGS`
says which are on the way out — both have been there since 0.6. `layout.sidecar_key()` does that lookup
in one call and is the thing to use once your floor is **format 0.7.0**; it does not exist before that,
so a consumer on 0.6.x wants the two constants.

**A table missing from this archive is not the same as a table with nothing in it.**
`{DERIVED_REPORT_FILE}`'s `files_absent` lists every derived name this run did not produce, and
`enrichment.notes` carries the reason wherever the pass recorded one. Some skips leave no note at
all — a gated source whose credential this deployment does not hold writes nothing and says nothing —
so treat an entry in `files_absent` as *"not produced here"*, never as *"this module has none"*.
Which of the two it is may be a question about the server rather than about your module; `GET /caches`
answers the snapshot half.
"""


@dataclass
class DerivedArchive:
    """The tree, the report that describes it, and the digests that let a caller check the bytes."""

    archive: bytes
    filename: str
    validation: ValidationReport
    enrichment: EnrichOutcome
    #: `{name, sha256, size}` per member, in the `sha256:` lowercase-hex convention the manifest uses.
    files: list[dict[str, Any]] = field(default_factory=list)


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def build_derived_tree(
    *,
    settings: Settings,
    repo: Any,
    uploads: dict[str, bytes],
    namespace: str,
    name: str,
    client_format: str | None = None,
    gate: Any = None,
) -> DerivedArchive:
    """Normalize, validate, enrich, and hand the derived tables back as a `.tar.gz`.

    Synchronous and blocking; the router hands it to a threadpool worker. It releases `gate` in its
    own `finally` rather than letting the coroutine do it, because a run that exceeds the request
    timeout keeps its worker: `asyncio.wait_for` cancels the await, not the thread. Releasing on the
    caller's side would let a runaway run stop counting against occupancy while it is still spending.

    **A broken spec is a `422` here, and that is not a contradiction of the dry-run rule.**
    `/validate` and `/check` answer `200` with `valid: false` because their whole contract is to
    report a finding. This route's contract is to *produce*, and a spec that cannot be enriched
    produces nothing — so it fails the way a publish fails, carrying the same `ValidationResult`
    errors a publish would have carried.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "spec"
            for rel, data in uploads.items():
                dest = spec_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)

            # Layout and `module:` block first, in the publish's own order — a tree derived against a
            # spec laid out differently from the one that would be published is a tree that predicts
            # nothing.
            normalization = normalize_spec(spec_dir)

            # Modeless, exactly as `publish_version`'s first pass is: this exists to reject a broken
            # spec before spending enrichment on it, and every strict-only finding is a per-row
            # judgement the enrichment tier is about to make anyway.
            validation = validation_report(
                spec_dir, repo, namespace, name, strict=False,
                normalized=normalization.info,
                extra_warnings=normalization.warnings,
                client_format=client_format,
            )
            if not validation.valid:
                raise PublishError(
                    "invalid_spec",
                    errors=validation.errors,
                    warnings=validation.warnings,
                    info=validation.info,
                )

            enrichment = enrich_spec(spec_dir, settings)
            return _pack(spec_dir, namespace, name, validation, enrichment)
    finally:
        if gate is not None:
            gate.release()


def _pack(
    spec_dir: Path,
    namespace: str,
    name: str,
    validation: ValidationReport,
    enrichment: EnrichOutcome,
) -> DerivedArchive:
    """Gather whatever `DERIVED_FILES` the run actually produced and tar them under `DERIVED_DIR`.

    **The folder is a consequence of the contents, never a promise made ahead of them.** A module
    that authors its own coordinates and needs no sidecars gets an archive with a report and a note
    and no `derived/` at all, which is the honest answer — the same rule `download(layout="split")`
    follows, where the folder appears only when something lands in it.
    """
    members: list[tuple[str, bytes]] = []
    for filename in DERIVED_FILES:
        source = spec_dir / filename
        if source.is_file():
            members.append((f"{DERIVED_DIR}/{filename}", source.read_bytes()))

    listing = [
        {"name": arcname, "sha256": _digest(data), "size": len(data)}
        for arcname, data in members
    ]
    # **Absence is a fact, so it is enumerated rather than left to be noticed.** A derived table this
    # run did not produce has two opposite histories — the module has nothing to say on that axis, or
    # the pass behind it could not run — and from outside the archive they are indistinguishable:
    # there is simply no member. `just-module-creator` met the second one and asked for this, and
    # they are right that it is the same rule this tier already applies to every empty collection.
    #
    # It does not claim to know *which* history: that is what `enrichment.notes` is for, where a pass
    # that skipped records its own reason. Some skips are invisible even there — a gated source whose
    # credential this deployment lacks (Atlas, for `expression_effects.csv`) writes nothing and says
    # nothing — so the honest report is "expected, not produced", beside whatever the run did say.
    produced = {arcname.split("/", 1)[-1] for arcname, _ in members}
    absent = [name for name in DERIVED_FILES if name not in produced]
    report = {
        "namespace": namespace,
        "name": name,
        "validation": validation.model_dump(mode="json"),
        "enrichment": {
            "ran": enrichment.ran,
            "offline": enrichment.offline,
            "skipped_reason": enrichment.skipped_reason,
            "fully_resolved": enrichment.fully_resolved,
            "unresolved": enrichment.unresolved,
            "notes": enrichment.notes,
        },
        "files": listing,
        "files_absent": absent,
    }
    extras = [
        (DERIVED_REPORT_FILE, json.dumps(report, indent=2, sort_keys=True).encode()),
        (DERIVED_NOTE_FILE, _COLLISION_NOTE.format(ns=namespace, name=name).encode()),
    ]

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for arcname, data in members + extras:
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            # A fixed mtime, so two runs over byte-identical inputs produce byte-identical archives.
            # The digests inside describe the members rather than the container, but a container that
            # changes every second is one nobody can cache or compare.
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return DerivedArchive(
        archive=buf.getvalue(),
        filename=f"{name}-derived.tar.gz",
        validation=validation,
        enrichment=enrichment,
        files=listing,
    )
