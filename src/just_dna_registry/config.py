"""
Service configuration (Pydantic settings).

Loads `.env` before reading the environment (per project rules). All runtime knobs live here;
nothing is hardcoded elsewhere.
"""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

API_PREFIX: str = "/api/v1"


class Settings(BaseSettings):
    """Registry settings, overridable via `REGISTRY_*` env vars or `.env`."""

    # `populate_by_name` so a field with a `validation_alias` can still be set by its own name.
    # Without it `Settings(hf_token=...)` / `Settings(pharmvar_api_key=...)` bind nothing and fall
    # back to the default — silently, which is how a test can "configure" a credential and assert
    # against a `None` it never noticed.
    model_config = SettingsConfigDict(
        env_prefix="REGISTRY_", extra="ignore", populate_by_name=True
    )

    # Catalog DB (SQLite for MVP; the DB is a projection of manifest.json).
    db_path: Path = Path("data/registry.db")

    # Artifact storage. `local` is the dev/test backend; `hf` (HuggingFace Hub) is the
    # production backend and is wired in a later milestone.
    storage_backend: str = "local"
    local_storage_dir: Path = Path("data/artifacts")
    hf_repo_id: str = "just-dna-seq/registry"
    # HF write token used by the (pending) HfStorage backend to manage the dataset repo. Reads
    # REGISTRY_HF_TOKEN first, then the conventional HF_TOKEN that huggingface_hub itself uses.
    hf_token: str | None = Field(
        default=None, validation_alias=AliasChoices("REGISTRY_HF_TOKEN", "HF_TOKEN")
    )

    # Server-side recompile (M4) pins one Ensembl reference across the ecosystem.
    ensembl_reference: str = "just-dna-seq/ensembl_variations"

    # --- Compile policy (format/compiler 0.5) -------------------------------------------------
    # `strict` is the compiler's all-or-nothing mode: it refuses to emit a partial artifact when
    # resolution left a variant without a position, and escalates a ladder of checks from warning to
    # error. The format's own guidance is that a publishing registry passes it, and that is what
    # makes `compiled_by="marketplace-server"` worth trusting — so it is on. It stays a setting
    # because turning it off is the escape hatch during a catalog migration: run
    # `registry revalidate --recompile-check` to see what a corpus would lose, fix or notify, then
    # turn it back on.
    compile_strict: bool = True
    # ACMG BA1 lint threshold (allele frequency above which a "pathogenic" claim is suspect).
    # Warning-only in both modes, so this tunes noise and never whether a publish succeeds.
    ba1_threshold: float = 0.05

    # --- Enrichment (just-dna-enricher — the only tier permitted to fetch) ---------------------
    # The enricher produces `resolution.csv` (rsid -> coordinate, VRS ids, reference-allele check),
    # which the compiler then consumes. It runs BEFORE the compile and as a separate step, never
    # from inside it: `compile_module`'s own `ensembl_cache=` shim reaches into the enricher from
    # within the compile path, which CONSTITUTION Principle 2 forbids and which is deprecated
    # upstream for removal at 1.0. We do not use it.
    enrich_enabled: bool = True
    # Always `best_effort`, and this is load-bearing rather than timid: `enrich(mode="strict")`
    # raises BEFORE it writes `resolution.csv`, so a strict failure leaves no table at all — nothing
    # to diagnose from, and a re-run repeats the whole network pass. Letting the compiler's strict
    # gate do the refusing keeps the table on disk and names the offending variants.
    enrich_mode: str = "best_effort"
    # Offline by default on the publish path. Three reasons: an online enrich holds a threadpool
    # worker for minutes; it makes `artifact.digest` a function of *when* you published; and it
    # turns publish into an egress surface driven by caller-supplied identifiers.
    enrich_offline: bool = True
    # Never provision a multi-hundred-MB snapshot from inside a request. `registry warm-caches`
    # is the operator step that does it.
    enrich_download: bool = False
    # Refuse to boot when enrichment is on, offline, and no snapshot is provisioned. In that state
    # every strict publish of an rsID module fails, and that should not be discovered one 422 at a
    # time. Off by default so a fresh dev checkout still starts.
    enrich_require_cache: bool = False
    enrich_use_clinvar: bool = True
    # gnomAD is paced at ~6s per 20 variants and is only reachable online; off by default so the
    # publish path cannot accidentally spend minutes on it.
    enrich_use_gnomad: bool = False
    enrich_mint_vrs: bool = True
    enrich_verify_ref: bool = True  # auto-skipped offline (needs the reference sequence)
    enrich_verify_clinsig: bool = True  # warning-only in both modes, by upstream design
    enrich_verify_rsids: bool = False  # live dbSNP only
    enrich_keep_par_twin: bool = False  # record a pseudoautosomal locus once, on X

    # Reference snapshot caches. ALWAYS passed explicitly to the enricher: with no path its
    # `resolve_*_reference()` helpers fall through to $JUST_DNA_ENSEMBL_CACHE /
    # $JUST_DNA_PIPELINES_CACHE_DIR / a platformdirs default, which would make CI and production
    # disagree about whether enrichment is even available. `None` here still means "not configured",
    # and the enricher's own env fallbacks are then what a just-dna-lite deployment reuses.
    # Resolution + fact snapshots: what a strict publish depends on.
    ensembl_cache: Path | None = None
    clinvar_cache: Path | None = None
    constraint_cache: Path | None = None
    # The licence-gated PGx snapshots (enricher 0.5.1 / RM38). Only the `?pgx=` check reads these, so
    # a deployment that never uses it needs none of them — but a *hosted* one that does needs all
    # three, because the alternative is fetching a gated source live, per request, on the operator's
    # own acceptance and (for PharmVar) their personal key, while every published rate figure for
    # them is per IP. `registry warm-caches` provisions cpic and clinpgx; PharmVar is build-only by
    # upstream design — its bulk data comes down under a non-transferable key, so nothing is
    # published to pull and there is no `ensure_pharmvar_snapshot`. Build it once with
    # `just-dna-enricher pharmvar build --out <dir>` and point this at the result.
    cpic_cache: Path | None = None
    pharmvar_cache: Path | None = None
    clinpgx_cache: Path | None = None
    acmg_snapshot_dir: Path | None = None

    # Declared use — a THIRD axis, orthogonal to strict/offline (format Principle 5). `mode` says how
    # hard to fail on a finding; this says who is using the data and why, and it is checked at
    # *acquisition*, because under a data-usage policy that is when the terms are accepted.
    #
    # Three states, not a bool, because a bool cannot express the default and defaulting either way
    # would have the registry assert a purpose on a publisher's behalf:
    #   unstated (default) — a source that forbids sale is SKIPPED, with a reason
    #   non_commercial     — it is fetched and the declaration recorded
    #   commercial         — it is REFUSED, and nothing is fetched
    # "Unknown terms" is skipped in every column: not having established the terms is not permission.
    #
    # Only the annotation-layer passes consult it (`pgx`, `clinpgx`, ClinGen dosage) — every PGx
    # upstream is CC BY-SA *plus* a no-sale clause. Resolution, frequency and gene-metrics never have
    # to ask, since none of those sources forbids sale; they record attribution instead.
    declared_use: str = "unstated"


    # Enrichment cost control. The per-caller token bucket below caps ONE caller; these cap the
    # process, which is the only thing that bounds our outbound rate. The upstreams are
    # unauthenticated and throttle by IP — gnomAD publishes a 10-per-60s budget and offers no API key
    # at any price — so exceeding it gets THIS SERVER throttled, for every user at once.
    # `enrich_max_concurrency > 1` also races the enricher's `PacingGate` (a plain dataclass with no
    # lock) and multiplies our egress rate against gnomAD's stated budget — raise it deliberately.
    enrich_max_concurrency: int = 1
    # `/check` only. Publish is deliberately NOT bounded by this: it is unattended, it has already
    # been queued behind every interactive caller, and a deadline on it would convert a slow upstream
    # into a lost upload. See `enrich_idle_*` below.
    enrich_timeout_seconds: float = 300
    # Refuse an enrichment dry run over a module this large before spending anything on it:
    # 500 / 20 * 6s is already ~150s of pure pacing for the frequency pass. `/check` only, for the
    # same reason as the timeout — and because publish never runs the frequency pass, which is the
    # expensive one this bound is really about.
    enrich_max_variants: int = 500

    # --- The idle lane: how publish yields to `/check` -------------------------------------------
    # Publish queues for an enrichment permit instead of failing on a full gate, and while queued it
    # costs an event-loop task rather than a threadpool worker — which is the concession that
    # actually matters, since that pool is what an interactive request needs in order to run.
    #
    # How long the gate must be free of interactive *demand* before a queued publish may start. Short
    # on purpose: this stops a publish winning a race against a `/check` that arrived in the same
    # moment, it is not a "wait for a quiet hour" policy. A rejected `/check` counts as demand.
    enrich_idle_quiet_seconds: float = 5.0
    enrich_idle_poll_seconds: float = 0.5
    # Nice increment for the publish worker thread (0 disables). Applies to the compile half, which
    # is real CPU; the enrichment half is mostly paced sleeping and gains nothing either way. The
    # thread is created per publish and discarded, because raising a nice value is unprivileged and
    # LOWERING IT BACK IS NOT — a reused worker could never be restored. See `lowpriority.py`.
    publish_nice: int = 10

    # Outbound retry floor, exported to the enricher as `JUST_DNA_HTTP_RETRY_ATTEMPTS` (0.5.1 / RM42).
    # Its clients already retry — tenacity, exponential jitter, and paced *before* the retry, so an
    # extra attempt spends a budget slot rather than bursting past it — but their own 3-4 attempts are
    # tuned for an author at a terminal who would rather see the failure. A server publish is
    # unattended and a transient 502 costs a whole re-upload. Upstream treats this as a FLOOR: gnomAD
    # and eutils keep their higher defaults, and a value below a client's own is a no-op.
    http_retry_attempts: int = 5

    # Upload bounds, applied to every multipart spec upload (publish, import, validate, check).
    max_upload_bytes: int = 25 * 1024 * 1024
    max_spec_files: int = 64

    # Politeness credentials for the enricher's NCBI / Europe PMC calls. Both OPTIONAL: the key only
    # *tightens* NCBI pacing (1 request per 3s → 1 per 0.1s) and the email is the polite-pool contact.
    # Neither applies to gnomAD, which has no authentication of any kind — its limit is enforced on
    # our IP and cannot be raised. (PharmVar is the one credential that gates a leg rather than just
    # tightening its pacing — see `pharmvar_api_key` below.) The enricher reads these from the
    # process environment at client construction rather than taking parameters, so `startup.py`
    # exports them (without overwriting anything already set).
    ncbi_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("REGISTRY_NCBI_API_KEY", "NCBI_API_KEY")
    )
    # PharmVar, unlike the two above, is a REQUIRED credential for the leg that uses it — and unlike
    # gnomAD/CPIC/NCBI it is tied to a person: PharmVar's terms §2 make an account non-transferable,
    # which is why the enricher keeps the key in a request header and never writes it to a module,
    # fixture, log or snapshot. Setting it here enables the PharmVar half of the `?pgx=` check;
    # leaving it unset disables that half and leaves CPIC (open, keyless) doing the work. There is no
    # separate on/off switch — presence of the key *is* the switch.
    #
    # Operator note: on a PUBLIC deployment this means third parties query PharmVar on your account.
    pharmvar_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REGISTRY_PHARMVAR_API_KEY", "PHARMVAR_API_KEY"),
    )
    contact_email: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REGISTRY_CONTACT_EMAIL", "JUST_DNA_CONTACT_EMAIL"),
    )

    # Pagination.
    default_per_page: int = 20
    max_per_page: int = 100

    # Community self-service onboarding (0.3). Accounts register with an install-id (proof-of-work,
    # see installid.py) and may claim up to `namespaces_per_account` namespaces. Community-first:
    # self-register is on by default; the install-id PoW deters random spambots, not determined ones.
    allow_self_register: bool = True
    install_id_difficulty: int = 20
    namespaces_per_account: int = 5
    lookup_batch_max: int = 256  # cap on digests per batch /modules/lookup

    # Rate limiting (SPEC §7), per caller (API key or IP) × category. In-memory token buckets.
    rate_limit_enabled: bool = True
    rate_publish_per_hour: float = 10
    rate_download_per_hour: float = 1000
    rate_search_per_min: float = 60
    rate_social_per_min: float = 30  # star/unstar toggles (0.6.0)
    # Pre-flight (0.11). `validate` is server CPU only — cheaper than a publish, hence a looser
    # bucket, but not free: it runs the real compiler over arbitrary uploaded CSVs. `enrich` spends
    # the deployment's shared standing with IP-throttled upstreams, plus minutes of pacing, so it is
    # the tightest bucket in the service.
    rate_validate_per_hour: float = 60
    rate_enrich_per_hour: float = 5

    # Listing groups (0.8.0). Namespaces whose name matches this regex are classified as
    # "test/sandbox" — surfaced only under `?group=test` and hidden from every other tab (`all`,
    # `featured`, `popular`, `new`). Server-owned policy (not a client-supplied regex) so all
    # consumers agree on membership; namespace names are hyphen-delimited (identity rules).
    test_namespace_pattern: str = r"^(sandbox|test)([-_]|$)"

    # Optional Ed25519 artifact signing (SPEC §5). When `signing_key` points at an Ed25519 private
    # key PEM, the server signs each published version's `artifact.digest` and the public key is
    # served at `GET /api/v1/pubkey` for clients to pin. Unset (default) → signing off, unsigned
    # manifests (0.4 behaviour unchanged).
    signing_key: Path | None = None

    # Optional JWT sessions (backwards-compatible). Static API keys always work; if `jwt_secret`
    # is set, POST /auth/tokens exchanges a key for a short-lived JWT that's also accepted as a
    # bearer. Unset (default) → JWT disabled, static-keys-only (0.4 behaviour unchanged).
    jwt_secret: str | None = None  # use ≥32 bytes (HS256); unset = JWT off
    jwt_ttl_seconds: int = 86400

    # Observability. `debug` turns on verbose structured logging to stdout (request tracing +
    # Eliot publish/import step logs + third-party DEBUG). Off = `log_level` (default INFO).
    debug: bool = False
    log_level: str = "INFO"


    @field_validator("declared_use")
    @classmethod
    def _validate_declared_use(cls, v: str) -> str:
        from just_dna_format.vocab import VALID_DECLARED_USE

        if v not in VALID_DECLARED_USE:
            raise ValueError(f"declared_use must be one of {sorted(VALID_DECLARED_USE)}, got: {v!r}")
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
