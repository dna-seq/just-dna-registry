"""
Startup guards. Fail fast (exit 1) on misconfiguration that would otherwise surface only at the
first publish — most importantly, a missing / read-only HuggingFace token when the HF storage
backend is selected, and (0.11) a missing reference snapshot when enrichment is on and offline.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from just_dna_registry.config import Settings

logger = logging.getLogger("registry.startup")

# Settings that existed once, were read from the environment, and are now gone. `Settings` is
# `extra="ignore"`, so a stale entry in a deployment's `.env` is swallowed in silence while the
# operator believes it still does something — which for this one would mean believing resolution is
# disabled when it is not.
_OBSOLETE_ENV: dict[str, str] = {
    "REGISTRY_RESOLVE_WITH_ENSEMBL": (
        "removed in 0.11 — resolution is no longer optional. The enricher produces resolution.csv "
        "before the compile and the compiler always consumes it. Use REGISTRY_ENRICH_ENABLED to "
        "turn the enrichment step off, and REGISTRY_COMPILE_STRICT to control whether an "
        "unresolved variant fails the publish."
    ),
}


def legacy_db_message(db_path: Path) -> Optional[str]:
    """The 0.9 rename moved the default DB path `data/marketplace.db` → `data/registry.db`. If the
    configured DB is absent but a non-empty legacy `marketplace.db` sits beside it, return an
    actionable message (else None) — so we never silently create/serve an empty catalog after upgrade."""
    if db_path.exists():
        return None
    legacy = db_path.with_name("marketplace.db")
    if legacy.exists() and legacy.stat().st_size > 0:
        return (
            f"No DB at {db_path.resolve()}, but a legacy {legacy.resolve()} exists — 0.9 renamed "
            f"the default DB path (marketplace.db → registry.db). Adopt it with "
            f"`mv {legacy} {db_path}`, or set REGISTRY_DB_PATH={legacy}."
        )
    return None


def validate_db_path(settings: Settings) -> None:
    """Refuse to start on the 0.9 rename orphan (a legacy `marketplace.db` with no `registry.db`),
    rather than silently booting an empty catalog. No-op once the DB exists at the configured path."""
    message = legacy_db_message(settings.db_path)
    if message is not None:
        logger.error(message)
        sys.exit(1)


def warn_obsolete_env() -> None:
    """Warn about env vars that no longer do anything, so a stale `.env` cannot mislead silently."""
    for name, reason in _OBSOLETE_ENV.items():
        if name in os.environ:
            logger.warning("%s is set but ignored: %s", name, reason)


def export_enricher_credentials(settings: Settings) -> None:
    """Publish the enricher's politeness credentials into the process environment.

    `just-dna-enricher` reads these from `os.environ` when it constructs a client rather than taking
    them as parameters, so configuring them through `Settings` means putting them back. Never
    overwrite an already-set value: an operator who exported one directly wins over one who wrote it
    into the registry's `.env`.

    **A consequence to know before writing a test against any of these.** `api/app.py` ends with a
    module-level `app = create_app()` — the conventional ASGI entrypoint uvicorn imports — so merely
    importing that module builds an app from ambient `get_settings()` and runs this. A later
    `create_app(Settings(http_retry_attempts=7))` in the same process therefore cannot move
    `JUST_DNA_HTTP_RETRY_ATTEMPTS`: the first export already set it, and this function does not
    clobber. In production that is a distinction without a difference, since both readings come from
    the same environment. In a test it means these are **process-wide, first-write-wins**, not
    per-app — so assert them in a subprocess or not at all.
    """
    for name, value in (
        ("NCBI_API_KEY", settings.ncbi_api_key),
        ("JUST_DNA_CONTACT_EMAIL", settings.contact_email),
        ("PHARMVAR_API_KEY", settings.pharmvar_api_key),
        # `huggingface_hub` reads `HF_TOKEN` from the environment and knows nothing of our prefix, so
        # an operator who set only `REGISTRY_HF_TOKEN` had a perfectly good token the snapshot
        # downloader could not see. That is not merely slower: the two **licence-gated** PGx mirrors
        # are private, so an anonymous pull gets 401 rather than a rate limit, and for the public
        # three anonymous traffic shares a per-IP pool and is the usual cause of a "stuck" download.
        ("HF_TOKEN", settings.hf_token),
        # The outbound retry floor (enricher 0.5.1 / RM42). Read per call by `net.retry_attempts`,
        # which treats it as a floor — gnomAD and eutils keep their higher own defaults, and a value
        # below a client's own is a no-op. Through 0.11 the registry got this by walking the package
        # at boot and assigning `policy.stop` on tenacity's objects; a settings-shaped knob is what
        # the RM asked for and `src/just_dna_registry/retries.py` is deleted.
        ("JUST_DNA_HTTP_RETRY_ATTEMPTS", str(settings.http_retry_attempts)),
    ):
        if value and name not in os.environ:
            os.environ[name] = value


def validate_enrichment_caches(settings: Settings) -> None:
    """Check that offline enrichment has something to work with.

    With `enrich_enabled` and `enrich_offline` and no provisioned snapshot, the enricher resolves
    nothing, so every strict publish of an rsID-authored module fails on unresolved positions. That
    is a deployment mistake, not a per-request one, and discovering it one 422 at a time is the
    worst way to find out. Warn always; exit only when the operator asked us to
    (`enrich_require_cache`), so a fresh dev checkout still starts.

    **Only the resolution snapshots are checked here.** The reference set doubled in enricher 0.5.1,
    but the three PGx caches gate the opt-in `?pgx=` check rather than publishing, so folding them in
    would greet every deployment that never asks for that check with three boot warnings about
    caches it does not need — and would put them behind `enrich_require_cache`, i.e. make a hosted
    PGx snapshot a condition of starting the server. `registry warm-caches` reports all six.
    """
    if not (settings.enrich_enabled and settings.enrich_offline):
        return

    from just_dna_registry.services.enrich import (
        RESOLUTION_REFERENCES,
        available_references,
        enricher_available,
    )

    if not enricher_available():
        logger.warning(
            "enrichment is enabled but just-dna-enricher is not installed — install the `server` "
            "extra (`uv sync --extra server`). Until then no resolution.csv is produced, and with "
            "REGISTRY_COMPILE_STRICT on, publishing an rsID-authored module will fail."
        )
        return

    present = available_references(settings)
    missing = [name for name in RESOLUTION_REFERENCES if present[name] is None]
    if not missing:
        return

    message = (
        f"enrichment is offline and these reference snapshots are not provisioned: "
        f"{', '.join(missing)}. Run `registry warm-caches --apply` (or point "
        f"REGISTRY_ENSEMBL_CACHE / REGISTRY_CLINVAR_CACHE / REGISTRY_CONSTRAINT_CACHE at existing "
        f"ones). Without them the enricher resolves nothing and strict publishes of rsID-authored "
        f"modules will fail."
    )
    if settings.enrich_require_cache:
        logger.error(message)
        sys.exit(1)
    logger.warning(message)


def validate_hf_access(settings: Settings) -> None:
    """When `storage_backend == "hf"`, require a valid, write-capable HF token for the dataset repo.

    Exits the process with code 1 on a missing / invalid / read-only token so the server never
    starts in a state where publishing would later fail. No-op for the local backend.
    """
    if settings.storage_backend != "hf":
        return

    from huggingface_hub import HfApi  # server extra; only imported when HF is selected

    if not settings.hf_token:
        logger.error(
            "storage_backend=hf but no HF token — set HF_TOKEN (or REGISTRY_HF_TOKEN)."
        )
        sys.exit(1)

    api = HfApi(token=settings.hf_token)
    try:
        who = api.whoami()  # validates the token (401 if invalid)
        # create_repo(exist_ok=True) is idempotent and requires write access → verifies it AND
        # ensures the dataset repo exists. Raises (403) if the token can't write.
        api.create_repo(settings.hf_repo_id, repo_type="dataset", exist_ok=True)
    except Exception as exc:  # noqa: BLE001 — any failure here is fatal at startup
        logger.error(
            "HF token invalid or lacks write access to dataset %s: %s",
            settings.hf_repo_id,
            exc,
        )
        sys.exit(1)

    logger.info(
        "HF write access OK for dataset %s (user=%s)",
        settings.hf_repo_id,
        who.get("name") if isinstance(who, dict) else who,
    )
