"""The authoring hint proxy (0.25) — the enricher's lookups, answered from this box's snapshots.

`just_dna_enricher.lookup` is already the right shape for this: snapshot first, live only for what
the snapshot missed, and it **writes nothing**. Every answer comes back as an `Alteration` with
`applied=False` and a `refusal` naming why the value is the author's to type, because almost every
fact here is cross-examined later by a check that only works if the author wrote it independently.
Proxying it changes none of that; it changes *who holds the snapshots*.

**Named `hint`, not `lookup`.** `GET`/`POST /modules/lookup`, `RegistryClient.lookup_by_digest` and
the console's Lookup page already mean *"is this content published?"*. `hint` is the enricher's own
word for this surface (`hint variant --rsid …`), so it collides with nothing and matches what a user
of that CLI already types.

Two things this layer owes that the enricher does not:

**Paths never leave the process — and since enricher 0.7 that is mostly upstream's doing rather than
ours.** We filed it as S93: `checked` held `str(reference)` and a finding interpolated the same path,
so a host had to scrub its own directory layout out of two places and re-audit every time a field was
added. Upstream answered by **splitting the two**. `checked` is now a set of *labels* — a lane name or
a live source — and `snapshots` is the label → path map, described in their own words as *"the one
place a path lives in the payload, so a host that does not want to publish its layout drops this
field and audits nothing else"*.

So the handling inverted rather than grew: `checked` is reported **as-is** and is the thing a thin
client actually wanted, and `snapshots` is **never serialized**. One scrub survives, and upstream
names why: a duckdb error's own first line may still contain the filename, and that is their sentence
kept as evidence. `hint.snapshots` is the exact label → path map for *this* lookup, which makes that
scrub precise where ours was an approximation over the whole deployment.

**Egress is metered, per upstream, before it is spent.** See `pacing.py` for why the units cannot be
exchanged. The charge is computed from the *shape* of the request — which legs it will run — rather
than measured afterwards, because nothing downstream reports what it actually spent. That is an upper
bound and the field says so.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from just_dna_registry.config import Settings
from just_dna_registry.services.enrich import (
    configured_caches,
    enricher_available,
    lane_presence,
    shared_lookup_clients,
)

#: Which `LookupClients` field paces each metered upstream, so `PaceLedger` can be grounded in the
#: interval the client is really using rather than in a constant. `EutilsClient` picks 10/s with
#: `NCBI_API_KEY` and 3/s without, which is exactly the case a constant gets wrong.
_PACING_CLIENTS: dict[str, tuple[str, ...]] = {
    "ncbi": ("eutils",),
    "gnomad": ("gnomad",),
    "literature": ("crossref", "europepmc"),
    "ontology": ("ontology",),
}


def observed_intervals() -> dict[str, float]:
    """The spacing each upstream is actually being paced at, read off the shared clients.

    The slowest client in a group wins, because a shared budget has to be expressed in the units of
    whichever leg is the bottleneck. Silent about anything it cannot read: a missing entry falls back
    to the declared `base_interval`, which is what `PaceLedger.interval_for` does.
    """
    if not enricher_available():
        return {}
    clients = shared_lookup_clients()
    out: dict[str, float] = {}
    for upstream, fields in _PACING_CLIENTS.items():
        seen = [
            gate.interval
            for name in fields
            if (gate := getattr(getattr(clients, name, None), "gate", None)) is not None
            and isinstance(getattr(gate, "interval", None), int | float)
        ]
        if seen:
            out[upstream] = float(max(seen))
    return out


@dataclass
class HintScrubber:
    """Rewrites this box's snapshot paths to lane names wherever they survive in a hint's prose.

    Since enricher 0.7 this is a **backstop, not the mechanism**: the payload's structured fields are
    already label-only, and the one place a path lives (`snapshots`) is dropped rather than scrubbed.
    What is left is third-party error text — a duckdb failure names the file it could not read, which
    upstream deliberately keeps as evidence.

    Built per request from `lane_presence`, the same resolution the lookup itself used, so the mapping
    cannot describe a different set of snapshots from the one that answered. `text()` additionally
    takes the hint's own `snapshots` map, which is exact for that lookup where this is deployment-wide.
    """

    by_path: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, settings: Settings) -> "HintScrubber":
        mapping: dict[str, str] = {}
        for lane, where in lane_presence(settings).items():
            if where is not None:
                mapping[str(where)] = lane
        # The configured location too, which may differ from the resolved one when a lane resolves
        # through a symlink or a parent.
        for lane, configured in configured_caches(settings).items():
            if configured is not None:
                mapping.setdefault(str(Path(configured)), lane)
        return cls(by_path=mapping)

    def text(self, message: str, snapshots: Mapping[str, str] | None = None) -> str:
        """Prose with any known snapshot path replaced by its lane name.

        `snapshots` is the hint's own label → path map and takes precedence, because it is exact for
        this lookup where `by_path` is whatever the deployment happens to hold. Longest path first, so
        a nested cache directory is not half-rewritten by its parent.
        """
        mapping = {**self.by_path, **{path: label for label, path in (snapshots or {}).items()}}
        for path in sorted(mapping, key=len, reverse=True):
            message = message.replace(path, f"<{mapping[path]} snapshot>")
        return message

    @staticmethod
    def served_from(checked: Any) -> list[str]:
        """The labels — and **a path is withheld rather than mapped or passed on**.

        **No mapping since enricher 0.7.** `checked` is label-only now (S93), so translating it would
        be this service re-deriving something upstream already states.

        The withholding is the part that is not obvious, and it is a floor problem rather than a
        hypothetical. Our floor is `just-dna-enricher>=0.7.0`, and the split that made `checked`
        label-only landed *after* that version number existed — so an install can satisfy the floor
        and still hand us paths, and no floor we can write expresses the difference. Passing an entry
        straight through would leak one; mapping it back to a lane would invent a vocabulary of ours
        inside a field that is upstream's, and be wrong for any snapshot this deployment does not
        configure.

        So an entry that looks like a path is dropped. Nothing is lost by it: *a snapshot answered*
        is already said by the labels beside it and by the hint's own findings, and a caller reading
        `served_from` wants lanes rather than a filesystem. `just-module-creator` reached the same
        answer for the same reason on their in-process read, which is the corroboration that made
        this worth doing rather than assuming the floor held.
        """
        return sorted({
            str(entry) for entry in (checked or ())
            if "/" not in str(entry) and "\\" not in str(entry)
        })


def _findings(hint: Any, scrub: HintScrubber) -> list[dict[str, Any]]:
    snapshots = getattr(hint, "snapshots", None)
    return [
        {
            "level": finding.level,
            "column": finding.column,
            "message": scrub.text(str(finding.message), snapshots),
        }
        for finding in getattr(hint, "findings", [])
    ]


def _alterations(hint: Any, scrub: HintScrubber) -> list[dict[str, Any]]:
    """The enricher's own `as_report_rows` shape, scrubbed.

    Every one carries `applied: false` and a `refusal`, and both are kept: a value this surface
    reports is a value the author still has to type, and the reason is the point rather than a
    footnote. Supplying the cell from the same oracle a later check consults would turn that check
    into a tautology.
    """
    return [
        {
            "column": alteration.column,
            "value": alteration.after,
            "source": alteration.source,
            "applied": alteration.applied,
            "refusal": alteration.refusal,
            "note": scrub.text(str(alteration.note), getattr(hint, "snapshots", None))
            if alteration.note else None,
        }
        for alteration in getattr(hint, "alterations", [])
    ]


def variant_charges(*, rsid: str | None, frequencies: bool, offline: bool) -> dict[str, int]:
    """What one variant hint will spend, by the legs its shape will run.

    Committed before the call because nothing downstream reports what it really spent (filed
    upstream), so a meter that could only look backwards could not refuse anything.

    **NCBI is charged only when an rsID is given**, which is not a nicety: `_check_rsid_currency`
    returns immediately without one, so charging a coordinate-only lookup would bill for a request
    that is never made. And it is charged on *every* online rsID lookup even when the snapshot
    answers, because dbSNP merge status has no snapshot in this tree — Ensembl 400s on some merged
    ids and would misreport them — so that leg runs regardless of a cache hit.
    """
    if offline:
        return {}
    charges: dict[str, int] = {}
    if rsid:
        charges["ncbi"] = 1
    if frequencies:
        charges["gnomad"] = 1
    return charges


def reconcile_ensembl(hint: Any, charges: dict[str, int]) -> dict[str, int]:
    """Add the live-Ensembl unit if the answer actually came from there.

    Read off `checked`, which is a **structured member**, never off a finding's prose: a warning's
    wording is upstream's to change and only the pinned member is an API. Reconciled upward only —
    refunding a committed unit that turned out not to egress would invite a caller to game their own
    miss rate, and the overcharge is bounded at one per call.
    """
    if any("live" in str(entry) for entry in (getattr(hint, "checked", None) or ())):
        charges = dict(charges)
        charges["ensembl"] = charges.get("ensembl", 0) + 1
    return charges


@dataclass
class HintAnswer:
    """One hint, scrubbed, with what it cost and where it came from."""

    payload: dict[str, Any]
    charges: dict[str, int]
    served_from: list[str]


def _caches(settings: Settings) -> dict[str, Path | None]:
    configured = configured_caches(settings)
    return {
        "ensembl_cache": configured.get("ensembl"),
        "clinvar_cache": configured.get("clinvar"),
        "pubmind_cache": configured.get("pubmind"),
    }


def run_variant(
    *,
    settings: Settings,
    scrub: HintScrubber,
    rsid: str | None,
    chrom: str | None,
    start: int | None,
    ref: str | None,
    alts: str | None,
    frequencies: bool,
    offline: bool,
) -> HintAnswer:
    """One variant: validity, coordinates, alleles, clinical calls, and frequencies if asked.

    The caches are passed **as configured**, never as resolved: `lookup_variant` runs the resolver
    ladder itself and reads `None` as *find one for me*, so handing it a resolved-to-`None` empty
    cache licenses exactly the ambient discovery the explicit setting exists to prevent.
    """
    from just_dna_enricher.lookup import lookup_variant

    clients = None if offline else shared_lookup_clients()
    hint = lookup_variant(
        rsid=rsid, chrom=chrom, start=start, ref=ref, alts=alts,
        ambiguity=True, frequencies=frequencies and not offline,
        offline=offline, clients=clients, **_caches(settings),
    )
    charges = variant_charges(rsid=rsid, frequencies=frequencies, offline=offline)
    if not offline:
        charges = reconcile_ensembl(hint, charges)
    status = hint.rsid_status
    return HintAnswer(
        payload={
            "rsid": hint.rsid,
            "rsid_state": status.state if status else None,
            "rsid_current": status.current if status else None,
            "loci": list(hint.loci),
            "rsid_candidates": list(hint.rsid_candidates),
            "populations": list(hint.populations),
            "clin_sig": list(hint.clin_sig),
            "pubmind": list(hint.pubmind),
            "vrs_id": hint.vrs_id,
            # Reported, never picked: more than one locus or more than one rsID at a position is the
            # author's to resolve, and a pick among equals is not a finding.
            "ambiguous": hint.ambiguous,
            "findings": _findings(hint, scrub),
            "alterations": _alterations(hint, scrub),
        },
        charges=charges,
        served_from=scrub.served_from(hint.checked),
    )


def run_citation(
    *, scrub: HintScrubber, pmid: str | None, doi: str | None, pmcid: str | None, offline: bool
) -> HintAnswer:
    """Does this citation exist, and what is its other identifier?

    **Existence is not identity**, which is why the bibliographic fields come back with it: PMIDs are
    densely allocated, so a recalled or invented number is very likely to be a real record — for a
    different paper — and `pmid_exists: true` alone cannot catch a fabricated citation. The answer
    names the paper it found so a caller can compare it against the one they meant.
    """
    from just_dna_enricher.lookup import lookup_citation

    clients = None if offline else shared_lookup_clients()
    hint = lookup_citation(
        pmid=pmid, doi=doi, pmcid=pmcid, offline=offline, clients=clients
    )
    charges: dict[str, int] = {}
    if not offline:
        if pmid or pmcid:
            charges["ncbi"] = 1
        if doi:
            charges["literature"] = 1
    return HintAnswer(
        payload={
            "pmid": hint.pmid, "doi": hint.doi, "pmcid": hint.pmcid,
            "pmid_exists": hint.pmid_exists, "doi_exists": hint.doi_exists,
            "registry_doi": hint.registry_doi,
            "open_access": hint.open_access, "abstract_available": hint.abstract_available,
            "title": hint.title, "journal": hint.journal,
            "year": hint.year, "first_author": hint.first_author,
            "findings": _findings(hint, scrub),
            "alterations": _alterations(hint, scrub),
        },
        charges=charges,
        served_from=[],
    )


def run_gene(*, symbol: str) -> HintAnswer:
    """Is this gene symbol approved or retired? HGNC's exact endpoints, never the fuzzy search."""
    from just_dna_enricher.lookup import lookup_gene

    status = lookup_gene(symbol, clients=shared_lookup_clients())
    return HintAnswer(
        payload={
            "symbol": status.symbol, "state": status.state, "current": status.current,
            "hgnc_id": status.hgnc_id, "location": status.location,
        },
        charges={"ontology": 1},
        served_from=[],
    )


def run_trait(*, curie: str) -> HintAnswer:
    """Is this trait CURIE current, obsolete or unknown? `unchecked` when OLS4 could not be asked."""
    from just_dna_enricher.lookup import lookup_trait

    status = lookup_trait(curie, clients=shared_lookup_clients())
    return HintAnswer(
        payload={
            "curie": status.curie, "state": status.state,
            "label": status.label, "replaced_by": status.replaced_by,
        },
        charges={"ontology": 1},
        served_from=[],
    )


def run_old_assembly(
    *, scrub: HintScrubber, chrom: str, start: int, ref: str | None, alts: str | None, offline: bool
) -> HintAnswer:
    """An hg19 coordinate to an rs-number. **Recovery, not liftover**, and the difference is the design.

    An rs-number authored into `variants.csv` resolves through the ordinary chain into a coordinate a
    later check can cross-examine; a lifted-over position becomes the row's sole identity with nothing
    to check it against. So candidates are reported and never written, and never picked when there is
    more than one.
    """
    from just_dna_enricher.lookup import lookup_old_assembly

    clients = None if offline else shared_lookup_clients()
    hint = lookup_old_assembly(
        chrom=chrom, start=start, ref=ref, alts=alts, offline=offline, clients=clients
    )
    recovery = hint.recovery
    return HintAnswer(
        payload={
            "chrom": recovery.chrom, "start": recovery.start, "outcome": recovery.outcome,
            "ref": recovery.ref, "alts": recovery.alts,
            "rsids": list(recovery.rsids), "candidates": list(recovery.candidates),
            "note": scrub.text(str(recovery.note)) if recovery.note else None,
            "findings": _findings(hint, scrub),
            "alterations": _alterations(hint, scrub),
        },
        charges={} if offline else {"ncbi": 1},
        served_from=[],
    )


def run_variant_batch(
    *,
    settings: Settings,
    scrub: HintScrubber,
    keys: list[dict[str, Any]],
    frequencies: bool,
    offline: bool,
) -> list[HintAnswer]:
    """Resolve many variants: **snapshot first for every key, live only for what missed**.

    This is where the caching-proxy flow is actually implemented, and it is not something the
    single-key routes can do. An online single lookup egresses unconditionally — `_check_rsid_currency`
    puts every rsID to dbSNP whatever the snapshot said, because merge status has no snapshot here —
    so per-key calls would charge for all N. A batch runs the offline pass over all N at zero cost and
    goes online only for the keys that missed, which on a well-provisioned box is none of them.
    """
    answers: list[HintAnswer] = []
    for key in keys:
        offline_answer = run_variant(
            settings=settings, scrub=scrub,
            rsid=key.get("rsid"), chrom=key.get("chrom"), start=key.get("start"),
            ref=key.get("ref"), alts=key.get("alts"),
            frequencies=False, offline=True,
        )
        resolved = bool(offline_answer.payload["loci"])
        if resolved and not frequencies:
            answers.append(offline_answer)
            continue
        if offline:
            answers.append(offline_answer)
            continue
        answers.append(run_variant(
            settings=settings, scrub=scrub,
            rsid=key.get("rsid"), chrom=key.get("chrom"), start=key.get("start"),
            ref=key.get("ref"), alts=key.get("alts"),
            frequencies=frequencies, offline=False,
        ))
    return answers
