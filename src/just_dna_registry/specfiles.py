"""
The set of files that make up an authored module spec, in one place, plus the one normalization
that decides *where* those files may arrive from (`plan_layout`).

Three services need to know "which files belong to a spec": publish (what to accept and carry into
storage), revalidate (what to materialize back out of storage before re-checking), and upgrade (what
to carry forward into the re-published version). Until 0.11 each of them hardcoded its own
`("module_spec.yaml", "variants.csv", "studies.csv")` triple, which was the complete list in format
0.3 and has been wrong since: it rejects a PGx-only module (correct and complete in 0.5 — one CSV,
one concern, and never an empty `variants.csv` to keep another table company) and it silently drops
every 0.5 sidecar on upgrade.

The names mirror `just_dna_compiler.compiler`'s own private `_TABLE_KINDS` / `_FACT_TABLES` /
`_INPUT_FILES`. They are private upstream, so this module cannot import them without reaching into
another package's internals — instead `tests/test_specfiles.py` imports them and asserts parity, so
a table kind added in a future format release fails CI here rather than being silently rejected at
publish time.

**One part of that is no longer mirrored, and that is the improvement 0.6 brought.** Where a
*sidecar* may live and what it may be called is now `just_dna_format.layout`, a module in the
dependency-light tier written for exactly the four parties that have to agree — the compiler reads,
the enricher writes, a publisher uploads, this registry re-splits. Every disagreement between them so
far has been silent, and 0.16.2 was one: `licensing.csv` reached storage and never reached the
compile. So the spellings, the `derived/` name and the deprecation set are **imported** below rather
than restated, and the rename map is *derived* from them. When 1.0 removes `sources.csv`, nothing
here needs editing.

Deliberately *not* a validation rule: composition is the compiler's judgement, not the registry's.
`REQUIRED_SPEC_FILES` is only `module_spec.yaml`, and everything past that
(`"module has no recognized table"`, `"studies.csv is missing"` when `variants.csv` is present) comes
back from `validate_spec` as a proper finding with the compiler's own wording.
"""

from pathlib import PurePosixPath
from typing import Iterable

from just_dna_format.layout import (
    DERIVED_SUBDIR,
    LICENSING_CSV,
    SIDECAR_SPELLINGS,
    SOURCES_CSV,
    VERIFICATION_JSON,
    is_deprecated_spelling,
    preferred_spelling,
    sidecar_spellings,
)
from pydantic import BaseModel, Field

SPEC_YAML: str = "module_spec.yaml"

# The SNP core. `studies.csv` is required if and only if `variants.csv` is present — a rule the
# compiler owns and enforces, not this module.
CORE_CSVS: tuple[str, ...] = ("variants.csv", "studies.csv")

# Optional table kinds a composed module adds, one parquet each. Mirrors `compiler._TABLE_KIND_CSVS`
# in the same order.
TABLE_KIND_CSVS: tuple[str, ...] = (
    "activity_phenotype.csv",
    "copynumbers.csv",
    "repeat_alleles.csv",
    "heteroplasmy.csv",
    "haplotypes.csv",
    "allele_function.csv",
    "diplotypes.csv",
    "pgs.csv",
    "pharm_variants.csv",
)

#: The licensing/attribution ledger: one row per `(source, layer)`, saying where the bytes came from
#: and on what terms. `SOURCES_CSV` and `LICENSING_CSV` are **one table with two spellings**, and
#: both names — plus which of them is deprecated — are imported from `just_dna_format.layout` rather
#: than restated here. That import is the whole lesson of 0.16.2: while these lists were hand-kept,
#: the two halves of the ecosystem disagreed about the filename and the disagreement was silent.
#:
#: The direction of travel reversed at 0.6. Under 0.5 this registry was the half that lagged — the
#: compiler read `sources.csv` and nothing else, so the ledger every current authoring tool writes
#: was dropped from the compile and the card advertised the enricher's own permissive Ensembl row for
#: a module whose upstreams forbid sale. Under 0.6 the compiler reads both, prefers `licensing.csv`,
#: and warns on the old spelling for removal at 1.0. So the rename in `RENAMED_ON_UPLOAD` now points
#: the other way, and it is derived from `SIDECAR_SPELLINGS` instead of written down: at 1.0, when
#: `sources.csv` stops being read at all, an author who still sends one keeps publishing and nothing
#: in this file has to be edited to make that true.

# The derived-fact sidecars, produced by `just-dna-enricher`. Mirrors `compiler._FACT_TABLES` — under
# the *canonical* spelling, which is what that constant names; the accepted spellings of each are
# `sidecar_spellings()` and are folded into `RECOGNIZED_SPEC_FILES` below.
#
# They compile to parquet (so they are part of `artifact.digest` for a module that carries them) but
# are hashed by *facts* rather than raw bytes, because they are multi-producer: the enricher, a
# human, and `reverse_module` all legitimately emit different bytes for the same content.
#
# The last three are 0.6's: `gene_validity.csv` (ClinGen/GenCC gene–disease validity, RM24),
# `clinical_assertions.csv` (ClinVar clinical assertions, RM25) and `gwas_effects.csv` (GWAS Catalog
# effect sizes, RM90). Adding them here is not cosmetic — this tuple is what `revalidate` and
# `upgrade` rebuild a spec directory from, so a fact table missing from it is a fact table silently
# dropped the first time a module is re-published. That is precisely how `licensing.csv` was lost.
FACT_CSVS: tuple[str, ...] = (
    "frequencies.csv",
    "gene_metrics.csv",
    "literature.csv",
    SOURCES_CSV,
    "gene_validity.csv",
    "clinical_assertions.csv",
    "gwas_effects.csv",
)

# The rsid↔coordinate table. Produced by the enricher (the only tier permitted to fetch) and
# consumed by the compiler, which never fetches. Not an input-hash member and not an output parquet
# — its identity is `manifest.compilation.resolution_signature`.
RESOLUTION_CSV: str = "resolution.csv"

# Optional structured provenance authored beside the spec. Shipped and hashed like a log, kept out
# of `artifact.digest`.
PROVENANCE_FILE: str = "provenance.json"

#: The enricher's attestation of what it checked: per check, the subjects and findings, or the reason
#: a check did not run — the distinction between "ran and found nothing" and "never ran" that this
#: whole tier is organised around. Recognized so a `revalidate` or an `upgrade` carries it forward
#: instead of dropping it, which is exactly the `README.md` failure of 0.14 at a different file
#: (S11, filed by `just-dna-format` against their own unreleased 0.6).
#:
#: **Recognized is not read as ours.** 0.16 recognized this file so a rebuild would carry it forward;
#: 0.6 lets the manifest attest it (`manifest.verification`), and 0.17 surfaces it — as the
#: *publisher's* claim, never as a registry verdict. This server compiles the spec itself, which is
#: what makes `compile_success` and the digest ours; this file is the author's word about what their
#: enricher saw against live sources at authoring time, which we cannot reproduce offline. Every
#: field upstream puts in that block is marked untrusted for the same reason, and **absent reads as
#: *nothing was said*, never as *passed***.
#:
#: Out of `SIGNATURE_INPUTS` (it is derived, not authored). **In** `DERIVED_FILES` since 0.17: the
#: manifest now records it under `derived`, so a downloader does receive it and the split tree has
#: somewhere to put it.
VERIFICATION_FILE: str = VERIFICATION_JSON

#: The module's prose, projected onto the catalog card at publish (S5). `README.md` and not
#: `MODULE.md`: it is what an author writes without being told to, it is what the ecosystem's other
#: registries read, and it is what the reporting consumer tried first. A comment in `upgrade.py`
#: advertised `MODULE.md` for two releases, but nothing ever read either — the name was free to pick.
#:
#: Recognized here rather than left to the publish paths' incidental behaviour: both of them copy
#: every non-parquet file out of the spec directory, so the *bytes* survived either way, but nothing
#: read them. Being on this list is what makes a readme reach the card, and it is also what makes
#: `upgrade` carry it forward and `revalidate` materialize it back out of storage — both of which
#: rebuild a spec dir from `RECOGNIZED_SPEC_FILES` and would otherwise drop it.
#:
#: (The 0.14 note here and in the changelog said `/versions/import` filters an archive through
#: `is_spec_file` and so lost readmes that the loose upload kept. It does not: `import_archive` sets
#: `spec_dir` to the extracted root unfiltered. The filter is on the *dry-run* pair, which is a real
#: asymmetry of its own and is why `carries_spec_content` exists below.)
#:
#: **Out of `artifact.digest` and out of `SIGNATURE_INPUTS`, deliberately.** Prose must not change a
#: module's identity on either axis: editing a caveat would otherwise mint a new digest and collide with
#: the `409 duplicate_content` claim of the module it is a copy of.
README_FILE: str = "README.md"

#: The name the readme arrived under before 0.14 picked one, and still the name the upstream
#: authoring agent writes — `write_module_md` in `just-dna-pipelines`' `agents/module_creator.py`.
#: (0.14 credited that tool to the `just-module-creator` plugin, which has never had it; two things
#: called some form of "module creator" is the whole of the mix-up, and the address matters because
#: emitting `README.md` at the source is a change to *pipelines* — S8.) Renamed on upload rather
#: than merely tolerated: the corpus was authored against advice this project gave and then changed,
#: so refusing it — or silently dropping the prose, which is what happened until now — would charge
#: the author for our rename.
LEGACY_README_FILE: str = "MODULE.md"

#: Spellings that are obviously *meant* as the readme but are not one of the two names above, so the
#: card would silently stay empty. Warned about, never renamed (S7): `MODULE.md` is renamed because
#: this project told authors to write it, which makes the rename a repair of our own advice —
#: guessing at `readme.md` or `README.txt` would be inventing intent, and a rename this module does
#: not have to keep is a rename it should not make. A warning costs nothing and refuses nothing.
_README_LOOKALIKES: frozenset[str] = frozenset(
    {"readme", "readme.md", "readme.txt", "readme.rst", "readme.markdown", "module.markdown"}
)

#: Where machine-written tables may sit in an *uploaded* or *downloaded* tree. A convention of this
#: registry's, not of the format: the compiler reads every authored and derived table from one flat
#: directory, so this is normalized away (`plan_layout`) before anything hashes anything, and applied
#: again only on the way out (`RegistryClient.download(layout="split")`).
#:
#: It exists because a spec directory mixes two provenances with no marking. `variants.csv` and
#: `studies.csv` are the author's; `resolution.csv` and the fact sidecars are the enricher's, and
#: `sources.csv` is both — the author's rows with the enricher's merged in. An author reading the
#: flat listing cannot tell which files are theirs to edit.
#:
#: **Safe by construction, and this is the reason to prefer a folder over any in-file marker:**
#: `SIGNATURE_INPUTS` is entirely root-level, so nothing that may move into this folder can move
#: `content_signature`, and `artifact.digest` is over parquets the server builds itself.
#:
#: The name is imported rather than chosen since 0.17. This registry invented the convention and
#: upstream adopted it as RM49, which makes it *their* constant now — and a second definition of a
#: name two packages must agree on is the exact failure `just_dna_format.layout` exists to end.
#: Their `sidecar_candidates` accepts a sidecar at the root **or** under this folder, so flattening
#: is no longer strictly required for the fact tables; it is still done, because the authored tables
#: are root-only and one normalized layout is easier to reason about than two.
DERIVED_DIR: str = DERIVED_SUBDIR

#: Where logs arrive, and the one subtree `plan_layout` must never touch: the compiler discovers
#: `logs/**.log` and the manifest records that path verbatim, so flattening one would rename a file
#: the manifest attests. A top-level `*.log` is equally discovered and equally left alone.
LOGS_DIR: str = "logs"

SPEC_DATA_FILES: tuple[str, ...] = CORE_CSVS + TABLE_KIND_CSVS + FACT_CSVS + (RESOLUTION_CSV,)

#: Every accepted *spelling* of every spec data file. For most names that is the name itself;
#: `sidecar_spellings` is what makes the ledger's two names one entry rather than a special case.
_SPEC_DATA_SPELLINGS: tuple[str, ...] = tuple(
    dict.fromkeys(
        spelling for name in SPEC_DATA_FILES for spelling in sidecar_spellings(name)
    )
)

#: Everything a spec directory may legitimately contain, for storage round-trips.
#:
#: Spellings, not canonical names: a file is stored under the name it was normalized to, and
#: `revalidate`/`upgrade` rebuild a spec directory from this tuple. A name missing here is a file
#: dropped on the next rebuild, which is what happened to `licensing.csv` before 0.16.2 and to the
#: readme before 0.14.
RECOGNIZED_SPEC_FILES: tuple[str, ...] = (
    SPEC_YAML, PROVENANCE_FILE, README_FILE, VERIFICATION_FILE
) + _SPEC_DATA_SPELLINGS

#: The registry's own precondition before it hands a spec to the compiler. Just the manifest of
#: intent — everything else is the compiler's call.
REQUIRED_SPEC_FILES: tuple[str, ...] = (SPEC_YAML,)

#: The machine-written tables: what `DERIVED_DIR` holds on the way in and on the way out. Everything
#: here is produced (or merged) by `just-dna-enricher` and hashed by *facts* rather than raw bytes —
#: which is the same property that keeps them out of `SIGNATURE_INPUTS`.
#:
#: Under the **preferred** spelling, because this is an emit list: it is what
#: `download(layout="split")` puts in `derived/`, and a tree we write should carry the name a fresh
#: file is created under rather than one queued for removal. `verification.json` joins it at 0.17,
#: now that `manifest.derived` attests the file and a downloader therefore receives it.
DERIVED_FILES: tuple[str, ...] = tuple(
    preferred_spelling(name) for name in FACT_CSVS
) + (RESOLUTION_CSV, VERIFICATION_FILE)

#: Names that arrive under one spelling and are stored under another, because the author wrote a name
#: that is not the one this registry's storage should hold. Two entries, and they are the same repair
#: pointing in opposite directions — which is the point worth keeping.
#:
#: `MODULE.md` → `README.md`: the corpus lags *us*. This project advised `MODULE.md` for two releases
#: and `just-dna-pipelines` still writes it, so refusing it — or silently dropping the prose, which is
#: what happened until 0.14 — would charge the author for our rename.
#:
#: `sources.csv` → `licensing.csv`: **we** lag the corpus no longer, and at 0.6 the lag inverted. The
#: 0.16.2 entry pointed the other way, renaming the new name onto the old one because this deployment's
#: compiler could only read the old one; a 0.6 compiler reads both, prefers the new one, and warns that
#: the old is removed at 1.0. Left alone, every publish of a legacy spec would carry that deprecation
#: warning into `manifest.compilation.warnings` forever, and at 1.0 the file would stop being read at
#: all. Renaming forward is what keeps a module authored in 2025 publishable in 1.0 without its author
#: editing anything.
#:
#: **Derived from `SIDECAR_SPELLINGS`, never written down.** Upstream owns which spellings exist and
#: which are deprecated; restating that here is how the two got out of step in the first place. A
#: sidecar renamed in some future release is picked up by this comprehension in the release that
#: bumps the floor.
#:
#: A rename is only ever *onto* a name in `RECOGNIZED_SPEC_FILES` — that is what makes the renamed
#: file survive the storage round-trip `revalidate` and `upgrade` rebuild a spec from — and a test
#: asserts it over the whole map, along with the disjointness from `SIGNATURE_INPUTS` that keeps any
#: spelling from moving a `content_signature` or its global `409 duplicate_content` claim.
RENAMED_ON_UPLOAD: dict[str, str] = {
    LEGACY_README_FILE: README_FILE,
    **{
        spelling: preferred_spelling(canonical)
        for canonical, spellings in SIDECAR_SPELLINGS.items()
        for spelling in spellings
        if is_deprecated_spelling(spelling)
    },
}

#: Names `plan_layout` will lift out of a subdirectory. The recognized spec files, plus the names
#: that are also *renamed* rather than only moved.
_HOISTABLE: frozenset[str] = frozenset(RECOGNIZED_SPEC_FILES) | set(RENAMED_ON_UPLOAD)

#: Exactly what `just_dna_compiler.compiler.content_signature` reads. Mirrors `_INPUT_FILES`: the
#: fact sidecars and `resolution.csv` are excluded because they are derived, not authored, so two
#: modules with identical authored data share a signature regardless of which sidecars were run.
SIGNATURE_INPUTS: tuple[str, ...] = (SPEC_YAML,) + CORE_CSVS + TABLE_KIND_CSVS


def is_spec_file(name: str) -> bool:
    """Whether `name` is a file the registry recognizes as part of an authored spec."""
    return name in RECOGNIZED_SPEC_FILES


def carries_spec_content(name: str) -> bool:
    """Whether `name` should reach `plan_layout` at all — the archive filter for the dry runs.

    Wider than `is_spec_file` in two directions, and both are load-bearing. A **subfoldered** spec
    file has to survive the filter or the normalization never sees it, and a dry run that drops what
    the publish keeps is not a rehearsal. Every key of `RENAMED_ON_UPLOAD` has to survive it for the
    same reason: none of them is a recognized spec file — each is renamed into one.
    """
    if name == LOGS_DIR or name.startswith(f"{LOGS_DIR}/"):
        return True
    return PurePosixPath(name).name in _HOISTABLE


def has_spec_data(names: "set[str] | frozenset[str]") -> bool:
    """Whether `names` carries at least one authored data table.

    The presence gate for revalidate/upgrade: a spec dir holding only `module_spec.yaml` has nothing
    to re-check, but a PGx-only module holding `haplotypes.csv` and no `variants.csv` has plenty.
    """
    return any(name in names for name in SPEC_DATA_FILES)


class LayoutPlan(BaseModel):
    """What normalizing an uploaded tree would do, computed from names alone.

    Split into three lists on purpose. `notes` are accepted-and-noteworthy (`ValidationResult.info`
    grade — the server changed the spec and the author should know what); `warnings` are things the
    author probably did not mean but which cost nothing; `conflicts` are refusals, returned rather
    than raised so this module stays free of the publish layer it would otherwise have to import.
    """

    renames: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.renames)


def plan_layout(names: Iterable[str]) -> LayoutPlan:
    """Plan the flattening of an uploaded spec tree onto the flat layout the compiler reads.

    Liberal in, strict out. A recognized spec file is lifted to the root **from any subdirectory**,
    not only from `DERIVED_DIR`: producers already ship `metadata/`, `enriched/` and `authored/`
    trees, and accepting whichever one arrived costs nothing, while blessing a second name in this
    module would make it a name we then have to keep. `LOGS_DIR` is the one exception and is never
    touched — the manifest attests those paths verbatim.

    `RENAMED_ON_UPLOAD` is applied as part of the same pass, since "this file arrived under a name
    the compiler does not read" is the same question asked about a filename rather than a directory.

    Unrecognized files stay exactly where they are, whatever depth they sit at. The compiler tolerates
    unknown files as a contract, and a rule invented here for them would quietly break it.

    Two paths claiming one root name is a `conflict`, never a guess: `resolution.csv` beside
    `derived/resolution.csv` is a question only the author can answer, and picking one silently is
    how the wrong table gets published under a signature that looks perfectly valid.
    """
    present = sorted(set(names))
    basenames = {PurePosixPath(name).name for name in present}
    plan = LayoutPlan()
    claims: dict[str, list[str]] = {}

    for name in present:
        if name == f"{LOGS_DIR}" or name.startswith(f"{LOGS_DIR}/"):
            continue
        base = PurePosixPath(name).name
        if base not in _HOISTABLE:
            continue
        renamed_to = RENAMED_ON_UPLOAD.get(base)
        if renamed_to is not None:
            if renamed_to in basenames:
                # Both spellings arrived, and the two cases diverge at 0.6 — which is why this is no
                # longer one branch. Never a merge and never newest-wins in either.
                if is_deprecated_spelling(base):
                    # A sidecar. `layout.resolve_sidecar` **raises** `SidecarCollision` on two copies
                    # of one table, so carrying the loser through as an extra file no longer produces
                    # a publish with a warning — it produces a `ValueError` out of the compiler with
                    # our own upload as its cause. Refused here instead, where the message can name
                    # both paths and the author can act on it. Upstream's reasoning is the reason to
                    # agree rather than to work around it: these tables are fact-hashed and
                    # hand-editable, so two copies are two claims and preferring either discards
                    # somebody's curation silently.
                    plan.conflicts.append(
                        f"`{name}` and `{renamed_to}` are the same table under both of its "
                        f"spellings; keep one and drop the other. `{renamed_to}` is the spelling to "
                        f"keep — `{name}` is deprecated and is removed at format 1.0"
                    )
                    continue
                # The readme. Still a warning: overwriting prose the author wrote with prose they
                # did not is the single most surprising thing this pass could do, and unlike a
                # sidecar an extra markdown file makes the compiler do nothing at all.
                plan.warnings.append(
                    f"`{name}` ignored: `{renamed_to}` is also present and is the name the "
                    f"registry reads. The file is carried unchanged."
                )
                continue
            claims.setdefault(renamed_to, []).append(name)
            continue
        claims.setdefault(base, []).append(name)

    # A file that is plainly meant as the readme under a name nothing reads (S7). Warned rather than
    # renamed or refused: the reporting consumer's point was that the current failure is silent in
    # both directions, and silence is the part worth fixing. Skipped entirely once a real `README.md`
    # is present, since then nothing was lost and the extra file is just an extra file.
    if README_FILE not in basenames:
        for name in present:
            base = PurePosixPath(name).name
            if base.lower() in _README_LOOKALIKES and base not in (README_FILE, LEGACY_README_FILE):
                plan.warnings.append(
                    f"`{name}` looks like a readme but the registry reads `{README_FILE}` "
                    f"(exact name), so the module card's `readme` will stay empty. Rename it, or "
                    f"set it after publishing with `amend_readme`. The file is carried unchanged."
                )

    for dest, sources in sorted(claims.items()):
        if len(sources) > 1:
            plan.conflicts.append(
                f"`{dest}` arrives from more than one path ({', '.join(f'`{s}`' for s in sources)}); "
                f"send one copy, since only the author knows which is current"
            )
            continue
        source = sources[0]
        if source == dest:
            continue
        plan.renames[source] = dest
        base = PurePosixPath(source).name
        if base == LEGACY_README_FILE:
            plan.notes.append(
                f"renamed `{source}` to `{README_FILE}` (the readme filename the registry reads; "
                f"`{LEGACY_README_FILE}` was this project's advice until 0.14 and nothing read it)"
            )
        elif is_deprecated_spelling(base):
            plan.notes.append(
                f"renamed `{source}` to `{dest}` (same table, same columns; `{base}` is the "
                f"deprecated spelling and is removed at format 1.0, so it is stored under the "
                f"current name — the rename moves no identity, since a fact sidecar sits outside "
                f"`content_signature`)"
            )
        else:
            plan.notes.append(
                f"moved `{source}` to the spec root (the compiler reads authored and derived tables "
                f"from one directory; `{DERIVED_DIR}/` is a layout for readers, not for the compile)"
            )
    return plan
