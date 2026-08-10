"""
API request/response models (SPEC §8). Distinct from the `ModuleManifest` contract: these are the
catalog's card/detail/version shapes, projected from stored manifests.
"""

import re
from typing import Generic, Optional, TypeVar

from just_dna_format.manifest import ModuleManifest
from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


class CardStats(BaseModel):
    """Stats shown on a module card (genes truncated; full list lives in the manifest)."""

    variant_count: int = 0
    study_count: int = 0
    gene_count: int = 0
    genes: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    clinvar_count: int = 0
    pathogenic_count: int = 0
    benign_count: int = 0


class ResolutionInfo(BaseModel):
    """How well a version's variants were pinned to the genome, and how far to trust that (0.5).

    `mode` is the *policy* the compile ran under; `fully_resolved` is the *outcome*. They are kept as
    separate axes on purpose — a best-effort compile that happened to resolve everything is a
    different thing from a strict one, and collapsing them loses which.
    """

    mode: Optional[str] = Field(default=None, description="strict | best_effort | null (legacy)")
    fully_resolved: bool = False
    trusted: Optional[bool] = Field(
        default=None,
        description="`mode == strict or fully_resolved`. null = the version predates the contract",
    )
    vrs_alleles: int = 0
    vrs_alleles_identified: int = 0
    vrs_complete: Optional[bool] = Field(
        default=None, description="null when there are no alleles — complete-out-of-zero is vacuous"
    )
    sources: list[str] = Field(default_factory=list)
    signature: Optional[str] = None


class LicensingInfo(BaseModel):
    """What the module's sources permit, from `sources.csv` (0.5).

    Every permission is **tri-state**, and `null` is not `false`: a source whose terms could not be
    established has not been shown to permit anything, and has not been shown to forbid it either.

    The per-layer lists exist because only the **annotation** layer taints. A source consulted purely
    to look up a coordinate contributed a fact every reference reports identically, so marking the
    whole module share-alike for it would be a false positive.
    """

    commercial_use: Optional[bool] = None
    redistribution: Optional[bool] = None
    share_alike_layers: list[str] = Field(default_factory=list)
    noncommercial_layers: list[str] = Field(default_factory=list)
    nonredistributable_layers: list[str] = Field(default_factory=list)
    unknown_terms_sources: list[str] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    attributions: list[str] = Field(default_factory=list)
    declared_uses: list[str] = Field(default_factory=list)


class ModuleCard(BaseModel):
    """One entry in the list/search grid (SPEC §8.2)."""

    namespace: str
    name: str
    title: str
    description: str
    icon: str
    icon_set: str = "fomantic"
    color: str
    logo_url: Optional[str] = None  # served logo, when the module ships one; else fall back to icon
    latest_version: Optional[str]
    genome_build: str
    license: Optional[str]
    owner: Optional[str]
    stats: CardStats
    downloads: int
    stars: int = 0
    views: int = 0
    created_at: str = ""  # first-publish time (distinct from updated_at)
    updated_at: str
    starred_by_me: bool = False  # true when the authenticated caller has starred this module
    featured: bool = False
    review_count: int = 0
    avg_rating: Optional[float] = None  # mean 1-5 rating across reviews, None when unreviewed
    curated: bool = False  # has ≥1 owner-highlighted review/audit (the `curated` group)
    author_funding_url: Optional[str] = None  # latest version's author's donation link
    org_funding_url: Optional[str] = None  # owning org's donation link (when the namespace is org-owned)
    # Projected from the latest version's manifest, the same way `stats` is (0.11).
    resolution: ResolutionInfo = Field(default_factory=ResolutionInfo)
    licensing: LicensingInfo = Field(default_factory=LicensingInfo)


class VersionSummary(BaseModel):
    """One entry in a version list (SPEC §8.4)."""

    version: str
    artifact_digest: str
    compile_success: bool
    yanked: bool
    signed: bool = False  # carries an Ed25519 signature over artifact.digest (SPEC §5)
    needs_upgrade: bool = False  # set by the `revalidate` audit: fails the current contract
    # Per-compile, so it belongs on the version rather than the module (0.11). Read from the
    # projected columns, not by parsing `manifest_json`, so a version list gains no per-row parse.
    resolution: ResolutionInfo = Field(default_factory=ResolutionInfo)
    downloads: int = 0  # per-version download count (0.6.0)
    created_at: str
    changelog: str
    manifest_url: str


class ModuleDetail(ModuleCard):
    """Module detail: card + readme + full versions + inline latest manifest (SPEC §8.3)."""

    readme: str
    versions: list[VersionSummary]
    latest_manifest: Optional[ModuleManifest]


class Page(BaseModel, Generic[T]):
    """Paginated envelope: `{items, total, page, per_page}`."""

    items: list[T]
    total: int
    page: int
    per_page: int


class WhoAmI(BaseModel):
    """Identity response for `GET /auth/whoami`. `email` is private — returned only here, to the
    account itself, never in public listings."""

    account: str  # the unique handle (used in URLs and as reviewer attribution)
    namespaces: list[str]
    type: str = "user"  # GitHub-style discriminator: `user` | `org`
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None  # userpic (public http(s) URL)
    funding_url: Optional[str] = None  # donation/sponsor link (public http(s) URL)
    email: Optional[str] = None


# Account identity vocab + light checks (regex-based, to avoid an email-validator / URL dep).
VALID_ACCOUNT_TYPES: frozenset[str] = frozenset({"user", "org"})
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HTTP_URL_RE = re.compile(r"^https?://\S+$")


class ProfileUpdate(BaseModel):
    """Body for `PATCH /auth/whoami` — the account edits its own profile. Omitted fields are left
    unchanged; an empty string clears a field. `type` is not self-editable (admin/creation-time)."""

    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    funding_url: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":  # "" clears the field
            return v
        if not _EMAIL_RE.match(v):
            raise ValueError("email must look like name@host.tld")
        return v

    @field_validator("avatar_url", "funding_url")
    @classmethod
    def _validate_http_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":  # "" clears the field
            return v
        if not _HTTP_URL_RE.match(v):
            raise ValueError("must be an http(s) URL")
        return v


class MemberEntry(BaseModel):
    """One member: an account and its role (`owner` | `admin` | `member`)."""

    account: str
    role: str


class MemberList(BaseModel):
    """Members of a namespace (`GET /namespaces/{ns}/members`)."""

    namespace: str
    members: list[MemberEntry]


class OrgMemberList(BaseModel):
    """Members of an org (`GET /orgs/{org}/members`)."""

    org: str
    members: list[MemberEntry]


class CreateOrgRequest(BaseModel):
    """Body for `POST /orgs` — create an org account and seed the caller as its owner."""

    name: str


class RoleUpdate(BaseModel):
    """Body for `PUT /orgs/{org}/members/{m}/role`."""

    role: str


class OrgSettings(BaseModel):
    """Body for `PATCH /orgs/{org}/settings` — org profile edits (funding link, display, etc.)."""

    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    funding_url: Optional[str] = None
    email: Optional[str] = None

    @field_validator("avatar_url", "funding_url")
    @classmethod
    def _validate_http_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if not _HTTP_URL_RE.match(v):
            raise ValueError("must be an http(s) URL")
        return v


class StarStatus(BaseModel):
    """Star toggle result for a module (`PUT`/`DELETE .../star`)."""

    namespace: str
    name: str
    stars: int
    starred_by_me: bool


# Optional audit tier on a review (a correctness attestation about the reviewed version). A plain
# review omits it and is just a rating + notes.
VALID_VERDICTS: frozenset[str] = frozenset({"verified", "concerns", "rejected"})


class ReviewRequest(BaseModel):
    """Body for posting a review/audit of a version — a 1-5 rating plus an optional audit verdict."""

    rating: int = Field(ge=1, le=5, description="Overall rating, 1-5")
    verdict: Optional[str] = Field(
        default=None, description=f"Optional audit tier, one of {sorted(VALID_VERDICTS)}"
    )
    notes: Optional[str] = Field(default=None, description="Free-text review/audit notes")

    @field_validator("verdict")
    @classmethod
    def _validate_verdict(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(VALID_VERDICTS)}")
        return v


class Review(BaseModel):
    """A published review/audit of a specific version."""

    reviewer: str = Field(description="Reviewer account name")
    version: str
    rating: int
    verdict: Optional[str] = None
    notes: Optional[str] = None
    highlighted: bool = False  # the namespace owner accepted/highlighted this review
    created_at: str
    updated_at: str


class AddMemberRequest(BaseModel):
    """Body for `POST /namespaces/{ns}/members`."""

    account: str
    role: str = "member"


# ── Pre-flight: validation & enrichment dry run (0.11) ────────────────────────
#
# These are what `POST .../validate` and `POST .../check` return. They exist because a publisher's
# real question is not "is this YAML well-formed" but "will my publish be rejected, and why" — so
# the shapes mirror the publish gates rather than the compiler's internals.
#
# One rule runs through all of them: **a finding is not an HTTP error.** A spec that will be refused
# comes back `200` with `valid: false` and the reasons in the body. Only a request we cannot even
# assemble a spec directory from is a 4xx. The endpoint's job is to report.


class VersionRef(BaseModel):
    """One published `(namespace, name, version)` a lookup matched."""

    namespace: str
    name: str
    version: str
    yanked: bool = False


class SpecStats(CardStats):
    """`ValidationResult.stats`, typed.

    Inherits the eight keys a card already models and adds the two only the validator reports. Every
    field defaults, because the compiler documents these keys as de-facto rather than frozen — an
    unknown or absent key should read as zero, not 500 the endpoint.
    """

    unique_rsids: int = 0
    module_name: Optional[str] = None


class ValidationReport(BaseModel):
    """`POST /modules/{ns}/{name}/validate` — the offline half of a publish dry run."""

    valid: bool
    strict: bool = Field(description="The mode the findings were graded under")
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    info: list[str] = Field(
        default_factory=list,
        description="Accepted but noteworthy: keys the server dropped, a version it coerced",
    )
    stats: SpecStats = Field(default_factory=SpecStats)
    content_signature: Optional[str] = Field(
        default=None,
        description="Content identity of the authored rows; None when a data CSV will not parse",
    )
    name_matches_path: bool = Field(
        default=True, description="Whether the spec's module.name matches {name}; publish 422s if not"
    )
    published_as: list[VersionRef] = Field(
        default_factory=list,
        description="Versions already built from identical data — publish would 409 duplicate_content",
    )


class RefMismatchEntry(BaseModel):
    """An authored reference allele the genome does not agree with.

    `shift` is the finding that matters: when the authored `ref` matches the genome a base or two
    away, the wrong column is almost always `start`, not `ref` — which is what subtracting one from
    a VCF position produces, and what passes every offline check.
    """

    variant_key: str
    chrom: str
    start: int
    claimed: str
    actual: str
    genome_build: str = "GRCh38"
    shift: Optional[int] = None


class ClinSigConflictEntry(BaseModel):
    """An authored clinical significance ClinVar's records do not support.

    Reported in both modes and never escalated to a refusal: making the compile arbitrate between
    expert panels is not the format's job, and it is not the registry's either.
    """

    variant_key: str
    chrom: str
    start: int
    authored: str
    clinvar: str
    condition: Optional[str] = None
    opposed: bool = Field(
        default=False, description="Opposed calls (pathogenic vs benign), not merely different"
    )
    confidence: str = Field(default="unrated", description="How much review backs ClinVar's side")


class StaleRsidEntry(BaseModel):
    """What dbSNP currently says about an authored rsID."""

    rsid: str
    state: str = Field(description="live | merged | absent | withdrawn")
    current: Optional[str] = Field(default=None, description="The surviving rsID, when merged")
    fatal: bool = Field(
        default=False, description="`withdrawn` only: refuses in both modes, not just strict"
    )


class VrsCoverage(BaseModel):
    """GA4GH allele-identity coverage over the resolution table.

    Counted per ALT rather than per row, and a shortfall is never a failure: an indel with no
    sequence proxy, or a non-GRCh38 build, is the tier's limit rather than anything the author could
    write differently.
    """

    alleles: int = 0
    identified: int = 0
    complete: Optional[bool] = Field(
        default=None, description="None when there are no alleles — complete-out-of-zero is vacuous"
    )
    unmintable_reasons: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "`reason -> allele count` for every slot left without an id. The actionable half: "
            "'no refget table for build GRCh37' is the tier's own limit, which no authored edit "
            "clears, and a publisher shown only a shortfall would hunt for a mistake that is not "
            "theirs. Grouped by reason rather than listed per row — forty lines each naming a "
            "different indel buries every other finding."
        ),
    )


class FrequencyCheck(BaseModel):
    """gnomAD allele-frequency coverage. Online only, and paced at roughly 6s per 20 variants."""

    covered: int = 0
    missing: list[str] = Field(default_factory=list)
    uncovered: list[str] = Field(
        default_factory=list, description="Never askable — distinct from asked and absent"
    )
    sources: list[str] = Field(default_factory=list)
    skipped_offline: bool = False
    warnings: list[str] = Field(
        default_factory=list,
        description="Why the pass could not run — a degradation, never a module defect",
    )


class LiteratureCheck(BaseModel):
    """Citation existence, DOI agreement, and quote grounding. Online only."""

    missing_pmids: list[str] = Field(default_factory=list)
    missing_dois: list[str] = Field(default_factory=list)
    doi_conflicts: list[str] = Field(default_factory=list)
    quotes_authored: int = 0
    quotes_found: int = 0
    quotes_unchecked: int = Field(
        default=0, description="A quote that could not be checked is not a quote that passed"
    )
    skipped_offline: bool = False
    warnings: list[str] = Field(
        default_factory=list,
        description="Why the pass could not run — e.g. a PGx-only module carries no studies.csv",
    )


class AcmgCheck(BaseModel):
    """Authored `acmg_sf` flags against the ACMG secondary-findings list."""

    list_version: Optional[str] = None
    checked: int = 0
    mismatches: list[str] = Field(default_factory=list)
    unverifiable: list[str] = Field(
        default_factory=list, description="The question could not be put — not a negative answer"
    )
    clean: bool = True
    warnings: list[str] = Field(default_factory=list)


class FunctionConflictEntry(BaseModel):
    """An authored allele function a nomenclature authority does not support."""

    gene: str
    allele: str
    authored: Optional[str] = None
    reported: Optional[str] = None
    source: str


class PgxCheck(BaseModel):
    """Authored PGx assertions against PharmVar, CPIC, ClinPGx and ClinGen dosage.

    `skipped` is the field to read first, and usually the reason nothing happened. Every one of these
    upstreams forbids sale, so with `declared_use="unstated"` (the default) none is even consulted —
    the registry will not assert a purpose on your behalf. Declare `non_commercial` to run it.

    Like every enricher check this reports and never repairs, and — like the `clin_sig` check — it
    does not escalate under strict: making the registry arbitrate between nomenclature authorities is
    not its job.
    """

    conflicts: list[FunctionConflictEntry] = Field(default_factory=list)
    skipped: list[str] = Field(
        default_factory=list, description="Sources not consulted, and why (usually declared_use)"
    )
    warnings: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="Sources actually consulted")
    routes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "`source -> snapshot | live | skipped`. Recorded rather than implied, because a pinned "
            "snapshot and a live API can differ by a release, and a reader has to be able to tell "
            "which answered — the same reason a gnomAD constraint row names its own dataset."
        ),
    )
    offline: bool = Field(
        default=False,
        description="Whether this run was snapshot-only. Not a skip: a provisioned deployment gets "
                    "the full check with zero egress.",
    )
    declared_use: str = "unstated"
    pharmvar_enabled: bool = Field(
        default=False,
        description=(
            "Whether the PharmVar leg could run at all — a built snapshot **or** an API key. It was "
            "key-only through 0.11; a snapshot needs no credential, so the key stopped being the "
            "sole switch. PharmVar is also the one cache the registry cannot pull: its bulk data "
            "comes down under a key its terms make non-transferable, so an operator builds it."
        ),
    )


class IdentifierCheck(BaseModel):
    """Authored trait CURIEs (OLS4) and gene symbols (HGNC) against the registries that own them.

    The generalization of "is the source stale?" from datasets to identifiers: a dbSNP merge, an EFO
    retirement and an HGNC rename each leave a module perfectly well-formed and quietly out of date.
    rsIDs are **not** here — they are checked inside `enrich()`, because their verdict lands on
    `resolution.csv`'s own columns; see `EnrichmentReport.stale_rsids`.

    **Online only, and there is no snapshot to fall back on.** Offline the pass is not run at all and
    says so, because neither OLS4 nor HGNC publishes one and `check_identifiers` takes no `offline`
    parameter to defer the decision to.

    **Nothing here moves `would_publish`.** A publish never runs this pass, so a finding predicts
    nothing about one — it is advice to the author, and reporting it as a publish blocker would
    predict a rejection that will not happen.
    """

    checked_traits: int = 0
    checked_genes: int = 0
    stale_traits: list[str] = Field(
        default_factory=list, description="Obsolete or absent CURIEs, with the replacement when OLS4 names one"
    )
    stale_genes: list[str] = Field(
        default_factory=list, description="Symbols HGNC has retired (with the current one) or never approved"
    )
    unchecked: list[str] = Field(
        default_factory=list,
        description=(
            "Identifiers no question could be put about — a CURIE in an ontology this tier has no "
            "route to. Kept apart from the two above: never asked is not answered-clean"
        ),
    )
    clean: Optional[bool] = Field(
        default=None,
        description="`null` when nothing was checked — clean out of zero identifiers says nothing",
    )
    skipped_offline: bool = False
    warnings: list[str] = Field(
        default_factory=list,
        description="Why the pass could not run, or could only partly run — never a module defect",
    )


class EnrichmentReport(BaseModel):
    """What the network tier found. Every entry is reported, never repaired.

    `mode` is always `best_effort`, whatever `?strict=` said. Strict enrichment *raises*, and an
    endpoint whose purpose is to report cannot be run in a mode that refuses to finish.
    """

    mode: str = "best_effort"
    offline: bool = False
    unresolved: list[str] = Field(default_factory=list)
    ref_mismatches: list[RefMismatchEntry] = Field(default_factory=list)
    clin_sig_conflicts: list[ClinSigConflictEntry] = Field(default_factory=list)
    #: Read this **before** believing an empty `clin_sig_conflicts` (enricher 0.5.2 / S4).
    clin_sig_not_checked: Optional[str] = Field(
        default=None,
        description=(
            "Why the ClinVar clin_sig cross-check did not run, or null when it did. An empty "
            "`clin_sig_conflicts` means two opposite things on its own — 'compared everything, "
            "nothing disagreed' and 'never compared' — so a client must not read the first without "
            "checking this. Reasons: `not_requested` (the operator disabled it), `no_snapshot` (no "
            "ClinVar snapshot on this deployment), or prose saying the module declares it was "
            "drafted from the very snapshot the check reads, which makes the comparison a value "
            "against itself and its zero structurally guaranteed."
        ),
    )
    stale_rsids: list[StaleRsidEntry] = Field(default_factory=list)
    par_twins_dropped: list[str] = Field(
        default_factory=list, description="Y pseudoautosomal spellings folded onto their X twin"
    )
    vrs: VrsCoverage = Field(default_factory=VrsCoverage)
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list,
        description="Degradations that are not findings — e.g. a snapshot that was not provisioned",
    )
    frequencies: Optional[FrequencyCheck] = None
    literature: Optional[LiteratureCheck] = None
    identifiers: Optional[IdentifierCheck] = None
    acmg: Optional[AcmgCheck] = None
    pgx: Optional[PgxCheck] = None


class CheckReport(BaseModel):
    """`POST /modules/{ns}/{name}/check` — the full publish dry run."""

    validation: ValidationReport
    enrichment: Optional[EnrichmentReport] = None
    skipped_reason: Optional[str] = Field(
        default=None,
        description="Why enrichment was not attempted, e.g. `invalid_spec` (nothing to enrich yet)",
    )
    would_publish: bool = Field(
        default=False,
        description="Whether a publish with these settings would succeed — the field CI branches on",
    )
    elapsed_seconds: float = 0.0


class LookupBatch(BaseModel):
    """Body for `POST /modules/lookup`: resolve many identities in one call.

    Two different identities, deliberately in one endpoint. `digests` names *compiled bytes* and
    answers "is this exact artifact published"; `signatures` names *authored data* and answers "is
    this module published, under any name, compiled against any reference". A client classifying a
    local corpus usually wants both.
    """

    digests: list[str] = Field(default_factory=list)
    signatures: list[str] = Field(default_factory=list)


class LookupMatch(BaseModel):
    """One key and everything published under it."""

    digest: Optional[str] = None
    signature: Optional[str] = None
    matches: list[VersionRef] = Field(default_factory=list)


class LookupBatchResponse(BaseModel):
    results: list[LookupMatch] = Field(default_factory=list)
