"""Archive-import tests against real sample module zips in data/input (gitignored).

Skipped when the sample zips are absent (they're not committed). Exercises the full path:
zip upload → server-side enrich + recompile → catalog → tarball download.

**These run with `compile_strict=False`, and that is the honest configuration rather than a
convenience.** Every one of these legacy modules authors variants by rsID alone, so resolving them
needs an Ensembl snapshot — hundreds of megabytes, provisioned by `registry warm-caches`, which CI
does not have and should not download. Under strict, an unresolved position is a refusal, so a
strict import of an rsID-authored module without a snapshot fails by design; that is what
`test_strict_import_refuses_an_unresolvable_module` below pins down. The rest of the file is about
the import *path* — extraction, recompilation, logs, the catalog, the tarball — which is orthogonal
to resolution policy, so it runs in the mode that lets those assertions be about what they claim.
"""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings

INPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "input"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Overrides the shared fixture: best-effort compiles, and cache paths pinned at empty
    directories so the enricher's ambient discovery (`$JUST_DNA_PIPELINES_CACHE_DIR`, platformdirs)
    cannot make the result depend on whose machine this runs on."""
    empty = tmp_path / "no-cache"
    return TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "registry.db",
                local_storage_dir=tmp_path / "artifacts",
                compile_strict=False,
                ensembl_cache=empty,
                clinvar_cache=empty,
                constraint_cache=empty,
            )
        )
    )


@pytest.fixture
def api_key(client: TestClient) -> str:
    """Mirrors the shared fixture, but against this module's own app."""
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    return "mk_live_testkey"


def _zip(name: str) -> Path:
    path = INPUT_DIR / name
    if not path.is_file():
        pytest.skip(f"sample zip not present: {name}")
    return path


def _spec_name(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        member = next(n for n in zf.namelist() if n.endswith("module_spec.yaml"))
        return yaml.safe_load(zf.read(member))["module"]["name"]


def _import(client: TestClient, key: str, name: str, zip_path: Path, version: str = "1.0.0"):
    return client.post(
        f"/api/v1/modules/just-dna-seq/{name}/versions/import",
        data={"version": version, "changelog": "import"},
        files={"archive": (zip_path.name, zip_path.read_bytes(), "application/zip")},
        headers={"Authorization": f"Bearer {key}"},
    )


@pytest.mark.parametrize(
    "zip_name",
    ["diabetes_metabolism_v2.zip", "longevity_2025_v4.zip", "multimorbidity_aging_v1.zip"],
)
def test_import_valid_spec_zip(client: TestClient, api_key: str, zip_name: str) -> None:
    zip_path = _zip(zip_name)
    name = _spec_name(zip_path)
    resp = _import(client, api_key, name, zip_path)
    assert resp.status_code == 201, resp.text
    manifest = resp.json()
    assert manifest["identity"]["name"] == name
    assert manifest["identity"]["canonical_id"] == f"just-dna-seq/{name}@1.0.0"
    assert manifest["compilation"]["compiled_by"] == "marketplace-server"
    assert manifest["stats"]["variant_count"] > 0
    # Appears in the catalog.
    listing = client.get("/api/v1/modules").json()
    assert any(i["name"] == name for i in listing["items"])


def test_import_captures_bundled_logs(client: TestClient, api_key: str) -> None:
    zip_path = _zip("longevity_variants_2026_v2.zip")  # ships a v2.log
    name = _spec_name(zip_path)
    resp = _import(client, api_key, name, zip_path)
    assert resp.status_code == 201, resp.text
    log_names = {e["name"] for e in resp.json()["logs"]}
    assert any(n.endswith(".log") for n in log_names), log_names
    # The bundled log is fetchable via the files endpoint.
    log = min(log_names)
    got = client.get(f"/api/v1/modules/just-dna-seq/{name}/versions/1.0.0/files/{log}")
    assert got.status_code == 200 and got.content


def test_import_missing_studies_rejected(client: TestClient, api_key: str) -> None:
    zip_path = _zip("putter_v1.zip")  # no studies.csv -> fails mandatory grounding
    name = _spec_name(zip_path)
    resp = _import(client, api_key, name, zip_path)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_spec"


def test_import_name_mismatch_rejected(client: TestClient, api_key: str) -> None:
    zip_path = _zip("longevity_2025_v4.zip")
    resp = _import(client, api_key, "wrong_name", zip_path)  # path name != spec name
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "name_mismatch"


def test_strict_import_refuses_an_unresolvable_module(tmp_path: Path) -> None:
    """The other side of the mode split, and the behaviour change 0.11 is really about.

    With `compile_strict` on (the production default) and no reference snapshot, a module whose
    variants are authored by rsID alone cannot be resolved, and the registry refuses rather than
    publishing a partial artifact whose `fully_resolved` is quietly false. The refusal has to be
    actionable by *both* people who could fix it — the compiler names the variants, and the registry
    adds why its enricher could not help — so this asserts the second half is present, not just that
    the status code is 422.
    """
    zip_path = _zip("longevity_2025_v4.zip")
    empty = tmp_path / "no-cache"
    strict_client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "strict.db",
                local_storage_dir=tmp_path / "strict-artifacts",
                compile_strict=True,
                ensembl_cache=empty,
                clinvar_cache=empty,
                constraint_cache=empty,
            )
        )
    )
    repo = strict_client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)

    resp = _import(strict_client, "mk_live_testkey", _spec_name(zip_path), zip_path)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "compile_failed"

    joined = " ".join(detail["errors"])
    assert "unresolved" in joined  # the compiler's half: which variants
    assert "warm-caches" in joined  # the registry's half: what an operator can do about it
    assert "REGISTRY_ENRICH_OFFLINE" in joined


# ── The legacy parquet-only path, and the one value on it that is not display metadata ──────────


def _bare_parquet_zip(tmp_path: Path, build: str) -> tuple[bytes, str]:
    """`(a legacy parquet-only archive, the digest it was compiled to)`.

    Built by really compiling a spec rather than assembled by hand, so what the import path meets is
    what the compiler actually emits. Two details are load-bearing:

    * **No `manifest.json`.** That is the legacy archive shape, and it is the only place
      `genome_build` survives a compile — no parquet column carries it — so its absence is what
      makes the build unrecoverable from the bytes alone.
    * **The variant is coordinate-only.** `derive_variant_key` takes the rsid first when there is
      one, so an rsID-authored row is keyed identically on every assembly and is immune to this
      whole class of bug. Only a coordinate-keyed row lets the build decide the identity, which is
      exactly the case that needs the declaration.
    """
    from just_dna_compiler.compiler import compile_module

    spec = tmp_path / f"spec-{build}"
    spec.mkdir(parents=True)
    (spec / "module_spec.yaml").write_text(
        'schema_version: "1.0"\n'
        "module:\n"
        "  name: hfe_build\n"
        "  title: HFE\n"
        "  description: HFE hereditary haemochromatosis\n"
        "  report_title: HFE\n"
        f"genome_build: {build}\n",
        encoding="utf-8",
    )
    # HFE C282Y at its GRCh37 coordinate — COMPILER.md's own example, because the same base on
    # GRCh38 is 228 bp away.
    (spec / "variants.csv").write_text(
        "chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
        "6,26093141,G,A,A/G,-0.8,risk,het,HFE,hfe\n",
        encoding="utf-8",
    )
    (spec / "studies.csv").write_text(
        "chrom,start,ref,pmid,population,p_value,conclusion,study_design\n"
        "6,26093141,G,8696333,European,1e-8,C282Y,case-control\n",
        encoding="utf-8",
    )
    out = tmp_path / f"out-{build}"
    result = compile_module(spec, out)
    assert result.success, result.errors

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for parquet in sorted(out.glob("*.parquet")):
            zf.write(parquet, parquet.name)
    return buf.getvalue(), result.manifest.artifact.digest


def _import_bare(client: TestClient, key: str, archive: bytes, version: str, **form) -> dict:
    resp = client.post(
        "/api/v1/modules/just-dna-seq/hfe_build/versions/import",
        data={"version": version, "changelog": "legacy import", **form},
        files={"archive": ("legacy.zip", archive, "application/zip")},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_legacy_grch37_archive_needs_its_build_declared(
    client: TestClient, api_key: str, tmp_path: Path
) -> None:
    """`genome_build` is the one importable value that is *inside* `artifact.digest`.

    `reverse_module` recovers it from the archive's own `manifest.json`, and falls back to the
    format's `GRCh38` default when the archive has none. That fallback is right for the common case
    and silently wrong for a GRCh37 module: the build decides the identity key — on GRCh38 a
    resolved substitution is keyed by its `ga4gh:VA.…`, minted against that assembly's refget
    accession — so importing GRCh37 coordinates as GRCh38 produces a different key, a different
    digest, and an allele id naming a base the module never carried.

    Nothing downstream can catch it: the recompile is internally consistent and `verify_manifest`
    re-derives the same wrong digest. So the assertions that matter are about the **bytes** — the
    guessed import moves the digest, and the declared one reproduces the original exactly.
    """
    archive, original_digest = _bare_parquet_zip(tmp_path, "GRCh37")

    guessed = _import_bare(client, api_key, archive, "1.0.0")
    assert guessed["genome_build"] == "GRCh38", "no manifest in the archive, so the default applies"
    assert guessed["artifact"]["digest"] != original_digest

    declared = _import_bare(client, api_key, archive, "1.0.1", genome_build="GRCh37")
    assert declared["genome_build"] == "GRCh37"
    assert declared["artifact"]["digest"] == original_digest, (
        "declaring the build has to reproduce the module's own bytes, not merely relabel it"
    )


def test_a_bare_archive_that_is_grch38_needs_no_declaration(
    client: TestClient, api_key: str, tmp_path: Path
) -> None:
    """The fallback is a sensible default, not a trap — an explicit `GRCh38` changes nothing."""
    archive, original_digest = _bare_parquet_zip(tmp_path, "GRCh38")
    implicit = _import_bare(client, api_key, archive, "1.0.0")
    explicit = _import_bare(client, api_key, archive, "1.0.1", genome_build="GRCh38")
    assert implicit["artifact"]["digest"] == explicit["artifact"]["digest"] == original_digest


def test_import_then_tarball_download(client: TestClient, api_key: str) -> None:
    zip_path = _zip("diabetes_metabolism_v2.zip")
    name = _spec_name(zip_path)
    assert _import(client, api_key, name, zip_path).status_code == 201

    resp = client.get(
        f"/api/v1/modules/just-dna-seq/{name}/versions/1.0.0/download", params={"format": "tarball"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        members = set(tar.getnames())
    assert "manifest.json" in members
    assert "weights.parquet" in members


# ── The corpus as it actually arrives (0.14) ──────────────────────────────────


def test_a_real_agent_zip_keeps_its_prose_its_log_and_its_logo(
    client: TestClient, api_key: str
) -> None:
    """`hepatic_fibrosis_v1.zip`, exactly as `just-module-creator` writes one.

    Six files, three of which the format has no table for: `MODULE.md` (prose), `v1.log` (a 240 KB
    agent transcript) and `logo.png`. Every sample zip in `data/input/` ships a `MODULE.md`, so
    "the readme is called `README.md` now" without a rename would have silently blanked the card of
    the entire existing corpus.

    The log and the logo are asserted to be *out of* `artifact.digest` — a module's identity cannot
    depend on which run produced it, or the same data recompiled tomorrow would be a different module
    and could not be published under any other name. "Out of the digest" is checked as what it
    concretely means: neither file appears in `artifact.files`, the list the Merkle root is taken over.
    """
    zip_path = _zip("hepatic_fibrosis_v1.zip")
    name = _spec_name(zip_path)
    resp = _import(client, api_key, name, zip_path)
    assert resp.status_code == 201, resp.text
    manifest = resp.json()

    card = client.get(f"/api/v1/modules/just-dna-seq/{name}").json()
    assert card["readme"].startswith("# Module:"), "MODULE.md reached the card"
    assert {e["name"] for e in manifest["logs"]} == {"v1.log"}
    assert manifest["logo"]["name"] == "logo.png"

    base = f"/api/v1/modules/just-dna-seq/{name}/versions/1.0.0"
    assert client.get(f"{base}/files/v1.log").status_code == 200
    assert client.get(f"{base}/files/logo.png").status_code == 200

    # `module.version: 1` is a YAML integer in this zip and the field is a freeform string; the
    # registry quotes it rather than refusing, and stamps its own version regardless.
    assert manifest["identity"]["version"] == "1.0.0"

    # Same data, no log and no logo → same content identity. The proof that neither is in it.
    #
    # The content identity is `content_signature`, and `artifact.digest` is deliberately *not* it:
    # the digest names the compiled bytes (upstream S7, and `docs/SCHEMAS.md`'s hash table since
    # format 0.5.4). This test asserted digest equality until 0.16.1 and was a coin flip for it —
    # this zip authors no `sources.csv`, so each publish gets a fresh one from the enricher with
    # `fetched_at` stamped at second resolution, and the two compiles agree only when they land
    # inside the same second. It passed alone on an idle machine and failed inside the full suite.
    with zipfile.ZipFile(zip_path) as zf:
        stripped = io.BytesIO()
        with zipfile.ZipFile(stripped, "w") as out:
            for member in zf.namelist():
                if member.endswith((".log", ".png")):
                    continue
                out.writestr(member, zf.read(member))
    resp2 = client.post(
        f"/api/v1/modules/just-dna-seq/{name}/versions/import",
        data={"version": "1.0.1", "changelog": "no log, no logo"},
        files={"archive": ("stripped.zip", stripped.getvalue(), "application/zip")},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp2.status_code == 201, resp2.text
    second = resp2.json()
    assert second["content_signature"] == manifest["content_signature"]
    assert second["logs"] == [] and second["logo"] is None

    first_files = {f["name"]: f["sha256"] for f in manifest["artifact"]["files"]}
    second_files = {f["name"]: f["sha256"] for f in second["artifact"]["files"]}
    assert set(first_files) == set(second_files)
    assert not [n for n in first_files if n.endswith((".log", ".png"))], first_files

    # And the compiled bytes themselves are identical apart from the one table carrying the
    # timestamp. Anything else moving would mean the log or the logo reached the compile.
    moved = {n for n in first_files if first_files[n] != second_files[n]}
    assert moved <= {"sources.parquet"}, moved
