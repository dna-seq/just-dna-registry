"""
API request/response models (SPEC §8). Distinct from the `ModuleManifest` contract: these are the
catalog's card/detail/version shapes, projected from stored manifests.
"""

import re

from just_dna_format.manifest import ModuleManifest
from pydantic import BaseModel, Field, field_validator


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

    mode: str | None = Field(default=None, description="strict | best_effort | null (legacy)")
    fully_resolved: bool = False
    trusted: bool | None = Field(
        default=None,
        description=(
            "Whether this version is fully-baked. false when the compiler reported a table that no "
            "VCF can join by position (rows with no chrom+start); otherwise `mode == strict or "
            "fully_resolved`. null = we cannot say — the version predates the contract, or it has no "
            "`variants.csv`, which makes `fully_resolved` an empty all() rather than a verdict."
        ),
    )
    vrs_alleles: int = 0
    vrs_alleles_identified: int = 0
    vrs_complete: bool | None = Field(
        default=None, description="null when there are no alleles — complete-out-of-zero is vacuous"
    )
    # ── 0.6 counters (RM44 / S31 / S33). `null` is *not measured*, and never `0`. ──
    #
    # Every one of these is `null` on a version compiled before 0.6, and `0` is a real answer for
    # each: "no variant rows were resolved", "this module carries no positional table", "resolution
    # found no one-to-many expansion". Coalescing the two would say something false about an existing
    # catalog — that a 1,482-row PGx artifact has no positional rows — which is the vacuous
    # `fully_resolved` failure re-made inside the fields written to close it.
    resolution_subjects: int | None = Field(
        default=None,
        description=(
            "Variant rows `fully_resolved` was evaluated over, after rsID expansion. Read it beside "
            "`fully_resolved`: `true` over `0` subjects is an empty all(), not a verdict. null = the "
            "version predates 0.6 and did not count."
        ),
    )
    positional_rows: int | None = Field(
        default=None,
        description="Rows across pharm_variants/haplotypes/heteroplasmy. 0 = no such table; null = not counted.",
    )
    positional_rows_placed: int | None = Field(
        default=None,
        description=(
            "Of those, how many carry chrom+start and therefore join to a VCF by position. Complete "
            "is `placed == rows` — parts rather than a ratio, so a shortfall's size is visible."
        ),
    )
    expanded_keys: int | None = Field(
        default=None,
        description="Authored identities that resolved onto more than one locus (null = not counted).",
    )
    expanded_rows: int | None = Field(
        default=None,
        description=(
            "Rows those keys became. Only one member per genotype can match; the difference from "
            "`expanded_keys` is **not** the count of non-matching rows."
        ),
    )
    sources: list[str] = Field(
        default_factory=list,
        description=(
            "Reference sources the resolution consulted. Populated on every surface since 0.19; "
            "through 0.18 a version-list row always reported `[]` regardless of the manifest, so an "
            "empty list there meant 'not projected' and 'none consulted' indistinguishably (S14)."
        ),
    )
    signature: str | None = Field(
        default=None,
        description=(
            "`compilation.resolution_signature` — the fact signature over what resolution decided. "
            "It moves when an upstream source revises an answer while `content_signature` stands "
            "still, which makes it the field a cross-version comparison keys on. Populated on the "
            "version list since 0.19 (S14); `null` means the version carries none, not that it was "
            "not read."
        ),
    )


class LicensingInfo(BaseModel):
    """What the module's sources permit, from `sources.csv` (0.5).

    Every permission is **tri-state**, and `null` is not `false`: a source whose terms could not be
    established has not been shown to permit anything, and has not been shown to forbid it either.

    The per-layer lists exist because only the **annotation** layer taints. A source consulted purely
    to look up a coordinate contributed a fact every reference reports identically, so marking the
    whole module share-alike for it would be a false positive.
    """

    commercial_use: bool | None = None
    redistribution: bool | None = None
    share_alike_layers: list[str] = Field(default_factory=list)
    noncommercial_layers: list[str] = Field(default_factory=list)
    nonredistributable_layers: list[str] = Field(default_factory=list)
    unknown_terms_sources: list[str] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    attributions: list[str] = Field(default_factory=list)
    declared_uses: list[str] = Field(default_factory=list)


class WeightingInfo(BaseModel):
    """What the module says its authored `weight` column means (0.6, RM92). All three free text.

    Rendered **verbatim**, never parsed and never normalized. Upstream chose free text deliberately —
    a closed vocabulary would have had to enumerate scales nobody has surveyed — so any tidying here
    would be this catalog inventing a taxonomy the format refused to invent.

    **An absent block means the module has not said, which is not the same as "the weights are
    comparable".** That distinction is the entire point of the block existing: `weight` is a bare
    float with no unit column, every module means something different by it, and until 0.6 the
    artifact had no way to say so. A consumer aggregating weights across modules should read absence
    as *do not*.
    """

    scale: str | None = None
    method: str | None = None
    note: str | None = None


class GwasEffectsInfo(BaseModel):
    """The GWAS Catalog effect-size sidecar's facets (0.6, RM90).

    **`units` and `without_effect_allele` are surfaced beside `row_count`, not behind it**, on
    upstream's explicit warning that a row count alone reads as confidence. They are what tell a
    reader whether these effects are usable at all:

    * more than one entry in `units` means the betas are on **different scales** and must not be
      pooled — one real variant in the reference corpus carries twelve distinct unit spellings across
      62 traits, three of which are spellings of "SD";
    * `without_effect_allele` counts associations the Catalog published without establishing which
      allele carries the effect (it writes `rs4149056-?`) — 42 of 195 on that same module. Those rows
      are real evidence and cannot be used as a weight in any direction. They are counted rather than
      filtered precisely so that neither dropping them nor keeping them can happen by accident.

    This is **not** a substitute for the authored `weight`, and a consumer must not treat it as one:
    the two are different methodologies, and `weight` is positive-is-protective while a GWAS beta is
    positive on its effect allele.
    """

    row_count: int = 0
    variant_count: int = 0
    with_effect_allele: int = 0
    without_effect_allele: int = 0
    measures: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)


class VerificationCheck(BaseModel):
    """One check, and what putting it produced. Every field is the publisher's claim — see below."""

    check: str
    subjects: int = 0
    findings: int = 0
    skipped: str | None = Field(
        default=None,
        description="Why the check did not run. null = it ran. `subjects: 0` with no reason is a "
        "check that ran and had nothing to look at, which is not the same as one that was skipped.",
    )
    detail: str | None = None
    source: str | None = None
    release: str | None = None
    checked_at: str | None = None


class VerificationInfo(BaseModel):
    """Whether anything this module asserts was ever *checked* (0.6, RM45) — as a claim, not a verdict.

    **Absent reads as *nothing was said*, never as *passed*.** Upstream marks every field of the
    manifest block untrusted for that reason, and the block is also absent when an attestation no
    longer matches the bytes it was made against, which reads correctly the same way.

    **How much of this is ours, measured rather than assumed** (pinned by
    `tests/test_specfiles.py::test_a_publisher_cannot_forge_a_check_this_server_runs`):

    * A check **this server runs** cannot be forged. Publish runs enrichment itself and attests what
      it saw, and that record displaces whatever arrived under the same name — an upload claiming
      `clinical_significance` ran over 999 subjects publishes as our own record instead.
    * A check **this server does not run** survives verbatim and is unverifiable. Nothing here
      produces `acmg_secondary_findings`, so a fabricated one is carried into the manifest as sent.
      That is the residual surface and the reason nothing in this block is presented as a registry
      verdict.
    * `closed` is the sturdiest field, because the closure is **hash-bound**: the compiler recomputes
      the binding against the authored bytes and drops the whole closure when it does not match. So
      `closed: true` cannot be claimed by editing a JSON file — though `closed_by` is free text, and
      proves that someone declared authoring finished, not who.

    Deliberately **not** a card facet and deliberately not a filter. A registry that let you sort by
    someone else's unverifiable pass would be lending it our credibility, which is the one thing this
    surface must not do.
    """

    closed: bool = Field(
        default=False,
        description="A closure survived the compiler's re-binding: a human declared this module "
        "final and the authored bytes have not moved since. The one field here with a check behind it.",
    )
    closed_at: str | None = None
    closed_by: str | None = Field(
        default=None, description="Free text. Who they say they are, not who they are."
    )
    producer: str | None = Field(
        default=None, description="Tool and version that last wrote the attestation. Untrusted."
    )
    produced_at: str | None = None
    checks: list[VerificationCheck] = Field(default_factory=list)


class ClinSigConcordanceInfo(BaseModel):
    """The clinical-significance concordance record's facets (format 0.7, RM130).

    **Three counters, and rendering only the first is the failure this block is shaped against.**
    `row_count` alone reads as confidence — *this module checked N subjects* — while what a reader
    needs is which way the check went. `opposed_count` is the disagreement that crosses the
    pathogenic/benign line, which is the finding worth acting on; `unchecked_count` is the subject an
    authority could not be consulted about, so the comparison is *incomplete* rather than clean. A
    shrinking record with a rising `unchecked_count` is a missing snapshot on the deployment that
    enriched it, not an improving module, and only the pair says which.

    That is this repo's sibling-field rule arriving in somebody else's block: a value two opposite
    histories can produce needs the field that says which happened. Both counters are carried for
    exactly that reason and neither is optional to render.

    **No consensus field, deliberately, and none is computed here.** Upstream omits one because
    resolving a split needs a weighting model the format does not have; inventing one at the catalog
    layer would publish a judgement as a fact. `authorities` says who was asked and the paired
    `clin_sig_authority_calls` table says what each of them answered — which authority spoke is data,
    never a rank.
    """

    row_count: int = Field(description="Contested subjects recorded, one per (variant_key, genotype)")
    call_count: int = Field(
        description=(
            "Rows in the paired per-authority detail table. Equal to `row_count` at one authority and "
            "higher above it, which is what makes the record's growth with N visible without counting"
        )
    )
    opposed_count: int = Field(
        description="Subjects where two calls sit in opposite camps rather than merely differing"
    )
    unchecked_count: int = Field(
        description=(
            "Subjects where an authority could not be consulted — incomplete, never clean. Read it "
            "beside `row_count`: a small record with a large value here checked almost nothing"
        )
    )
    authorities: list[str] = Field(
        default_factory=list, description="Who was consulted, sorted. Not a ranking"
    )
    datasets: list[str] = Field(
        default_factory=list, description="The authority releases the calls were read from"
    )
    concordance_states: list[str] = Field(
        default_factory=list, description="`authority_concordance` values present in the record"
    )
    authored_positions: list[str] = Field(
        default_factory=list, description="`authored_position` values present in the record"
    )


class FactTablesInfo(BaseModel):
    """Which derived fact tables a version carries, for the card and the search filters (0.6).

    Presence only — the counts and facets live on the detail, because a card is a grid cell and a
    reader scanning one wants "does this module carry GWAS effects at all", not 195. `weighting` is
    here for the same reason and is the odd one out in kind: it is authored rather than derived, and
    what it flags is that the module **said** what its weights mean.
    """

    gene_validity: bool = False
    clinical_assertions: bool = False
    gwas_effects: bool = False
    frequencies: bool = False
    weighting_declared: bool = False


class ModuleCard(BaseModel):
    """One entry in the list/search grid (SPEC §8.2)."""

    namespace: str
    name: str
    title: str
    description: str = Field(
        description="The **authored** subtitle, `module.description`, exactly as the spec carries it"
    )
    short_description: str | None = Field(
        default=None,
        description=(
            "The registry-held **override** of the subtitle a listing shows (format 0.7, RM133), at "
            "most 120 characters. `None` means the module has no override and a renderer shows "
            "`description` unchanged — which is not the same as an override set to the empty string, "
            "a deliberate blank. Held beside the module rather than in the spec so that amending it "
            "leaves `module_spec.yaml`'s bytes, and therefore `manifest.inputs`, `content_signature` "
            "and every closure over them, untouched. Render it as `short_description ?? description`"
        ),
    )
    icon: str
    icon_set: str = "fomantic"
    color: str
    logo_url: str | None = None  # served logo, when the module ships one; else fall back to icon
    latest_version: str | None
    genome_build: str
    license: str | None
    owner: str | None
    stats: CardStats
    downloads: int
    stars: int = 0
    views: int = 0
    created_at: str = ""  # first-publish time (distinct from updated_at)
    updated_at: str
    starred_by_me: bool = False  # true when the authenticated caller has starred this module
    featured: bool = False
    review_count: int = 0
    avg_rating: float | None = None  # mean 1-5 rating across reviews, None when unreviewed
    curated: bool = False  # has ≥1 owner-highlighted review/audit (the `curated` group)
    author_funding_url: str | None = None  # latest version's author's donation link
    org_funding_url: str | None = None  # owning org's donation link (when the namespace is org-owned)
    # Projected from the latest version's manifest, the same way `stats` is (0.11).
    resolution: ResolutionInfo = Field(default_factory=ResolutionInfo)
    licensing: LicensingInfo = Field(default_factory=LicensingInfo)
    # Which derived fact tables the latest version carries (0.6 adoption). Presence only; the
    # facets that decide whether the data is *usable* are on the detail, where there is room to
    # render them honestly.
    facts: FactTablesInfo = Field(default_factory=FactTablesInfo)


class VersionSummary(BaseModel):
    """One entry in a version list (SPEC §8.4)."""

    version: str
    artifact_digest: str
    content_signature: str | None = Field(
        default=None,
        description=(
            "The version's name-independent data identity — `manifest.content_signature`, the value "
            "`409 duplicate_content` is keyed on. Beside `artifact_digest` deliberately: the digest "
            "names the compiled **bytes** and moves whenever a recompile restamps a timestamp, while "
            "this moves only when the authored data does, so 'did the content change between these "
            "two versions' is the question only this one answers. Added in 0.19 (S14), so that "
            "question costs one list call rather than one manifest fetch per version. `null` for a "
            "pre-0.5 manifest that carries none."
        ),
    )
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
    """Module detail: card + readme + full versions + inline latest manifest (SPEC §8.3).

    The three 0.6 blocks are projected here rather than onto the card, and each for its own reason.
    `verification` is an unverifiable third-party claim that must never be sortable; `gwas_effects`
    needs `units` and `without_effect_allele` rendered beside its count or the count misleads; and
    `weighting` is free prose that a grid cell would have to truncate into something the author did
    not write. All three are projected from the **latest** version's manifest, exactly as `stats`,
    `resolution` and `licensing` already are, so they describe the same version the card does.
    """

    readme: str
    versions: list[VersionSummary]
    latest_manifest: ModuleManifest | None
    verification: VerificationInfo | None = None
    weighting: WeightingInfo | None = None
    clin_sig_concordance: ClinSigConcordanceInfo | None = None
    authority_precedence: list[str] = Field(
        default_factory=list,
        description=(
            "The authorities this module's curator weighted, most-trusted first (format 0.7, RM134) "
            "— served **verbatim and computed with nowhere**. Nothing in the format derives a verdict "
            "from it and neither does this service: the first entry is not a winner, and reading it "
            "as one beside `clin_sig_concordance` would resolve a split the format deliberately "
            "leaves open. Empty means the module has not said, which is not the same as saying the "
            "authorities weigh equally. Shown where `weighting` and `authorship` are shown, because "
            "it is the same kind of statement: what the curator brought to the module, in their words"
        ),
    )
    gwas_effects: GwasEffectsInfo | None = None


class Page[T](BaseModel):
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
    display_name: str | None = None
    avatar_url: str | None = None  # userpic (public http(s) URL)
    funding_url: str | None = None  # donation/sponsor link (public http(s) URL)
    email: str | None = None


# Account identity vocab + light checks (regex-based, to avoid an email-validator / URL dep).
VALID_ACCOUNT_TYPES: frozenset[str] = frozenset({"user", "org"})
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HTTP_URL_RE = re.compile(r"^https?://\S+$")


class ProfileUpdate(BaseModel):
    """Body for `PATCH /auth/whoami` — the account edits its own profile. Omitted fields are left
    unchanged; an empty string clears a field. `type` is not self-editable (admin/creation-time)."""

    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    funding_url: str | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        if v is None or v == "":  # "" clears the field
            return v
        if not _EMAIL_RE.match(v):
            raise ValueError("email must look like name@host.tld")
        return v

    @field_validator("avatar_url", "funding_url")
    @classmethod
    def _validate_http_url(cls, v: str | None) -> str | None:
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

    display_name: str | None = None
    avatar_url: str | None = None
    funding_url: str | None = None
    email: str | None = None

    @field_validator("avatar_url", "funding_url")
    @classmethod
    def _validate_http_url(cls, v: str | None) -> str | None:
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
    verdict: str | None = Field(
        default=None, description=f"Optional audit tier, one of {sorted(VALID_VERDICTS)}"
    )
    notes: str | None = Field(default=None, description="Free-text review/audit notes")

    @field_validator("verdict")
    @classmethod
    def _validate_verdict(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(VALID_VERDICTS)}")
        return v


class Review(BaseModel):
    """A published review/audit of a specific version."""

    reviewer: str = Field(description="Reviewer account name")
    version: str
    rating: int
    verdict: str | None = None
    notes: str | None = None
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
    module_name: str | None = None
    table_rows: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Rows per 0.4-family table CSV (`pharm_variants.csv`, `haplotypes.csv`, …). Separate from "
            "`variant_count`, which counts `variants.csv` only — a PGx module has thousands of rows "
            "and a `variant_count` of 0."
        ),
    )


class ValidationReport(BaseModel):
    """`POST /modules/{ns}/{name}/validate` — the offline half of a publish dry run."""

    valid: bool
    strict: bool = Field(description="The mode the findings were graded under")
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    carried: list[str] = Field(
        default_factory=list,
        description=(
            "The subset of `warnings` **no edit to the spec directory can clear** (format 0.7, "
            "RM131): a limit of the tier or a fact of a source. Subtract it from `warnings` to get "
            "what the author still owes. Empty is a real answer here — it means every finding is "
            "actionable, not that nothing was classified; `warnings_summary` beside it is what "
            "distinguishes the two, since an unclassified channel withholds both"
        ),
    )
    warnings_summary: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "`warnings` counted by kind, keyed on the format's closed `VALID_WARNING_CODES`. Either "
            "empty — this run did not classify the channel — or its values sum to `len(warnings)` "
            "and account for the whole of it. Never complete-looking and short. Count and branch on "
            "this rather than substring-matching a message: a code names the finding and survives a "
            "rewording, which the prose does not"
        ),
    )
    info: list[str] = Field(
        default_factory=list,
        description="Accepted but noteworthy: keys the server dropped, a version it coerced",
    )
    stats: SpecStats = Field(default_factory=SpecStats)
    format_version: str | None = Field(
        default=None,
        description=(
            "The `just-dna-format` version these findings were graded against — the row schema this "
            "instance holds, not the one the caller runs. Unconditional, because a refusal an author "
            "cannot date is a refusal they cannot act on (S18), and a `curl` caller has no response "
            "header in front of them. None only on a server too old to report it."
        ),
    )
    format_advisory: str | None = Field(
        default=None,
        description=(
            "Present when the caller advertised a *newer* `just-dna-format` than `format_version` "
            "within the same minor — a patch-grain skew, which is legal on the handshake and can "
            "still fail a spec, because a column added by a patch release is rejected by an older "
            "instance in the same words as a typo. Context, never a diagnosis of the errors beside "
            "it: it is derived from the two version strings alone and never from what failed. "
            "Requires the caller to send `X-Format-Version` (every `RegistryClient` does)."
        ),
    )
    content_signature: str | None = Field(
        default=None,
        description="Content identity of the authored rows; None when a data CSV will not parse",
    )
    name_matches_path: bool = Field(
        default=True, description="Whether the spec's module.name matches {name}; publish 422s if not"
    )
    published_as: list[VersionRef] = Field(
        default_factory=list,
        description=(
            "Every version already built from identical data, including earlier versions of **this** "
            "module. Informational: a hit here does not by itself predict a `409` — see "
            "`published_elsewhere`, which is the subset that does."
        ),
    )
    published_elsewhere: list[VersionRef] = Field(
        default_factory=list,
        description=(
            "The subset of `published_as` under a *different* `(namespace, name)` — what publish "
            "actually refuses with `409 duplicate_content` (0.16). A later version of the same "
            "module with unchanged data is allowed by the gate, which is what a review pass is: an "
            "`authorship` entry added, no data touched."
        ),
    )
    would_publish_module_level: bool = Field(
        default=False,
        description=(
            "The publish gates that do not scale with the variant count, composed into one field: "
            "the spec validates under `strict`, `module.name` matches the path, and the data is not "
            "already published under another `(namespace, name)`. **It is not `would_publish`.** It "
            "quantifies over the module-level gates only, so `true` means 'nothing here blocks a "
            "publish', never 'a publish would succeed' — the network tier can still refuse one on a "
            "reference mismatch or a withdrawn rsID, and only `/check` runs that tier."
        ),
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
    shift: int | None = None


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
    condition: str | None = None
    opposed: bool = Field(
        default=False, description="Opposed calls (pathogenic vs benign), not merely different"
    )
    confidence: str = Field(default="unrated", description="How much review backs ClinVar's side")


class StaleRsidEntry(BaseModel):
    """What dbSNP currently says about an authored rsID."""

    rsid: str
    state: str = Field(description="live | merged | absent | withdrawn")
    current: str | None = Field(default=None, description="The surviving rsID, when merged")
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
    complete: bool | None = Field(
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
    unreachable: list[str] = Field(
        default_factory=list,
        description=(
            "Sources that were asked and never answered — a 5xx, a timeout, a refused connection. "
            "Non-empty means every count and list beside it is *unchecked* rather than clean: this "
            "pass reached its upstream's error, not its data. A degradation of the report, never a "
            "finding about the module and never a publish gate"
        ),
    )
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
    titles_as_quotes: list[str] = Field(
        default_factory=list,
        description=(
            "PMIDs whose `provenance_quote` is the cited article's own title. A title appears in its "
            "own fulltext, so the quote check cannot fail on one: these PMIDs are counted in "
            "`quotes_found` while nothing about the claim has been grounded. A warning about the "
            "evidence, never a publish gate"
        ),
    )
    skipped_offline: bool = False
    unreachable: list[str] = Field(
        default_factory=list,
        description=(
            "Sources that were asked and never answered — a 5xx, a timeout, a refused connection. "
            "Non-empty means every count and list beside it is *unchecked* rather than clean: this "
            "pass reached its upstream's error, not its data. A degradation of the report, never a "
            "finding about the module and never a publish gate"
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Why the pass could not run — e.g. a PGx-only module carries no studies.csv",
    )


class AcmgCheck(BaseModel):
    """Authored `acmg_sf` flags against the ACMG secondary-findings list."""

    list_version: str | None = None
    checked: int = 0
    mismatches: list[str] = Field(default_factory=list)
    unverifiable: list[str] = Field(
        default_factory=list, description="The question could not be put — not a negative answer"
    )
    clean: bool = Field(
        default=True,
        description=(
            "No mismatch was found. Vacuous when nothing was checked — read `checked` and "
            "`unreachable` beside it. A plain bool rather than the tri-state `IdentifierCheck.clean` "
            "carries, because retyping a published field is a major"
        ),
    )
    unreachable: list[str] = Field(
        default_factory=list,
        description=(
            "The list could not be read: a 5xx, a timeout, or a page whose shape the scrape guards "
            "refuse — which is the same state as an outage for a reader, since either way no gene "
            "was compared. Non-empty makes `clean: true` vacuous. Never a publish gate"
        ),
    )
    warnings: list[str] = Field(default_factory=list)


class FunctionConflictEntry(BaseModel):
    """An authored allele function a nomenclature authority does not support."""

    gene: str
    allele: str
    authored: str | None = None
    reported: str | None = None
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
    unreachable: list[str] = Field(
        default_factory=list,
        description=(
            "Legs asked that never answered. Per source rather than per pass, because the four run "
            "independently and one upstream's outage must not be read as silence from the other "
            "three — nor discard their findings. Distinct from `skipped` (a licensing refusal, "
            "nothing was asked) and from a `warning` (the source answered and something was odd)"
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
    gene_loci: list[str] = Field(
        default_factory=list,
        description=(
            "Rows whose `gene` names a chromosome the row's own variant is not on (enricher 0.5.4 / "
            "S24). A different question from `stale_genes`, which only asks whether HGNC approves the "
            "symbol: here both halves are individually true and the *relationship* is false — the "
            "signature of a machine-written citation, a real symbol beside an invented rsID that "
            "resolves anyway because dbSNP is dense enough that almost any number hits something. "
            "Chromosome granularity only, so a row naming a distal regulatory target is not accused"
        ),
    )
    gene_loci_not_checked: str | None = Field(
        default=None,
        description=(
            "Why the comparison above did not run, or null when it did. Read it before believing an "
            "empty `gene_loci`: HGNC may have returned no usable chromosome, or no row may have a "
            "known one. Same contract as `EnrichmentReport.clin_sig_not_checked`"
        ),
    )
    unreachable: list[str] = Field(
        default_factory=list,
        description=(
            "Sources that were asked and never answered — a 5xx, a timeout, a refused connection. "
            "Non-empty means every count and list beside it is *unchecked* rather than clean: this "
            "pass reached its upstream's error, not its data. A degradation of the report, never a "
            "finding about the module and never a publish gate"
        ),
    )
    clean: bool | None = Field(
        default=None,
        description=(
            "`null` when nothing was checked — clean out of zero identifiers says nothing. Folds in "
            "`gene_loci`, so a gene/variant contradiction makes it false"
        ),
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
    unreachable_rsids: list[str] = Field(
        default_factory=list,
        description=(
            "rsIDs live Ensembl could not be *asked* about — the request failed — so their absence is "
            "unchecked rather than established (enricher 0.5.4 / S20). A subset of the reasons behind "
            "`unresolved`, which is silent about why a key has no position: a row nothing could be "
            "asked about and a row Ensembl genuinely has no locus for look identical there, and only "
            "one of them may resolve on a re-run. Always empty offline, where nothing was asked at "
            "all. It does not soften `would_publish`: under `?strict=true` an unresolved key still "
            "refuses, because the publish really would refuse — but this says the refusal may be "
            "transient and worth re-running rather than an authoring defect to go fix"
        ),
    )
    ref_mismatches: list[RefMismatchEntry] = Field(default_factory=list)
    clin_sig_conflicts: list[ClinSigConflictEntry] = Field(default_factory=list)
    #: Read this **before** believing an empty `clin_sig_conflicts` (enricher 0.5.2 / S4).
    clin_sig_not_checked: str | None = Field(
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
    frequencies: FrequencyCheck | None = None
    literature: LiteratureCheck | None = None
    identifiers: IdentifierCheck | None = None
    acmg: AcmgCheck | None = None
    pgx: PgxCheck | None = None


class CheckReport(BaseModel):
    """`POST /modules/{ns}/{name}/check` — the full publish dry run."""

    validation: ValidationReport
    enrichment: EnrichmentReport | None = None
    skipped_reason: str | None = Field(
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

    digest: str | None = None
    signature: str | None = None
    matches: list[VersionRef] = Field(default_factory=list)


class LookupBatchResponse(BaseModel):
    results: list[LookupMatch] = Field(default_factory=list)


class CacheLaneStatus(BaseModel):
    """One snapshot lane as `GET /caches` reports it — `services/enrich.lane_status()` builds these.

    Every field is derived from upstream's own `CacheLane` registry (`caches.CACHE_LANES`, RM176) or
    from a predicate `prepare_lane` already uses. Nothing here is a list kept by hand: that is what
    the registry replaced, and ours had drifted by eight lanes when it was one.

    **No filesystem path appears on this model, and none may be added.** Lane *presence* is already
    inferable from `/check`'s skip reasons one pass at a time, so the state is not new information;
    the server's directory layout is, and it is the half an anonymous reader has no business with.
    `configured` carries the operator-actionable part of what a path would have said — whether this
    deployment pinned the location or is letting the lane's own ladder find it.
    """

    name: str = Field(description="The lane's name in the enricher's registry, e.g. `clinvar`")
    serves: str = Field(description="What this snapshot is for, in the lane's own words")
    #: `present` / `partial` / `absent`. **`partial` is not a nicety** — it is a directory holding
    #: something that is not a readable snapshot (a build that died after its downloads, a payload
    #: deleted beside its `release.json`, a stray `.part`), and it is the one state where
    #: provisioning refuses to act rather than overwriting. Folding it into `absent` would send an
    #: operator to run a pull that will not fix it.
    state: str = Field(description="present | partial | absent")
    release: str | None = Field(
        default=None,
        description=(
            "Which release the snapshot on disk holds, as its own `release.json` states it. `null` "
            "means the snapshot does not say — never a placeholder, because a caller has to be able "
            "to tell a release from a snapshot that cannot name one."
        ),
    )
    release_unreadable: bool = Field(
        default=False,
        description=(
            "A `release.json` is present and could not be parsed. The snapshot is still usable, so "
            "this is reported beside `state: present` rather than downgrading it — a provenance "
            "failure is not a data failure."
        ),
    )
    route: str = Field(
        description=(
            "How this lane would arrive: `pullable` (published, download it), `buildable` (nothing "
            "publishes it, build it here) or `none`. Read from the lane's `ensure` and `rebuild` "
            "stages independently — never inferred from one, since a lane can have an `ensure` and "
            "no `rebuild` for an acquisition reason rather than a division of labour."
        )
    )
    route_reason: str | None = Field(
        default=None,
        description=(
            "Why a stage is missing, in the sentence upstream recorded beside the lane "
            "(`unpublished` / `unbuilt`) — a personal key, terms nobody publishes, a permission "
            "never established, or a snapshot another tier cuts. Never a sentence written here."
        ),
    )
    build_command: str | None = Field(
        default=None,
        description=(
            "The command that builds this lane, as an operator types it. Carried on the lane rather "
            "than composed from its name: two lanes are not `<name> build`, and composing printed "
            "commands that do not exist."
        ),
    )
    licence_gated: bool = Field(
        default=False,
        description="Acquiring this lane applies `declared_use`, because its source restricts use",
    )
    licence_skip: str | None = Field(
        default=None,
        description=(
            "Why this deployment's `declared_use` would decline to acquire the lane, if it would. "
            "A lane sitting absent behind this will never arrive from a pull no matter how often "
            "one is run, which is a different instruction to an operator from `not provisioned`."
        ),
    )
    read_here: bool = Field(
        default=False,
        description=(
            "Whether a pass in *this service* opens the lane. Deliberately narrower than the set of "
            "lanes an operator can provision: the same box often runs authoring commands, and a "
            "lane nothing here reads is still worth reporting rather than hiding."
        ),
    )
    group: str | None = Field(
        default=None,
        description="Which group of passes reads it here (`resolution`, `pgx`, …); null if none do",
    )
    configured: bool = Field(
        default=False,
        description=(
            "Whether this deployment pins the lane's location, as opposed to letting the enricher's "
            "own ladder find it. Not the path itself — see the class docstring."
        ),
    )
    parents: list[str] = Field(
        default_factory=list,
        description=(
            "Lanes this one is derived from. Empty for every lane that acquires its own bytes, "
            "which is all but one — and the field an operator asking why an increment is empty needs."
        ),
    )


class CacheStatusReport(BaseModel):
    """`GET /caches` — which snapshots this deployment holds, and for the rest, why not.

    Anonymous, and the licence for that is the same one `/health` already runs on: it publishes the
    enrichment gate's occupancy unauthenticated, and lane state is the same class of operational fact
    about the box. Note that *"a caller could already enumerate this through `/check`"* is **not** the
    argument — `/check` requires the `PUBLISH` capability and an anonymous caller has none. If
    `/health` ever stops reporting operational state, this endpoint's licence goes with it.
    """

    enricher_available: bool = Field(
        description=(
            "Whether the network tier is installed at all. `false` makes every lane `absent` with no "
            "route, which is a deployment fact rather than fourteen separate failures."
        )
    )
    declared_use: str = Field(
        description="The deployment's declared use, which is what `licence_skip` is computed against"
    )
    lanes: list[CacheLaneStatus] = Field(default_factory=list)


class HintCost(BaseModel):
    """What one hint spent, where it was answered from, and whether a limit shaped the answer.

    **`charged` is reported even when it is empty**, and that is the field this whole surface exists
    to teach: an `offline=true` answer costs the deployment nothing. Without it a caller has no way to
    learn which of their traffic is free — and "you are being throttled" has two opposite histories,
    spent egress or a plain request bucket, with opposite remedies.
    """

    charged: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Units committed per upstream. Charged from the *shape* of the request rather than "
            "measured, because nothing downstream reports what it actually spent — so it is an upper "
            "bound, and a request served entirely from a snapshot charges nothing at all."
        ),
    )
    served_from: list[str] = Field(
        default_factory=list,
        description=(
            "Which snapshots or live sources answered, by lane name. Never a filesystem path: the "
            "enricher records the snapshot's location here and it is mapped back to the lane."
        ),
    )
    limit: str | None = Field(
        default=None,
        description=(
            "`pace` when the per-upstream ledger slowed this answer, `bucket` when the request "
            "limiter did, null when nothing did. The sibling that tells those two apart — the "
            "remedies are opposite and 'you are being throttled' cannot distinguish them."
        ),
    )
    waited_seconds: float = Field(
        default=0.0, description="Seconds this request was held to keep the caller inside its pace"
    )
    remedy: str | None = Field(
        default=None,
        description=(
            "What to do about it, per upstream reached, and only past the free tier. It is never "
            "'obtain an API key' where no key exists — gnomAD sells none at any price, NCBI's paces "
            "whoever holds it, OLS4 and HGNC issue none."
        ),
    )


class VariantHintReport(BaseModel):
    """`GET /hint/variant` — what is known about one variant, and what of it is the author's to type.

    Nothing here is written anywhere and nothing is decided: a one-to-many rsID returns every locus
    rather than picking one, and a position matching several rsIDs returns every candidate. Every
    entry in `alterations` carries `applied: false` and a `refusal`, because almost every fact here
    is cross-examined later by a check that only works if the author wrote the value independently.
    """

    rsid: str | None = None
    rsid_state: str | None = Field(
        default=None, description="dbSNP merge status: live, merged, withdrawn, unchecked"
    )
    rsid_current: str | None = Field(
        default=None, description="The id this one was merged into — reported, never written"
    )
    loci: list[dict] = Field(default_factory=list)
    rsid_candidates: list[str] = Field(default_factory=list)
    populations: list[dict] = Field(default_factory=list)
    clin_sig: list[dict] = Field(default_factory=list)
    vrs_id: str | None = None
    ambiguous: bool = Field(
        default=False, description="More than one locus or rsID candidate — the author must choose"
    )
    findings: list[dict] = Field(default_factory=list)
    alterations: list[dict] = Field(default_factory=list)
    cost: HintCost = Field(default_factory=HintCost)


class CitationHintReport(BaseModel):
    """`GET /hint/citation` — does this citation exist, and what is its other identifier?

    **Existence is not identity.** PMIDs are densely allocated, so a recalled or invented number is
    very likely to be a real record for a different paper, and `pmid_exists` alone cannot catch a
    fabrication. The bibliographic fields arrive in the same response that answers existence, so
    naming the paper costs nothing and is the only thing that makes the answer checkable.
    """

    pmid: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    pmid_exists: bool | None = None
    doi_exists: bool | None = None
    registry_doi: str | None = None
    open_access: bool | None = None
    abstract_available: bool | None = None
    title: str | None = None
    journal: str | None = None
    year: str | None = None
    first_author: str | None = None
    findings: list[dict] = Field(default_factory=list)
    alterations: list[dict] = Field(default_factory=list)
    cost: HintCost = Field(default_factory=HintCost)


class GeneHintReport(BaseModel):
    """`GET /hint/gene` — is this gene symbol approved or retired? HGNC exact, never fuzzy search."""

    symbol: str | None = None
    state: str | None = None
    current: str | None = None
    hgnc_id: str | None = None
    location: str | None = None
    cost: HintCost = Field(default_factory=HintCost)


class TraitHintReport(BaseModel):
    """`GET /hint/trait` — is this trait CURIE current, obsolete or unknown? (OLS4.)"""

    curie: str | None = None
    state: str | None = None
    label: str | None = None
    replaced_by: str | None = None
    cost: HintCost = Field(default_factory=HintCost)


class OldAssemblyHintReport(BaseModel):
    """`GET /hint/old-assembly` — an hg19 coordinate to an rs-number. Recovery, never liftover.

    An rs-number authored into `variants.csv` resolves through the ordinary chain into a coordinate a
    later check can cross-examine. A lifted-over position becomes the row's sole identity with nothing
    to check it against, which is an unverifiable-by-construction identity — so candidates are
    reported and never written, and never picked when there is more than one.
    """

    chrom: str | None = None
    start: int | None = None
    outcome: str | None = None
    ref: str | None = None
    alts: str | None = None
    rsids: list[str] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    note: str | None = None
    findings: list[dict] = Field(default_factory=list)
    alterations: list[dict] = Field(default_factory=list)
    cost: HintCost = Field(default_factory=HintCost)


class VariantKey(BaseModel):
    """One variant to resolve in a batch: an rsID, a coordinate, or both."""

    rsid: str | None = None
    chrom: str | None = None
    start: int | None = None
    ref: str | None = None
    alts: str | None = None


class VariantHintBatch(BaseModel):
    """Body for `POST /hint/variants`."""

    keys: list[VariantKey] = Field(default_factory=list)


class VariantHintBatchResponse(BaseModel):
    """`POST /hint/variants` — snapshot first for every key, live only for what missed.

    The per-key `cost.charged` is where the caching proxy becomes visible: on a provisioned
    deployment a whole module's worth of keys comes back charging nothing, because the snapshot
    answered and only a miss costs anything.
    """

    results: list[VariantHintReport] = Field(default_factory=list)
    total_charged: dict[str, int] = Field(
        default_factory=dict, description="Units committed across the batch, per upstream"
    )
    cost: HintCost = Field(
        default_factory=HintCost,
        description=(
            "The batch's own meter result — what it waited and why, and the remedy if it was paced. "
            "Per-key `charged` says which keys cost anything; this says what the batch as a whole "
            "was held to."
        ),
    )
