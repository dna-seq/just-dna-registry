"""
The publish dry run: `POST .../validate` (offline) and `POST .../check` (network tier).

Two conventions worth stating, because both are easy to "fix" wrongly later:

**A finding is a 200.** A spec that would be rejected comes back with `valid: false` and the reasons
in the body, not as a 4xx. The endpoint's job is to report; only a request we cannot assemble a spec
directory from is an error.

**Offline means zero egress, and that is asserted rather than assumed.** The `no_network` fixture
below makes any non-loopback socket connection raise, so a test claiming `?offline=true` reaches
nothing would fail loudly if the enricher ever slipped in a lookup. It also covers the
`download=False` rule: with `download=True` the "no snapshot" case would try HuggingFace and trip the
tripwire instead of returning a clean 503.

**Not covered here, deliberately** — live gnomAD / Ensembl / dbSNP / Europe PMC / Crossref, the
`frequencies` and `literature` passes (online-only by construction: there is no offline snapshot to
assert against, and never will be), the multi-gigabyte `ensure_*_snapshot` downloads, and the
enriched-with-a-real-cache path (hand-building a snapshot means reproducing another package's private
duckdb/parquet layout, which tests that layout rather than our wiring). A CI failure caused by gnomAD
publishing a new release would tell us nothing about this repo. The registry-side wiring — modes,
cache paths, projection, cost guards — is covered without any of it.
"""

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings

_AUTH = {"Authorization": "Bearer mk_live_testkey"}

_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  version: 3
  namespace: not-yours
  title: Coronary
  description: Coronary artery disease risk
  report_title: Coronary
genome_build: GRCh38
"""
# Authored coordinates, so nothing needs resolving and the offline path is meaningful.
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
)
# rsID only: with no snapshot there is no way to place it, so it stays unresolved.
_VARIANTS_RSID_ONLY = (
    "rsid,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,A/G,-0.8,risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"
_BAD_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,NOT-A-PMID,T,0.05,E,U\n"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every non-loopback connection raise, so "zero egress" is a claim the suite checks."""
    real_connect = socket.socket.connect

    def guarded(self, address):  # noqa: ANN001 — matches socket's own signature
        host = address[0] if isinstance(address, tuple) else ""
        if host not in ("127.0.0.1", "::1", "localhost", ""):
            raise AssertionError(f"test attempted a network connection to {address!r}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


def _app(tmp_path: Path, **over) -> TestClient:
    """An app whose cache paths point at an empty directory.

    Explicit rather than unset, so the enricher's ambient discovery ($JUST_DNA_PIPELINES_CACHE_DIR,
    platformdirs) cannot make these assertions depend on whose machine they run on.
    """
    empty = tmp_path / "no-cache"
    client = TestClient(
        create_app(
            Settings(
                db_path=tmp_path / "m.db",
                local_storage_dir=tmp_path / "a",
                ensembl_cache=empty,
                clinvar_cache=empty,
                constraint_cache=empty,
                **over,
            )
        )
    )
    repo = client.app.state.repo
    account_id = repo.create_account("antonkulaga")
    repo.add_namespace("just-dna-seq", account_id)
    repo.add_api_key("mk_live_testkey", account_id)
    return client


def _parts(yaml: str = _YAML, variants: str = _VARIANTS, studies: str = _STUDIES) -> list:
    return [
        ("files", ("module_spec.yaml", yaml.encode(), "text/yaml")),
        ("files", ("variants.csv", variants.encode(), "text/csv")),
        ("files", ("studies.csv", studies.encode(), "text/csv")),
    ]


def _validate(client: TestClient, *, strict: bool = True, **kw) -> dict:
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/validate",
        params={"strict": strict},
        files=_parts(**kw),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── /validate ──────────────────────────────────────────────────────────────────


def test_valid_spec_reports_its_stats(tmp_path: Path) -> None:
    body = _validate(_app(tmp_path))
    assert body["valid"] and body["strict"]
    assert set(body["stats"]["genes"]) == {"CYP2C19"}
    assert set(body["stats"]["categories"]) == {"cyp2c19"}
    assert body["stats"]["variant_count"] == 1


def test_an_invalid_spec_is_a_200_with_findings(tmp_path: Path) -> None:
    """The contract that separates this endpoint from publish: a rejection is data, not a status."""
    body = _validate(_app(tmp_path), studies=_BAD_STUDIES)
    assert body["valid"] is False
    assert body["errors"], body


def test_strict_only_changes_severity(tmp_path: Path) -> None:
    """The compiler promises `strict` "changes severity only; it never adds or removes a finding".

    Asserted as a relationship rather than against fixed message text, so it keeps testing the
    property after the compiler rewords something — and it is a genuine contract test against the
    dependency, not a restatement of our own code.
    """
    client = _app(tmp_path)
    loose = _validate(client, strict=False, studies=_BAD_STUDIES)
    strict = _validate(client, strict=True, studies=_BAD_STUDIES)

    assert set(strict["errors"]) >= set(loose["errors"])
    assert set(strict["errors"]) | set(strict["warnings"]) == set(loose["errors"]) | set(
        loose["warnings"]
    )


def test_info_reports_what_the_server_rewrote(tmp_path: Path) -> None:
    """A dry run that silently normalizes your spec is predicting a publish you did not describe."""
    body = _validate(_app(tmp_path))
    joined = " ".join(body["info"])
    assert "namespace" in joined  # the authority key we dropped
    assert "version" in joined  # the integer we quoted


def test_content_signature_matches_a_locally_computed_one(tmp_path: Path) -> None:
    """Client and server must agree on the signature, or the whole dedup pre-check is theatre."""
    from just_dna_compiler.compiler import content_signature

    from just_dna_registry.services.publish import normalize_module_block

    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "module_spec.yaml").write_text(_YAML)
    (spec / "variants.csv").write_text(_VARIANTS)
    (spec / "studies.csv").write_text(_STUDIES)
    normalize_module_block(spec)

    body = _validate(_app(tmp_path / "srv"))
    assert body["content_signature"] == content_signature(spec)


def test_name_mismatch_is_a_finding_not_a_rejection(tmp_path: Path) -> None:
    client = _app(tmp_path)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/something-else/validate", files=_parts(), headers=_AUTH
    )
    assert resp.status_code == 200
    assert resp.json()["name_matches_path"] is False


def test_published_as_predicts_the_duplicate_rejection(tmp_path: Path) -> None:
    """The pre-check and the publish gate must agree — that they do is the endpoint's whole value."""
    client = _app(tmp_path, compile_strict=False)
    assert (
        client.post(
            "/api/v1/modules/just-dna-seq/coronary/versions",
            data={"version": "1.0.0"},
            files=_parts(),
            headers=_AUTH,
        ).status_code
        == 201
    )

    # The pre-check sees it...
    body = _validate(client)
    assert [(v["name"], v["version"]) for v in body["published_as"]] == [("coronary", "1.0.0")]

    # ...and publishing the same data under another name is indeed refused.
    dup = client.post(
        "/api/v1/modules/just-dna-seq/rebranded/versions",
        data={"version": "1.0.0"},
        files=_parts(yaml=_YAML.replace("name: coronary", "name: rebranded")),
        headers=_AUTH,
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["error"] == "duplicate_content"


def test_validate_requires_publish_capability(tmp_path: Path) -> None:
    client = _app(tmp_path)
    assert client.post("/api/v1/modules/just-dna-seq/coronary/validate", files=_parts()).status_code == 401
    other = client.post(
        "/api/v1/modules/someone-else/coronary/validate", files=_parts(), headers=_AUTH
    )
    assert other.status_code == 403


# ── /check ─────────────────────────────────────────────────────────────────────


def _check(client: TestClient, **params) -> tuple[int, dict]:
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params=params,
        files=_parts(**{k: v for k, v in params.pop("_spec", {}).items()}) if False else _parts(),
        headers=_AUTH,
    )
    return resp.status_code, resp.json()


def test_offline_check_reports_without_touching_the_network(tmp_path: Path) -> None:
    code, body = _check(_app(tmp_path), offline=True)
    assert code == 200, body
    assert body["would_publish"] is True
    enrichment = body["enrichment"]
    assert enrichment["offline"] is True
    # `best_effort` regardless of `?strict=`: strict enrichment raises, and this endpoint reports.
    assert enrichment["mode"] == "best_effort"
    assert enrichment["unresolved"] == []


def test_a_missing_snapshot_offline_degrades_with_a_reason(tmp_path: Path) -> None:
    """A missing snapshot is a degradation to report, never a refusal.

    An earlier cut raised `503 enrichment_unavailable` whenever `available_references` came back
    empty on an online run — exactly backwards, since a snapshot is what makes *offline* resolution
    possible and an online run falls through to live Ensembl without one. That 503 refused the only
    configuration that actually works. What remains is a note in the report.
    """
    client = _app(tmp_path)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    notes = " ".join(resp.json()["enrichment"]["notes"])
    assert "no local snapshot" in notes
    assert "warm-caches" in notes  # what an operator would do about it


def test_503_only_when_the_tier_is_genuinely_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case that is a real 503: the enricher is not installed, so nothing can be attempted."""
    from just_dna_registry.services import enrich as enrich_service

    monkeypatch.setattr(enrich_service, "enricher_available", lambda: False)
    resp = _app(tmp_path).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "enrichment_unavailable"
    assert any("not installed" in m for m in detail["missing"])
    # No `Retry-After`: retrying does not help until an operator changes the deployment.
    assert "retry-after" not in {k.lower() for k in resp.headers}


def test_the_pgx_family_is_gated_by_declared_use(tmp_path: Path) -> None:
    """Every PGx upstream forbids sale, so on the default `unstated` none is queried — the registry
    must not declare a purpose on a publisher's behalf."""
    resp = _app(tmp_path).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    pgx = resp.json()["enrichment"]["pgx"]
    assert pgx["declared_use"] == "unstated"
    assert pgx["sources"] == []  # nothing consulted


def test_offline_pgx_is_snapshot_only_rather_than_skipped_wholesale(tmp_path: Path) -> None:
    """`offline` stopped being the axis it was when the gated sources got caches (0.5.1 / RM38).

    Through 0.11 PharmVar and CPIC were live-only, so an offline `?pgx=` skipped them as a category.
    Now every leg is snapshot → live → skipped-with-a-reason, and what an offline run without
    snapshots reports is *per source and per reason*, not one blanket sentence. This deployment has
    none provisioned, so each leg must name the thing that is actually missing — which is what tells
    an operator that `warm-caches --pgx` is the fix rather than "wait for the network".
    """
    pgx = _app(tmp_path).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True},
        files=_parts(),
        headers=_AUTH,
    ).json()["enrichment"]["pgx"]

    assert pgx["offline"] is True
    assert pgx["sources"] == []  # nothing consulted: no snapshot, and no egress permitted

    reasons = " ".join(pgx["skipped"])
    # ClinPGx has no live route at all, so its reason is the snapshot and never the network.
    clinpgx = next(s for s in pgx["skipped"] if s.startswith("clinpgx:"))
    assert "no snapshot found" in clinpgx
    # PharmVar's reason has to name *both* routes, because the snapshot is the one a hosted
    # deployment can have and the key is the one it usually cannot.
    assert "pharmvar" in reasons
    # ClinGen is the genuinely offline-blocked one: CC0, live-only, no snapshot exists to build.
    assert any("clingen dosage" in s and "offline" in s for s in pgx["skipped"])


def test_a_pharmvar_snapshot_enables_the_leg_without_a_key(tmp_path: Path) -> None:
    """The key stopped being the only switch when PharmVar got a cache (0.5.1 / RM38).

    Reading a built snapshot needs no credential, so a hosted deployment can run the PharmVar leg
    without one — which matters because that key is personal and non-transferable under PharmVar's
    terms §2, and on a public server it would mean third parties querying it on the operator's
    account. Asserting on `pharmvar_enabled` rather than on findings: the fixture directory is not a
    real snapshot, and what is under test is the switch, not the parquet.
    """
    snapshot = tmp_path / "pharmvar"
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "data" / "alleles.parquet").write_bytes(b"PAR1")  # located, not readable

    without = _app(tmp_path / "a").post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True}, files=_parts(), headers=_AUTH,
    ).json()["enrichment"]["pgx"]
    assert without["pharmvar_enabled"] is False

    with_snapshot = _app(tmp_path / "b", pharmvar_cache=snapshot).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True}, files=_parts(), headers=_AUTH,
    ).json()["enrichment"]["pgx"]
    assert with_snapshot["pharmvar_enabled"] is True


def test_an_out_of_vocabulary_declared_use_is_refused(tmp_path: Path) -> None:
    """`non-commercial` is the enricher CLI's hyphenated spelling and not the vocabulary member.

    It must not fall through to the enricher, where the nearest wrong behaviour would be treating an
    unrecognized declaration as something other than a refusal — for sources whose whole point is
    that an undeclared purpose means *do not fetch*.
    """
    resp = _app(tmp_path).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True, "declared_use": "non-commercial"},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_declared_use"
    assert "non_commercial" in detail["errors"][0]


def test_declared_use_defaults_to_the_server_setting(tmp_path: Path) -> None:
    resp = _app(tmp_path, declared_use="non_commercial").post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.json()["enrichment"]["pgx"]["declared_use"] == "non_commercial"


def test_a_pharmvar_key_still_enables_the_leg(tmp_path: Path) -> None:
    """No boolean of its own: what the server *has* is the switch, so it cannot disagree with reality.

    A key was the only route until PharmVar got a cache (0.5.1 / RM38) — see the snapshot test
    above, which covers the other half. Either alone enables the leg.
    """
    without = _app(tmp_path / "a").post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True}, files=_parts(), headers=_AUTH,
    ).json()["enrichment"]["pgx"]
    assert without["pharmvar_enabled"] is False

    with_key = _app(tmp_path / "b", pharmvar_api_key="pv_test").post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True}, files=_parts(), headers=_AUTH,
    ).json()["enrichment"]["pgx"]
    assert with_key["pharmvar_enabled"] is True


def test_an_rsid_only_module_reports_what_it_could_not_place(tmp_path: Path) -> None:
    client = _app(tmp_path)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "strict": True},
        files=_parts(variants=_VARIANTS_RSID_ONLY),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enrichment"]["unresolved"], "an rsID with no snapshot cannot be placed"
    # Unresolved positions block a *strict* publish, so the dry run must say so.
    assert body["would_publish"] is False


def test_an_invalid_spec_short_circuits_before_enrichment(tmp_path: Path) -> None:
    """The strongest cost guard: a spec that cannot compile is never worth an outbound request."""
    client = _app(tmp_path)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True},
        files=_parts(studies=_BAD_STUDIES),
        headers=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enrichment"] is None
    assert body["skipped_reason"] == "invalid_spec"
    assert body["would_publish"] is False


def test_a_module_over_the_variant_cap_is_refused_before_spending(tmp_path: Path) -> None:
    code, body = _check(_app(tmp_path, enrich_max_variants=0), offline=True)
    assert code == 422
    assert body["detail"]["error"] == "too_many_variants"


def test_vrs_coverage_is_counted_per_allele(tmp_path: Path) -> None:
    """A substitution mints offline; the count is over ALT slots, not rows."""
    code, body = _check(_app(tmp_path), offline=True)
    assert code == 200
    vrs = body["enrichment"]["vrs"]
    assert vrs["alleles"] == 1 and vrs["identified"] == 1
    assert vrs["complete"] is True


# ── the optional passes ────────────────────────────────────────────────────────
#
# These three used to be unreachable in the worst way: the router exposed `?frequencies=`,
# `?literature=` and `?acmg=` as query parameters and the functions they dispatch to did not exist
# anywhere in the package, so asking for any of them raised `NameError` inside a threadpool worker
# and came back a 500. Nothing caught it because nothing here had ever passed the flags. Every test
# below runs under the `no_network` fixture, so each also proves the pass reaches nothing offline.


def test_the_frequency_pass_runs_and_reports_rather_than_raising(tmp_path: Path) -> None:
    code, body = _check(_app(tmp_path), offline=True, frequencies=True)
    assert code == 200, body
    freq = body["enrichment"]["frequencies"]
    assert freq is not None, "?frequencies=true must produce a report, not a null"
    # gnomAD is online-only and there is no snapshot to fall back on, so offline is a clean no-op.
    assert freq["skipped_offline"] is True
    assert freq["covered"] == 0


def test_the_literature_pass_runs_and_reports_rather_than_raising(tmp_path: Path) -> None:
    code, body = _check(_app(tmp_path), offline=True, literature=True)
    assert code == 200, body
    lit = body["enrichment"]["literature"]
    assert lit is not None
    assert lit["skipped_offline"] is True
    # A quote that could not be checked is never a quote that failed.
    assert lit["quotes_found"] == 0 and lit["missing_pmids"] == []


def test_a_pgx_only_module_gets_a_literature_note_not_a_failure(tmp_path: Path) -> None:
    """`studies.csv` is required iff `variants.csv` is present, so a PGx-only module has none.

    The literature pass raises on a missing `studies.csv`. That is the correct and complete shape of
    such a module rather than a defect in it, so the dry run must degrade to a note — a 422 here
    would tell a PGx author their module is broken for carrying exactly the tables it should.
    """
    parts = [
        ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
        ("files", ("allele_function.csv",
                   b"gene,allele,function_status\nCYP2C19,*2,no_function\n", "text/csv")),
    ]
    resp = _app(tmp_path).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "literature": True, "acmg": True},
        files=parts,
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    enrichment = resp.json()["enrichment"]
    assert any("studies.csv" in w for w in enrichment["literature"]["warnings"])
    # Same shape one table over: `acmg_sf` is a variants-table column.
    assert any("variants.csv" in w for w in enrichment["acmg"]["warnings"])


def test_acmg_offline_without_a_snapshot_is_unchecked_not_clean(tmp_path: Path) -> None:
    """`unchecked` and `clean` are different answers, and conflating them is the failure mode.

    NCBI's page is the only fetchable form of the list, so offline the check needs a built snapshot
    (`just-dna-enricher acmg build`). Without one it must say the question was never put — reporting
    zero mismatches would read as "your acmg_sf flags were verified", which is what the whole
    `unverifiable`/`unchecked` vocabulary upstream exists to prevent.
    """
    code, body = _check(_app(tmp_path), offline=True, acmg=True)
    assert code == 200, body
    acmg = body["enrichment"]["acmg"]
    assert acmg is not None
    assert acmg["list_version"] is None, "no list was read, so none can be named"
    assert acmg["checked"] == 0
    assert any("snapshot" in w for w in acmg["warnings"])


def test_check_requires_publish_capability(tmp_path: Path) -> None:
    client = _app(tmp_path)
    assert client.post("/api/v1/modules/just-dna-seq/coronary/check", files=_parts()).status_code == 401
    other = client.post(
        "/api/v1/modules/someone-else/coronary/check", files=_parts(), headers=_AUTH
    )
    assert other.status_code == 403
