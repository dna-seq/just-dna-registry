"""Drafting run against the server's snapshots (0.25) — the enricher's drafters, rented out.

**Drafting is still authoring-side, and this service still drafts nothing of its own.** The recorded
position — *"the honest answer for this service was that it has none"* — was about a `registry
upgrade` sweep, and it stays true: a re-draft is not a catalog migration, and nothing here re-drafts a
published module. What changes is that a client that cannot run a drafter can now ask a box that can.

The reason it is worth an endpoint: `just-module-creator` is a Claude Code / Codex plugin that reaches
this registry over HTTPS from an author's machine, and its own `.env.template` tells that author
*"the Ensembl snapshot alone is ~14 GB"*. It has the enricher **package** — it calls these drafters as
a Python API already — and what it does not reliably have is the snapshots.

**Stateless is the whole safety argument.** `CLAUDE.md` records that a re-draft over an existing spec
*appends* corrected rows beside the ones they supersede, so the publisher needs a fresh spec
directory. Nothing is held here between calls: a caller uploads a tree, the drafter appends into that
tree, and the tree comes back. The server cannot append a correction beside a superseded row across
two calls because it has no memory of the first. What a caller can still do to themselves is upload an
already-drafted spec twice, which is why every outcome is counted and reported by name —
`already_present` and `differs` are what that looks like from the outside — and why `dry_run` exists.

**Snapshot-only, forced.** `download=False` is the standing rule for a request path, and `offline=True`
follows from it here for a sharper reason than convenience: `pgx_draft.draft_gene` takes a bare
`client=` and `LookupClients` has no CPIC field at all, so an online CPIC draft would build an
unshared, unpaced client per request — exactly the violation *one shared bundle per process* exists to
prevent. Filed upstream rather than worked around. The consequence is that a draft makes no outbound
request, so it takes no enrichment permit and rides the `/validate` lane: CPU, bounded by its bucket
and a timeout.

**Why the drafter imports are inside the adapters.** The house rule is that imports live at module
top level; this module is the same exception `services/enrich.py` is, for the same mechanical reason.
The enricher ships in the `server` extra and the compile path must never reach it — so a module-level
`just_dna_enricher` import here would make `services/drafting` unimportable on a compiler-only
install, and would put the network tier one import away from `services/publish`, which this module
already imports from. A test asserts the laziness rather than trusting the comment.
"""

import io
import json
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from just_dna_format.vocab import TEMPLATE_PLACEHOLDER

from just_dna_registry.config import Settings
from just_dna_registry.services.enrich import cache_lanes, enricher_available, lane_presence
from just_dna_registry.services.publish import PublishError, normalize_spec
from just_dna_registry.specfiles import DRAFT_REPORT_FILE

#: The exception each source raises, as `(module, class)` — resolved lazily, like every other enricher
#: import here. Upstream's ENRICHER.md carries the full roster (RM216) and walks it against the
#: package, which is what makes naming them here safe rather than a hand-kept list going stale in the
#: dark: `test_every_draft_source_names_an_error_type_the_enricher_defines` resolves every entry.
_SOURCE_ERRORS: dict[str, tuple[str, str]] = {
    "clinvar": ("just_dna_enricher.clinvar_draft", "ClinVarDraftError"),
    "pubmind": ("just_dna_enricher.pubmind_draft", "PubMindDraftError"),
    "civic": ("just_dna_enricher.civic_draft", "CivicDraftError"),
    "mitomap-miss": ("just_dna_enricher.mitomap_draft", "MitomapDraftError"),
    "clinpgx": ("just_dna_enricher.clinpgx_draft", "ClinPgxEnrichmentError"),
    "cpic": ("just_dna_enricher.pgx_draft", "CpicError"),
    "strchive": ("just_dna_enricher.strchive_draft", "StrchiveDraftError"),
}

#: What **every** drafter can raise regardless of source, which is the half a per-source list misses.
#: `enrich.source_build_mismatch` runs before any provider writes a coordinate and raises
#: `EnrichmentError` on a `module_spec.yaml` it cannot read — an ordinary mid-authoring state, not a
#: broken request. Upstream hit this exact shape and answered it with a shared tuple rather than two
#: more `except` clauses, precisely so the next provider inherits the handling instead of
#: rediscovering it. We were the next provider and rediscovered it: a spec carrying only `name:`
#: returned a traceback from `POST /drafts` until 0.25.
_PRECONDITION_ERRORS: tuple[tuple[str, str], ...] = (
    ("just_dna_compiler.draft", "DraftError"),
    ("just_dna_enricher.enrich", "EnrichmentError"),
    ("just_dna_enricher.licensing", "LicenseRefusal"),
)


def draft_errors(source_name: str) -> tuple[type[Exception], ...]:
    """Every exception this source's drafter can raise that is the caller's problem, not a bug.

    Deliberately **not** a bare `except Exception`: a drafter failing in a way nobody predicted is a
    defect and should reach the logs as one, rather than being flattened into a `422` that tells a
    publisher to fix a spec that is fine.
    """
    import importlib

    names = [*_PRECONDITION_ERRORS, _SOURCE_ERRORS[source_name]]
    return tuple(getattr(importlib.import_module(module), cls) for module, cls in names)


#: Re-exported from `specfiles`, where the client can reach it too. It is dropped at the archive root
#: beside the spec files rather than in a wrapper folder, so the archive is directly re-uploadable to
#: `/check` or back to this route — safe there for the reason `derived/` is safe: the compiler
#: tolerates unknown files as a contract, `plan_layout` leaves unrecognized files where they are, and
#: `SIGNATURE_INPUTS` is a closed root-level tuple, so a carried report can move neither
#: `content_signature` nor `artifact.digest`.


@dataclass
class DraftRequest:
    """One drafting call, with every parameter any source could want.

    A union rather than seven models, because the route is one route. The guard that keeps that
    honest is `DraftSource.params`: a parameter that means nothing for the chosen source is a `422`,
    never silently dropped — a dropped `min_evidence_level` produces a draft answering a different
    question from the one asked, which is "unchecked is not clean" wearing a different hat.
    """

    spec_dir: Path
    genes: Sequence[str] = ()
    drugs: Sequence[str] = ()
    alleles: Sequence[str] = ()
    population: str | None = None
    clin_sig: Sequence[str] = ()
    min_review_stars: int | None = None
    max_citations: int | None = None
    min_confidence: int | None = None
    min_evidence_level: str | None = None
    declared_use: str = "unstated"
    dry_run: bool = False
    #: `{lane: resolved path}` for the lanes this source declared. Filled by `run_draft`, never
    #: resolved inside an adapter: a drafter handed `None` falls through to the enricher's ambient
    #: ladder, which is the discovery the explicit setting exists to prevent.
    snapshots: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class DraftSource:
    """One drafting lane: what it reads, what it accepts, and how it is called."""

    name: str
    #: Lanes that must be on disk. Absence is a `503 snapshot_unavailable` naming the lane — never
    #: `enrichment_unavailable`, which means the tier is not installed at all.
    lanes: tuple[str, ...]
    #: `one` · `many` · `optional`. CPIC drafts a single gene per call and the others take a panel.
    genes: str
    #: Every request parameter this source reads, beyond `genes`. Anything else sent with it is a 422.
    params: frozenset[str]
    run: Callable[[DraftRequest], Any]
    #: What a caller gets out, for the response's `next_step`.
    produces: tuple[str, ...]


def _clinvar(request: DraftRequest) -> Any:
    from just_dna_enricher.clinvar_draft import DEFAULT_CLIN_SIG, draft_gene_panel

    return draft_gene_panel(
        request.spec_dir, list(request.genes),
        snapshot=request.snapshots["clinvar"],
        clin_sig=frozenset(request.clin_sig) if request.clin_sig else DEFAULT_CLIN_SIG,
        min_review_stars=request.min_review_stars if request.min_review_stars is not None else 2,
        max_citations=request.max_citations if request.max_citations is not None else 3,
        declared_use=request.declared_use, offline=True, download=False, dry_run=request.dry_run,
    )


def _pubmind(request: DraftRequest) -> Any:
    from just_dna_enricher.clinvar_draft import DEFAULT_CLIN_SIG
    from just_dna_enricher.pubmind_draft import draft_gene_panel_from_pubmind

    return draft_gene_panel_from_pubmind(
        request.spec_dir, list(request.genes),
        snapshot=request.snapshots["clinvar"],
        pubmind_snapshot=request.snapshots["pubmind"],
        clin_sig=frozenset(request.clin_sig) if request.clin_sig else DEFAULT_CLIN_SIG,
        min_confidence=request.min_confidence if request.min_confidence is not None else 1,
        declared_use=request.declared_use, offline=True, download=False, dry_run=request.dry_run,
    )


def _civic(request: DraftRequest) -> Any:
    from just_dna_enricher.civic_draft import draft_panel_from_civic

    # `offline=True` also decides the ClinGen allele registry leg: the drafter builds its own
    # `ClingenAlleleClient(offline=offline)` and a `SequenceProxy`, neither of which is the shared
    # bundle, so an online run here would egress on per-request clients.
    return draft_panel_from_civic(
        request.spec_dir, list(request.genes),
        snapshot=request.snapshots["civic"],
        declared_use=request.declared_use, offline=True, dry_run=request.dry_run,
    )


def _mitomap_miss(request: DraftRequest) -> Any:
    from just_dna_enricher.mitomap_draft import draft_panel_from_mitomap_miss

    return draft_panel_from_mitomap_miss(
        request.spec_dir, list(request.genes),
        snapshot=request.snapshots["mitomap_miss"],
        declared_use=request.declared_use, dry_run=request.dry_run,
    )


def _clinpgx(request: DraftRequest) -> Any:
    from just_dna_enricher.clinpgx_draft import draft_pharm_variants

    return draft_pharm_variants(
        request.spec_dir,
        snapshot=request.snapshots["clinpgx"],
        genes=list(request.genes), drugs=list(request.drugs),
        min_evidence_level=request.min_evidence_level,
        declared_use=request.declared_use, dry_run=request.dry_run,
    )


def _cpic(request: DraftRequest) -> Any:
    from just_dna_enricher.pgx_draft import draft_gene

    return draft_gene(
        request.spec_dir, request.genes[0],
        drugs=list(request.drugs), alleles=list(request.alleles),
        population=request.population, declared_use=request.declared_use,
        dry_run=request.dry_run, offline=True, cpic_cache=request.snapshots["cpic"],
    )


def _strchive(request: DraftRequest) -> Any:
    from just_dna_enricher.strchive_draft import draft_repeat_loci

    # `catalogue=`, not `snapshot=`: this lane is a file the drafter reads, which is why the setting
    # behind it is named `strchive_catalogue` rather than `..._cache`.
    return draft_repeat_loci(
        request.spec_dir, list(request.genes),
        catalogue=request.snapshots["strchive"],
        declared_use=request.declared_use, dry_run=request.dry_run,
    )


#: Every source this endpoint offers, under the spelling the enricher's own `draft-panel --source`
#: uses, with its three standalone commands folded in beside them.
DRAFT_SOURCES: dict[str, DraftSource] = {
    "clinvar": DraftSource(
        name="clinvar", lanes=("clinvar",), genes="many",
        params=frozenset({"clin_sig", "min_review_stars", "max_citations"}),
        run=_clinvar, produces=("variants.csv", "studies.csv"),
    ),
    "pubmind": DraftSource(
        # Two lanes, and that is exactly why the response names which ones it read: "which snapshots
        # answered" is not derivable from the source name.
        name="pubmind", lanes=("pubmind", "clinvar"), genes="many",
        params=frozenset({"clin_sig", "min_confidence"}),
        run=_pubmind, produces=("variants.csv",),
    ),
    "civic": DraftSource(
        name="civic", lanes=("civic",), genes="optional", params=frozenset(),
        run=_civic, produces=("variants.csv", "studies.csv"),
    ),
    "mitomap-miss": DraftSource(
        name="mitomap-miss", lanes=("mitomap_miss",), genes="optional", params=frozenset(),
        run=_mitomap_miss, produces=("variants.csv", "studies.csv"),
    ),
    "clinpgx": DraftSource(
        name="clinpgx", lanes=("clinpgx",), genes="optional",
        params=frozenset({"drugs", "min_evidence_level"}),
        run=_clinpgx, produces=("pharm_variants.csv",),
    ),
    "cpic": DraftSource(
        name="cpic", lanes=("cpic",), genes="one",
        params=frozenset({"drugs", "alleles", "population"}),
        run=_cpic, produces=("haplotypes.csv", "allele_function.csv", "diplotypes.csv"),
    ),
    "strchive": DraftSource(
        name="strchive", lanes=("strchive",), genes="optional", params=frozenset(),
        run=_strchive, produces=("repeat_alleles.csv",),
    ),
}


def _reports(result: Any) -> list[Any]:
    """The `DraftReport`s out of a result, whatever this source's shape calls them.

    The seven result classes are **not** uniform — `StrchiveDraftResult` carries `report` singular,
    `PubMindDraftResult` has no `skipped` at all, and the derived count properties differ per class
    (`added`/`already_present`/`invalid` on one, `added`/`differs` on another). So the counts below
    are computed from `RowOutcome.status`, which every one of them shares, rather than read off
    properties that exist on some and not others.
    """
    if hasattr(result, "reports"):
        return list(result.reports)
    single = getattr(result, "report", None)
    return [single] if single is not None else []


def _tables(result: Any) -> list[dict[str, Any]]:
    tables = []
    for report in _reports(result):
        counts: dict[str, int] = {}
        differences = []
        for outcome in report.outcomes:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            if outcome.status == "differs" and outcome.differences:
                differences.append({
                    "key": list(outcome.key) if outcome.key else None,
                    "fields": {
                        name: {"authored": authored, "source": incoming}
                        for name, (authored, incoming) in sorted(outcome.differences.items())
                    },
                })
        tables.append({
            # `csv_name`, never `report.path` — that is an absolute path on this server.
            "csv": report.csv_name,
            "added": counts.get("added", 0),
            "already_present": counts.get("already_present", 0),
            "differs": counts.get("differs", 0),
            "appended_unkeyed": counts.get("appended_unkeyed", 0),
            "invalid": counts.get("invalid", 0),
            "written": report.written,
            "header_extended": list(report.header_extended),
            "shifted": list(report.shifted),
            "differences": differences,
        })
    return tables


def resolve_snapshots(source: DraftSource, settings: Settings) -> dict[str, Path]:
    """Every lane this source needs, or a `503` naming the first one that is not there.

    **Not `enrichment_unavailable`.** That code means the network tier is not installed at all, and a
    missing snapshot is explicitly not it. A separate code, with the lane named and the lane's own
    recorded route reason attached, because the remedy is an operator's and they need to know which
    lane and by what route.
    """
    if not enricher_available():
        raise PublishError(
            "enrichment_unavailable",
            errors=["just-dna-enricher is not installed (install the `server` extra)"],
            extra={"missing": list(source.lanes)},
        )
    lanes = cache_lanes()
    present = lane_presence(settings)
    resolved: dict[str, Path] = {}
    for lane_name in source.lanes:
        where = present.get(lane_name)
        if where is None:
            lane = lanes.get(lane_name)
            reason = (lane.unpublished or lane.unbuilt) if lane is not None else None
            raise PublishError(
                "snapshot_unavailable",
                errors=[
                    f"the {lane_name} snapshot is not provisioned on this deployment, so "
                    f"?source={source.name} has nothing to draft from"
                ],
                extra={
                    "lane": lane_name,
                    "source": source.name,
                    "route": ("pullable" if lane is not None and lane.ensure is not None
                              else "buildable" if lane is not None and lane.rebuild is not None
                              else "none"),
                    "route_reason": reason,
                },
            )
        resolved[lane_name] = where
    return resolved


def check_params(source: DraftSource, sent: set[str]) -> None:
    """Refuse a parameter the chosen source does not read, rather than dropping it.

    One route over seven drafters means a union of parameters, and a union silently ignored is a
    draft answering a different question from the one asked. `genes` is handled separately because
    every source takes it, in one of three arities.
    """
    stray = sorted(sent - source.params)
    if stray:
        raise PublishError(
            "param_not_for_source",
            errors=[
                f"?source={source.name} does not read {', '.join(stray)}. It reads "
                f"{', '.join(sorted(source.params)) or 'no parameters beyond genes'}."
            ],
            extra={"source": source.name, "rejected": stray, "accepted": sorted(source.params)},
        )


def check_genes(source: DraftSource, genes: Sequence[str]) -> None:
    """`one` / `many` / `optional`, refused up front rather than as an IndexError in an adapter."""
    if source.genes == "one" and len(genes) != 1:
        raise PublishError(
            "gene_count",
            errors=[f"?source={source.name} drafts one gene per call, got {len(genes)}"],
            extra={"source": source.name},
        )
    if source.genes == "many" and not genes:
        raise PublishError(
            "gene_count",
            errors=[f"?source={source.name} needs at least one gene"],
            extra={"source": source.name},
        )


def run_draft(
    *,
    settings: Settings,
    uploads: dict[str, bytes],
    source_name: str,
    request: DraftRequest,
) -> "DraftArchive":
    """Materialize the upload, run the drafter against this box's snapshots, hand the tree back.

    Synchronous and blocking; the router hands it to a threadpool worker. It takes no enrichment
    permit because it makes no outbound request — see the module docstring.
    """
    source = DRAFT_SOURCES[source_name]
    snapshots = resolve_snapshots(source, settings)

    with tempfile.TemporaryDirectory() as tmp:
        spec_dir = Path(tmp) / "spec"
        for rel, data in uploads.items():
            dest = spec_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        # The same normalization a publish applies, so a caller drafting into an upload laid out
        # their way gets a tree laid out the way this registry would have stored it.
        normalization = normalize_spec(spec_dir)

        request.spec_dir = spec_dir
        request.snapshots = snapshots
        try:
            result = source.run(request)
        except draft_errors(source_name) as exc:
            # A refusal the caller can act on, reported as one. Without this the endpoint answered a
            # mid-authoring `module_spec.yaml` with a traceback, which is the shape CLAUDE.md records
            # for `/check` before enricher 0.6.2: an endpoint whose contract is to report, failing.
            raise PublishError(
                "draft_failed",
                errors=[str(exc)],
                extra={"source": source.name, "error_type": type(exc).__name__},
            ) from exc
        return _pack(
            spec_dir, source, result, snapshots, request,
            info=normalization.info, warnings=normalization.warnings,
        )


@dataclass
class DraftArchive:
    archive: bytes
    filename: str
    report: dict[str, Any]


def _pack(
    spec_dir: Path,
    source: DraftSource,
    result: Any,
    snapshots: dict[str, Path],
    request: DraftRequest,
    *,
    info: list[str],
    warnings: list[str],
) -> DraftArchive:
    """Tar the drafted tree with the report beside it.

    **The archive is forced, not preferred.** `RowOutcome` carries `key`, `status` and `differences`
    and never the row cells, so a JSON-only response could not reconstruct what was drafted. The
    bytes are the only faithful carrier.
    """
    tables = _tables(result)

    # **Which tables actually need a curator, read off the bytes rather than assumed.** Not every
    # drafted table carries the placeholder: `studies.csv` gains citation rows (rsid, pmid) that need
    # no judgement, while `variants.csv` gains rows whose genotype and conclusion only a curator can
    # decide. Naming every file the source writes would tell an author to go and fill cells that are
    # already complete, so the list is computed from what is on disk.
    needs_curation = sorted({
        table["csv"] for table in tables
        if table["written"] and (spec_dir / table["csv"]).is_file()
        and TEMPLATE_PLACEHOLDER in (spec_dir / table["csv"]).read_text(errors="ignore")
    })

    report = {
        "source": source.name,
        "declared_use": request.declared_use,
        "dry_run": request.dry_run,
        # `skipped` is absent from one of the seven result classes, so it is read defensively rather
        # than assumed: a declared-use refusal sets it, and that is not "nothing to add".
        "skipped": bool(getattr(result, "skipped", False)),
        "tables": tables,
        # Which snapshots answered. Not derivable from `source` — pubmind reads two lanes — and
        # without it a draft from a half-provisioned box is indistinguishable from one that found
        # nothing, which is the `would publish` over an outage a tier up.
        "lanes_read": sorted(snapshots),
        "warnings": list(getattr(result, "warnings", [])),
        "normalized": list(info),
        "normalization_warnings": list(warnings),
        # Fixed, not derived by running `validate`: the placeholder guarantees the answer, and
        # deriving it would cost a full validation pass and mean reading a verdict to decide a
        # message.
        "validates": False,
        "placeholder": TEMPLATE_PLACEHOLDER,
        "needs_curation": needs_curation,
        "next_step": (
            # A dry run writes nothing, so `needs_curation` is empty for a reason that has nothing to
            # do with whether curation is owed — the one shape where an empty list would otherwise
            # read as "all clear". Said explicitly rather than inferred from the empty list.
            (
                "Preview only — nothing was written. Re-run without dry_run to get the tree, then "
                "fill the cells the report marks and run /check."
            )
            if request.dry_run
            else (
                f"Drafted rows carry {TEMPLATE_PLACEHOLDER} where only a curator can decide the "
                f"value, so this spec will not pass /validate yet and that is by design. Fill those "
                f"cells in {', '.join(needs_curation)}, then run /check, then publish."
            )
            if needs_curation
            else (
                "Nothing here needs a curated cell. Run /check before publishing — a draft is still "
                "an unvalidated spec, and a source writing only derived rows is not a source that "
                "wrote nothing."
            )
        ),
    }

    members: list[tuple[str, bytes]] = []
    if not request.dry_run:
        for path in sorted(spec_dir.rglob("*")):
            if path.is_file():
                members.append((str(path.relative_to(spec_dir)), path.read_bytes()))
    members.append((DRAFT_REPORT_FILE, json.dumps(report, indent=2, sort_keys=True).encode()))

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for arcname, data in members:
            entry = tarfile.TarInfo(arcname)
            entry.size = len(data)
            entry.mtime = 0
            entry.mode = 0o644
            tar.addfile(entry, io.BytesIO(data))
    return DraftArchive(
        archive=buf.getvalue(), filename=f"{source.name}-draft.tar.gz", report=report
    )
