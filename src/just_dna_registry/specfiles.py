"""
The set of files that make up an authored module spec, in one place.

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

Deliberately *not* a validation rule: composition is the compiler's judgement, not the registry's.
`REQUIRED_SPEC_FILES` is only `module_spec.yaml`, and everything past that
(`"module has no recognized table"`, `"studies.csv is missing"` when `variants.csv` is present) comes
back from `validate_spec` as a proper finding with the compiler's own wording.
"""

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

# The 0.5 derived-fact sidecars, produced by `just-dna-enricher`. Mirrors `compiler._FACT_TABLES`.
# They compile to parquet (so they are part of `artifact.digest` for a module that carries them) but
# are hashed by *facts* rather than raw bytes, because they are multi-producer: the enricher, a
# human, and `reverse_module` all legitimately emit different bytes for the same content.
FACT_CSVS: tuple[str, ...] = (
    "frequencies.csv",
    "gene_metrics.csv",
    "literature.csv",
    "sources.csv",
)

# The rsid↔coordinate table. Produced by the enricher (the only tier permitted to fetch) and
# consumed by the compiler, which never fetches. Not an input-hash member and not an output parquet
# — its identity is `manifest.compilation.resolution_signature`.
RESOLUTION_CSV: str = "resolution.csv"

# Optional structured provenance authored beside the spec. Shipped and hashed like a log, kept out
# of `artifact.digest`.
PROVENANCE_FILE: str = "provenance.json"

SPEC_DATA_FILES: tuple[str, ...] = CORE_CSVS + TABLE_KIND_CSVS + FACT_CSVS + (RESOLUTION_CSV,)

#: Everything a spec directory may legitimately contain, for storage round-trips.
RECOGNIZED_SPEC_FILES: tuple[str, ...] = (SPEC_YAML, PROVENANCE_FILE) + SPEC_DATA_FILES

#: The registry's own precondition before it hands a spec to the compiler. Just the manifest of
#: intent — everything else is the compiler's call.
REQUIRED_SPEC_FILES: tuple[str, ...] = (SPEC_YAML,)

#: Exactly what `just_dna_compiler.compiler.content_signature` reads. Mirrors `_INPUT_FILES`: the
#: fact sidecars and `resolution.csv` are excluded because they are derived, not authored, so two
#: modules with identical authored data share a signature regardless of which sidecars were run.
SIGNATURE_INPUTS: tuple[str, ...] = (SPEC_YAML,) + CORE_CSVS + TABLE_KIND_CSVS


def is_spec_file(name: str) -> bool:
    """Whether `name` is a file the registry recognizes as part of an authored spec."""
    return name in RECOGNIZED_SPEC_FILES


def has_spec_data(names: "set[str] | frozenset[str]") -> bool:
    """Whether `names` carries at least one authored data table.

    The presence gate for revalidate/upgrade: a spec dir holding only `module_spec.yaml` has nothing
    to re-check, but a PGx-only module holding `haplotypes.csv` and no `variants.csv` has plenty.
    """
    return any(name in names for name in SPEC_DATA_FILES)
