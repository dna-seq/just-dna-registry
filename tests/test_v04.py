"""Spec normalization + structured authorship (format 0.4, revised for 0.5).

Two things the server does to every authored `module:` block before it validates or compiles, and
one thing it carries through untouched:

* **Registry-owned keys are dropped.** `namespace`/`owner`/`canonical_id` are stamped by the registry
  on publish, and the `module:` block is `extra="forbid"`, so an authored copy would fail validation
  for a value the server overrides anyway. The format ships the canonical set
  (`IDENTITY_AUTHORITY_KEYS`) and the registry injects it rather than keeping its own list.
* **A non-string `module.version` is quoted.** `version: 3` is a YAML integer and the field is a
  freeform string, so the entire pre-0.4 corpus trips on a quoting accident. Through 0.10 the
  registry dropped the key to sidestep this. Format 0.5 turned it into a real advisory field, so it
  is now normalized instead of discarded — the author's marker survives (coerced to SemVer, with the
  original recorded), and the registry's stamped `Identity.version` still wins.
* **Structured per-version `authorship` (RM14)** is carried verbatim spec → manifest and surfaces on
  the API detail's inline manifest, so a consumer can route scrutiny by author-kind.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from just_dna_compiler.compiler import validate_spec
from just_dna_format.normalize import IDENTITY_AUTHORITY_KEYS

from just_dna_registry.services.publish import normalize_module_block

# A self-contained spec: positions are authored, so it compiles without any resolution. It carries a
# registry-owned key, an unquoted integer `version`, and an `authorship` block — all three wiring
# points in one fixture.
_MODULE_YAML = """\
schema_version: "1.0"
module:
  name: {name}
  version: 3
  namespace: someone-elses-namespace
  title: Coronary
  description: Coronary artery disease risk
  report_title: Coronary
  icon: heart
  color: "#db2828"
genome_build: GRCh38
authorship:
  - who: Jane Doe
    role: created
    kind: [human_expert]
  - who: claude-opus
    role: audited
    kind: [ai, agent]
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _write_spec(spec_dir: Path, name: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "module_spec.yaml").write_text(_MODULE_YAML.format(name=name), encoding="utf-8")
    (spec_dir / "variants.csv").write_text(_VARIANTS, encoding="utf-8")
    (spec_dir / "studies.csv").write_text(_STUDIES, encoding="utf-8")


def _publish(client, key, name, version):
    return client.post(
        f"/api/v1/modules/just-dna-seq/{name}/versions",
        data={"version": version, "changelog": "initial"},
        files=[
            ("files", ("module_spec.yaml", _MODULE_YAML.format(name=name).encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers=_auth(key),
    )


# ── normalize_module_block ─────────────────────────────────────────────────────


def test_raw_spec_is_rejected_without_normalization(tmp_path: Path) -> None:
    """The normalization is load-bearing, not cosmetic: the authored spec fails validation as-is,
    and it fails on BOTH offenders — the stray authority key and the integer version."""
    spec = tmp_path / "spec"
    _write_spec(spec, "coronary")
    result = validate_spec(spec)
    assert not result.valid
    assert any("namespace" in e for e in result.errors), result.errors
    assert any("version" in e for e in result.errors), result.errors


def test_normalization_drops_authority_keys_and_quotes_the_version(tmp_path: Path) -> None:
    spec = tmp_path / "spec"
    _write_spec(spec, "coronary")

    changes = normalize_module_block(spec)
    assert any("namespace" in c for c in changes), changes
    assert any("version" in c for c in changes), changes
    assert validate_spec(spec).valid

    # Idempotent, and byte-preserving once clean — so re-normalizing a stored spec cannot churn its
    # input hash.
    before = (spec / "module_spec.yaml").read_bytes()
    assert normalize_module_block(spec) == []
    assert (spec / "module_spec.yaml").read_bytes() == before


def test_the_authored_version_survives_normalization(tmp_path: Path) -> None:
    """0.5 keeps the advisory marker rather than discarding it: `3` becomes the string `"3"`, which
    the format then coerces to SemVer. Contrast 0.10, which dropped the key outright."""
    spec = tmp_path / "spec"
    _write_spec(spec, "coronary")
    normalize_module_block(spec)

    import yaml

    module = yaml.safe_load((spec / "module_spec.yaml").read_text())["module"]
    assert module["version"] == "3"
    assert set(module) & IDENTITY_AUTHORITY_KEYS == set()


# ── End-to-end publish ─────────────────────────────────────────────────────────


def test_publish_normalizes_and_carries_authorship(client: TestClient, api_key: str) -> None:
    resp = _publish(client, api_key, "coronary", "1.0.0")
    assert resp.status_code == 201, resp.text
    manifest = resp.json()

    # The registry is the version authority: the request version wins over anything authored, and
    # the namespace is the one from the path, not the one the spec tried to claim.
    assert manifest["identity"]["version"] == "1.0.0"
    assert manifest["identity"]["namespace"] == "just-dna-seq"

    # authorship carried verbatim spec → manifest (RM14).
    authorship = manifest["authorship"]
    assert [c["who"] for c in authorship] == ["Jane Doe", "claude-opus"]
    assert {c["role"] for c in authorship} == {"created", "audited"}
    assert authorship[1]["kind"] == ["ai", "agent"]


def test_detail_surfaces_authorship_on_inline_manifest(client: TestClient, api_key: str) -> None:
    assert _publish(client, api_key, "coronary", "1.0.0").status_code == 201
    detail = client.get("/api/v1/modules/just-dna-seq/coronary").json()
    carried = detail["latest_manifest"]["authorship"]
    assert {c["who"] for c in carried} == {"Jane Doe", "claude-opus"}
