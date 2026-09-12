"""Startup guards: HF token validation gates server start when the HF backend is selected."""

import re
from pathlib import Path

import pytest

from just_dna_registry.config import Settings
from just_dna_registry.services import enrich
from just_dna_registry.startup import validate_hf_access


def test_local_backend_skips_hf_check() -> None:
    # Local backend must never touch HF — returns cleanly with no token.
    validate_hf_access(Settings(storage_backend="local", hf_token=None))


def test_hf_backend_without_token_exits() -> None:
    with pytest.raises(SystemExit) as exc:
        validate_hf_access(Settings(storage_backend="hf", hf_token=None))
    assert exc.value.code == 1


#: Env names the template documents that are NOT `Settings` fields: the client CLI reads these
#: directly (`client_cli.py`), so they have no server setting and must not read as stale.
CLIENT_ONLY_ENV: frozenset[str] = frozenset(
    {"REGISTRY_URL", "REGISTRY_TOKEN", "REGISTRY_TIMEOUT"}
)


def _template() -> str:
    path = Path(__file__).resolve().parent.parent / ".env.template"
    body = path.read_text()
    # Floor: an absence assertion passes on an empty haystack, and so does a subset check. Show the
    # file is the file before concluding anything about what is or is not named in it.
    assert len(body) > 4000, f".env.template is {len(body)} bytes — read the wrong file?"
    assert "REGISTRY_DB_PATH" in body, "template does not look like our env template"
    return body


def test_env_template_documents_every_setting() -> None:
    """Every `Settings` field appears in `.env.template`, under a name that actually resolves.

    The template went stale by 38 of 83 fields between 0.12 and 0.25 — `REGISTRY_MODE` among them,
    which governs every irreversible decision on the box. A setting nobody can discover is a setting
    that gets configured by reading source, so this is a documentation contract and not a nicety.

    A field with a `validation_alias` counts if ANY of its choices is documented: `NCBI_API_KEY`,
    `PHARMVAR_API_KEY`, `HF_TOKEN` and `JUST_DNA_CONTACT_EMAIL` are the conventional spellings the
    enricher and huggingface_hub read, and the template documents those rather than our prefixed
    forms — deliberately, since an operator who already exports one outranks our setting.

    **It must appear as an assignment, not merely be mentioned.** A substring search over the file
    was the first version and it passed with `REGISTRY_MODE` deleted from its own block, because the
    prose two paragraphs up says the words "REGISTRY_MODE in a unit file". Prose is not a documented
    knob: an operator copies this file and uncomments lines. So the pattern is anchored to the start
    of a line, with an optional comment marker, which is the shape every entry here has.
    """
    body = _template()
    fields = Settings.model_fields
    assert len(fields) >= 60, f"only {len(fields)} settings fields — reflection broken, not the doc"

    def assigned(env_name: str) -> bool:
        return re.search(rf"^#?\s*{re.escape(env_name)}=", body, re.MULTILINE | re.IGNORECASE) is not None

    undocumented = []
    for name, field in fields.items():
        alias = field.validation_alias
        candidates = (
            [c for c in alias.choices if isinstance(c, str)]
            if alias is not None and hasattr(alias, "choices")
            else ["REGISTRY_" + name.upper()]
        )
        if not any(assigned(c) for c in candidates):
            undocumented.append(name)

    assert not undocumented, (
        f"{len(undocumented)} setting(s) missing from .env.template: {sorted(undocumented)}"
    )


def test_env_template_names_no_setting_that_no_longer_exists() -> None:
    """The reverse direction: a `REGISTRY_*` name in the template is a real field or a client var.

    Documenting a removed knob is worse than documenting none — an operator sets it, sees no effect,
    and has no way to tell a typo from a retired setting.
    """
    body = _template()
    tokens = set(re.findall(r"\bREGISTRY_[A-Z0-9_]+\b", body))
    # Floor: if the regex stops matching, `stale` is empty and this passes vacuously.
    assert len(tokens) >= 60, f"parsed only {len(tokens)} REGISTRY_ tokens — regex broken"

    fields = Settings.model_fields
    stale = sorted(
        t for t in tokens if t[len("REGISTRY_") :].lower() not in fields and t not in CLIENT_ONLY_ENV
    )
    assert not stale, f"template names settings that do not exist: {stale}"


@pytest.mark.skipif(
    not enrich.enricher_available(), reason="the network tier is not installed"
)
def test_env_template_mentions_every_cache_lane() -> None:
    """Every lane in the enricher's own registry is discoverable from the template.

    `warm-caches` provisions all of them, so an operator choosing where snapshots land needs the full
    list — ours had drifted by eight lanes once, and the one that mattered was `acmg`: a setting we
    had, a pass that read it, and a provisioning command that never mentioned it, so a box reporting
    everything green had the ACMG check falling back to a page serving SF v3.2.

    Lanes are matched by NAME, not by a `REGISTRY_*` spelling, because `alphagenome_avi` deliberately
    has no setting of its own and resolves under the shared base.
    """
    lanes = set(enrich.cache_lanes())
    # Floor: an emptied import would make the subset check below vacuous.
    assert len(lanes) >= 10, f"lane registry has {len(lanes)} lanes — import moved?"

    body = _template().upper()
    unmentioned = sorted(n for n in lanes if n.upper() not in body)
    assert not unmentioned, f"lanes absent from .env.template: {unmentioned}"
