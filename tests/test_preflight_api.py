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

**One thing about those passes *is* covered**: what the endpoint answers when an upstream does not.
Their findings need the network; their failure handling does not, and a stub client raising the tier's
own error type reaches every line the real 5xx would. That half was untested and broken — see the
`unreachable` tests at the end of this file.
"""

import socket
from pathlib import Path
from typing import Optional

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

    **Every snapshot the enricher can discover, not only the three a strict publish needs.** The PGx
    caches were left unset here, so the `?pgx=` assertions silently described the developer's machine:
    the day a `~/.cache/just-dna-pipelines/clinpgx` appeared beside this checkout, the ClinPGx leg
    started *running* and the test that asserts each leg names its missing snapshot failed with no
    code change behind it. An unset cache is not an absent one.
    """
    empty = tmp_path / "no-cache"
    # `over` last: a test that provisions one snapshot (`pharmvar_cache=…`) overrides that one and
    # keeps the rest pinned empty.
    settings = {
        "db_path": tmp_path / "m.db",
        "local_storage_dir": tmp_path / "a",
        "ensembl_cache": empty,
        "clinvar_cache": empty,
        "constraint_cache": empty,
        "cpic_cache": empty,
        "pharmvar_cache": empty,
        "clinpgx_cache": empty,
        "acmg_snapshot_dir": empty,
        **over,
    }
    client = TestClient(create_app(Settings(**settings)))
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

    # The pre-check sees it, under the name that would actually be refused...
    body = client.post(
        "/api/v1/modules/just-dna-seq/rebranded/validate",
        files=_parts(yaml=_YAML.replace("name: coronary", "name: rebranded")),
        headers=_AUTH,
    ).json()
    assert [(v["name"], v["version"]) for v in body["published_as"]] == [("coronary", "1.0.0")]
    assert [(v["name"], v["version"]) for v in body["published_elsewhere"]] == [
        ("coronary", "1.0.0")
    ]

    # ...and publishing the same data under another name is indeed refused.
    dup = client.post(
        "/api/v1/modules/just-dna-seq/rebranded/versions",
        data={"version": "1.0.0"},
        files=_parts(yaml=_YAML.replace("name: coronary", "name: rebranded")),
        headers=_AUTH,
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["error"] == "duplicate_content"


def test_a_review_pass_is_not_a_duplicate_and_the_pre_flight_agrees(tmp_path: Path) -> None:
    """S10: a second version of the same module with unchanged data is legal, and was being predicted
    as a refusal.

    The scenario is the commonest second pass there is: `1.0.0` is published, a human reviews it,
    changes no data, and publishes `1.0.1`. The gate carves the same `(namespace, name)` out
    explicitly; the pre-flight ran the same lookup without the carve-out, so `/validate` answered
    `would_publish_module_level: false` for a publish that then returned `201` — a false negative in
    the one field the docs tell a CI job to branch on.

    Driven end to end rather than asserted on the field alone, because the property under test is
    agreement between two code paths: what the pre-flight predicts, and what publish then does.
    """
    client = _app(tmp_path, compile_strict=False)
    assert client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"}, files=_parts(), headers=_AUTH,
    ).status_code == 201

    body = _validate(client)
    # Still listed — "this data is already published as 1.0.0" is how an author confirms they changed
    # nothing — but not counted, and separated into the list that says which hits refuse.
    assert [(v["name"], v["version"]) for v in body["published_as"]] == [("coronary", "1.0.0")]
    assert body["published_elsewhere"] == []
    assert body["would_publish_module_level"] is True

    republished = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.1"}, files=_parts(), headers=_AUTH,
    )
    assert republished.status_code == 201, republished.text  # the verdict was right


def test_the_review_pass_carve_out_holds_for_check_too(tmp_path: Path) -> None:
    """The same fix on `/check`, whose `would_publish` composes the module-level half.

    `/check` reaches `validation_report` down a different path (`dry_run`), and the namespace had to
    be threaded through both — a fix to one and not the other would leave the endpoint a CI job is
    actually pointed at still answering `false`.
    """
    client = _app(tmp_path, compile_strict=False)
    assert client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"}, files=_parts(), headers=_AUTH,
    ).status_code == 201

    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True}, files=_parts(), headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["validation"]["published_elsewhere"] == []
    assert body["validation"]["would_publish_module_level"] is True
    assert body["would_publish"] is True

    other = client.post(
        "/api/v1/modules/just-dna-seq/rebranded/check",
        params={"offline": True},
        files=_parts(yaml=_YAML.replace("name: coronary", "name: rebranded")),
        headers=_AUTH,
    ).json()
    assert [v["name"] for v in other["validation"]["published_elsewhere"]] == ["coronary"]
    assert other["validation"]["would_publish_module_level"] is False
    assert other["would_publish"] is False


def test_the_module_level_verdict_composes_the_three_gates(tmp_path: Path) -> None:
    """S1: one branchable field for the publish gates that do not scale with the variant count.

    Walked gate by gate rather than asserted once, because the field's whole value is that it agrees
    with what publish would actually answer: a spec that will not validate, a name the path does not
    match (`422 name_mismatch`), and data already published (`409 duplicate_content`).
    """
    client = _app(tmp_path, compile_strict=False)
    assert _validate(client)["would_publish_module_level"] is True

    assert _validate(client, studies=_BAD_STUDIES)["would_publish_module_level"] is False

    mismatch = client.post(
        "/api/v1/modules/just-dna-seq/something-else/validate", files=_parts(), headers=_AUTH
    )
    assert mismatch.json()["would_publish_module_level"] is False

    assert (
        client.post(
            "/api/v1/modules/just-dna-seq/coronary/versions",
            data={"version": "1.0.0"},
            files=_parts(),
            headers=_AUTH,
        ).status_code
        == 201
    )
    # The dedup gate, asserted against a *rename* — which is what publish refuses. Until 0.16 this
    # asserted the same-module case instead, and so pinned the S10 false negative as intended
    # behaviour: `false` for a republish of this module's own unchanged data, which publish allows.
    after = client.post(
        "/api/v1/modules/just-dna-seq/rebranded/validate",
        files=_parts(yaml=_YAML.replace("name: coronary", "name: rebranded")),
        headers=_AUTH,
    ).json()
    assert after["valid"] is True and after["published_elsewhere"]
    assert after["would_publish_module_level"] is False, "a valid spec can still be undeployable"


def test_validate_requires_publish_capability(tmp_path: Path) -> None:
    client = _app(tmp_path)
    assert client.post("/api/v1/modules/just-dna-seq/coronary/validate", files=_parts()).status_code == 401
    other = client.post(
        "/api/v1/modules/someone-else/coronary/validate", files=_parts(), headers=_AUTH
    )
    assert other.status_code == 403


# ── /check ─────────────────────────────────────────────────────────────────────


def _check(client: TestClient, *, spec: Optional[dict] = None, **params) -> tuple[int, dict]:
    """POST `/check` with `params` as the query string and `spec` overriding the uploaded parts.

    `spec` is a separate argument rather than another `**params` key on purpose: everything in `params`
    goes on the query string, so a spec override smuggled in there would be ignored by the server and
    silently checked against the default module instead.
    """
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params=params,
        files=_parts(**(spec or {})),
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


def test_an_empty_conflict_list_says_which_empty_it_is(tmp_path: Path) -> None:
    """`clin_sig_conflicts: []` must not be readable as "checked, all clear" when nothing was checked.

    These caches are empty directories, so the cross-check has no ClinVar snapshot to compare
    against and cannot run. Before enricher 0.5.2 the report was indistinguishable from a real pass:
    an empty list, no reason, and a `would_publish: true` beside it. The token is asserted rather
    than just the prose, because that is what a CI job branches on.
    """
    code, body = _check(_app(tmp_path), offline=True)
    assert code == 200, body
    enrichment = body["enrichment"]
    assert enrichment["clin_sig_conflicts"] == []
    assert enrichment["clin_sig_not_checked"] == "no_snapshot"
    notes = " ".join(enrichment["notes"])
    assert "clin_sig cross-check did not run" in notes
    assert "unchecked, not clean" in notes
    # Unchecked is not a defect in the module: the operator owns this, so the publish still stands.
    assert body["would_publish"] is True


def test_an_operator_disabled_check_is_reported_to_the_publisher(tmp_path: Path) -> None:
    """`not_requested` is reported here even though the enricher's own CLI suppresses it.

    There it echoes the author's `--no-verify-clinsig` back at them. Here it is a server setting the
    publisher cannot see, so silence would be the one thing it must never mean.
    """
    client = _app(tmp_path, enrich_verify_clinsig=False)
    code, body = _check(client, offline=True)
    assert code == 200, body
    enrichment = body["enrichment"]
    assert enrichment["clin_sig_not_checked"] == "not_requested"
    notes = " ".join(enrichment["notes"])
    assert "REGISTRY_ENRICH_VERIFY_CLINSIG=false" in notes
    assert "not a clean bill of health" in notes


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


def test_an_authored_sources_row_is_not_a_source_the_registry_consulted(tmp_path: Path) -> None:
    """`PgxCheck.sources` says "actually consulted", and it has to keep saying that.

    `PgxResult.rows` is the *merged* `sources.csv` — the module's own authored rows plus whatever
    the run emitted, existing-wins — so deriving `sources` from it reported a module's declaration
    back as the registry's own consultation. Here the module declares CPIC and the deployment holds
    no CPIC snapshot on an offline run, so the same report says in one field that CPIC answered and
    in the next that it was skipped for want of one. The honest source is `routes`, which gains an
    entry only where a client actually answered.
    """
    sources_csv = (
        "source,layer,license,commercial_use,declared_use\n"
        "cpic,annotation,CC BY-SA 4.0,false,non_commercial\n"
    )
    # A PGx module, because the cross-check needs a gene to ask about: with none it stops before it
    # would have consulted anything, and the bug this pins needs the CPIC leg to be *reached*.
    parts = [
        ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
        ("files", ("allele_function.csv",
                   b"gene,allele,function_status\nCYP2C19,*2,no_function\n", "text/csv")),
        ("files", ("sources.csv", sources_csv.encode(), "text/csv")),
    ]
    body = _app(tmp_path).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": True, "pgx": True, "declared_use": "non_commercial"},
        files=parts,
        headers=_AUTH,
    ).json()
    pgx = body["enrichment"]["pgx"]
    assert pgx["sources"] == []
    assert any(s.startswith("cpic:") for s in pgx["skipped"])
    # And the two fields cannot contradict each other: a skipped source has no route either.
    assert pgx["routes"].get("cpic") is None


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
    # And this is the case that shows why the module-level field is not `would_publish` under
    # another name: nothing module-level is wrong here, and the publish still fails. A caller who
    # read the weaker field as the stronger one would have shipped an upload doomed by the tier
    # only `/check` runs.
    assert body["validation"]["would_publish_module_level"] is True


def test_an_ensembl_that_never_answered_is_unchecked_rather_than_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S20, driven through the real `enrich()` with only the socket replaced.

    The two cases this separates are indistinguishable in `unresolved`, and they call for opposite
    responses: an rsID Ensembl says it has no GRCh38 locus for is a fact about the identifier, while one
    Ensembl never answered about is a fact about the run. Before enricher 0.5.4 the second was reported
    as the first — `resolve_rsid` fused a failed request into `([], None)` — and a consumer auditing
    machine-written rsIDs put two published variants in the fabricated pile because of it.

    The resolver here fails the way a 5xx or a timeout fails, which is the only part of the path a test
    can honestly stand in for; everything downstream is the real thing, including the decision not to
    write a `not_found` row claiming Ensembl was asked.
    """
    from types import SimpleNamespace

    from just_dna_registry.services import enrich as enrich_service

    class _UnreachableEnsembl:
        def resolve_rsid(self, rsid: str) -> tuple[None, None]:
            return None, None  # could not ask — never `([], None)`, which would mean "asked, nothing"

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        enrich_service,
        "shared_lookup_clients",
        lambda: SimpleNamespace(
            ensembl=_UnreachableEnsembl(), ontology=None, gnomad=None, eutils=None,
            europepmc=None, crossref=None,
        ),
    )
    resp = _app(tmp_path, enrich_verify_ref=False).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": False, "strict": True},
        files=_parts(variants=_VARIANTS_RSID_ONLY),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    e = resp.json()["enrichment"]

    assert e["unreachable_rsids"] == ["rs4244285"]
    # It is a *reason* behind an unresolved key, not a replacement for it: the key genuinely has no
    # position, so strict still refuses. What changes is what the publisher is told to do about it.
    assert e["unresolved"] == ["rs4244285"]
    assert resp.json()["would_publish"] is False
    assert any("unchecked rather than established" in note for note in e["notes"])
    assert any("Re-run" in note for note in e["notes"])


def test_an_offline_run_reports_no_unreachable_rsids(tmp_path: Path) -> None:
    """Nothing was asked, so nothing can be unanswered — the field is empty for the same reason
    `unresolved` is full. Pinned because "empty" here must mean "no failed request", never "no failure
    detected": the offline path asks Ensembl nothing at all."""
    code, body = _check(
        _app(tmp_path), offline=True, spec={"variants": _VARIANTS_RSID_ONLY}
    )
    assert code == 200, body
    assert body["enrichment"]["unresolved"] == ["rs4244285"]
    assert body["enrichment"]["unreachable_rsids"] == []


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


def test_an_online_module_over_the_variant_cap_is_refused_before_spending(tmp_path: Path) -> None:
    """The cap still refuses the run it is about: paced, per-subject, outbound.

    Nothing egresses here despite `offline=false` — the refusal lands before the enricher is
    reached, which is the whole point of a pre-flight bound, and the `no_network` tripwire would
    fail this test if it did not.
    """
    code, body = _check(_app(tmp_path, enrich_max_variants=0), offline=False)
    assert code == 422
    assert body["detail"]["error"] == "too_many_variants"


def test_a_refused_online_check_still_answers_the_module_level_half(tmp_path: Path) -> None:
    """S1: the server has the module-level verdict in hand when it refuses, and used to bin it.

    Demonstrated as the inversion it caused: an *invalid* spec over the ceiling has always come back
    `200` with a full report (`invalid_spec` short-circuits earlier), so the ceiling withheld the
    check on exactly the specs that pass it. Both now carry a verdict.
    """
    client = _app(tmp_path, enrich_max_variants=0)
    code, body = _check(client, offline=False)
    assert code == 422
    detail = body["detail"]
    assert detail["error"] == "too_many_variants", "the code a client branches on is unchanged"
    assert detail["subject_count"] == 1 and detail["limit"] == 0
    # The half that does not scale with the variant count, answered rather than withheld.
    assert detail["would_publish_module_level"] is True
    assert detail["validation"]["valid"] is True
    assert detail["validation"]["content_signature"], "dedup is foreseeable above the ceiling too"
    # The message has to say what to do next; `/validate` and offline are the two ways through.
    assert "offline=true" in detail["errors"][0] and "/validate" in detail["errors"][0]


def test_a_module_level_rejection_is_visible_above_the_ceiling(tmp_path: Path) -> None:
    """A name mismatch is a `422 name_mismatch` at publish and needs no variant work to see."""
    client = _app(tmp_path, enrich_max_variants=0)
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": False},
        files=_parts(yaml=_YAML.replace("name: coronary", "name: something_else")),
        headers=_AUTH,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["validation"]["name_matches_path"] is False
    assert detail["would_publish_module_level"] is False


def test_the_variant_cap_does_not_apply_to_a_run_that_cannot_egress(tmp_path: Path) -> None:
    """S1: the bound is about paced outbound requests, and an offline run makes none.

    A ClinVar-scale panel is the case that motivated it — refused in zero time by a ceiling whose
    stated cost model (~6s per twenty subjects against gnomAD's IP-scoped budget) does not describe
    an offline run at all. Offline CPU stays bounded by `enrich_timeout_seconds` and the gate.
    """
    code, body = _check(_app(tmp_path, enrich_max_variants=0), offline=True)
    assert code == 200, body
    assert body["skipped_reason"] is None, "it ran; it was not skipped with a reason"
    assert body["enrichment"] is not None
    assert body["would_publish"] is True


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


def test_a_skipped_frequency_pass_reports_no_absences(tmp_path: Path) -> None:
    """`unchecked` is not `not_found`, and this is the pass where the two are easiest to confuse.

    Skipped offline, `FrequencyResult.missing` carries every allele no existing `frequencies.csv`
    already pins — a statement about the module's coverage, not about gnomAD. Surfaced verbatim
    under a field documented as "asked and does not have", it said gnomAD had been asked about this
    module's alleles and had none of them, on a run that made no request at all. The count is real
    and stays, as a warning that names which of the two it is.
    """
    code, body = _check(_app(tmp_path), offline=True, frequencies=True)
    assert code == 200, body
    freq = body["enrichment"]["frequencies"]
    assert freq["skipped_offline"] is True
    assert freq["missing"] == [] and freq["uncovered"] == []
    warning = " ".join(freq["warnings"])
    assert "not consulted" in warning
    # The coverage gap the authored spec does have — one allele, unpinned — is still reported.
    assert "1 allele(s)" in warning


def test_the_literature_pass_runs_and_reports_rather_than_raising(tmp_path: Path) -> None:
    code, body = _check(_app(tmp_path), offline=True, literature=True)
    assert code == 200, body
    lit = body["enrichment"]["literature"]
    assert lit is not None
    assert lit["skipped_offline"] is True
    # A quote that could not be checked is never a quote that failed.
    assert lit["quotes_found"] == 0 and lit["missing_pmids"] == []


def test_the_identifier_pass_reports_nothing_asked_offline(tmp_path: Path) -> None:
    """OLS4 and HGNC publish no snapshot, so offline there is no question to put — and `unchecked`
    must not arrive looking like a clean bill of health.

    `check_identifiers` takes no `offline` parameter, so unlike every other pass there is nothing to
    defer the decision to: guarding is the only option, which makes saying so the whole job. `clean`
    stays `null` rather than `true`, on the same rule that keeps `VrsCoverage.complete` null over an
    empty table.
    """
    code, body = _check(_app(tmp_path), offline=True, identifiers=True)
    assert code == 200, body
    ident = body["enrichment"]["identifiers"]
    assert ident["skipped_offline"] is True
    assert ident["clean"] is None
    assert ident["stale_traits"] == [] and ident["stale_genes"] == []
    assert ident["checked_traits"] == 0 and ident["checked_genes"] == 0
    assert "nothing was asked" in " ".join(ident["warnings"])


def test_the_identifier_pass_grades_traits_and_genes_without_gating_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real pass, with the network boundary — and only that — replaced.

    Three answers in one run, because the interesting part is that they are three: an obsolete EFO
    term is a finding, a retired HGNC symbol is a finding, and a CURIE in an ontology this tier has
    no route for is neither — it is a question that was never put, and the enricher's own `clean`
    counts it as clean. That is why `unchecked` is a separate field rather than folded into the
    other two.

    And none of it moves `would_publish`: a publish never runs this pass, so a finding here predicts
    nothing about one. Reporting it as a blocker would predict a rejection that will not happen.
    """
    from types import SimpleNamespace

    from just_dna_enricher.identifiers import GeneStatus, TraitStatus

    from just_dna_registry.services import enrich as enrich_service

    class _Ontology:
        def trait(self, curie: str) -> TraitStatus:
            if curie == "EFO_0004340":
                return TraitStatus(
                    curie=curie, state="obsolete", label="obesity", replaced_by="EFO_0007041"
                )
            return TraitStatus(curie=curie, state="unchecked")

        def gene(self, symbol: str) -> GeneStatus:
            return GeneStatus(symbol=symbol, state="retired", current="CYP2C19P1")

    monkeypatch.setattr(
        enrich_service,
        "shared_lookup_clients",
        lambda: SimpleNamespace(
            ontology=_Ontology(), gnomad=None, ensembl=None, eutils=None,
            europepmc=None, crossref=None,
        ),
    )
    variants = (
        "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category,trait_efo_id\n"
        "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19,EFO_0004340;DOID_1234\n"
    )
    # Online, so the pass actually runs; `enrich_verify_ref=False` because the reference-allele check
    # reads sequence over HTTP and the `no_network` fixture would (rightly) trip on it.
    resp = _app(tmp_path, enrich_verify_ref=False).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": False, "identifiers": True},
        files=_parts(variants=variants),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ident = body["enrichment"]["identifiers"]

    assert ident["stale_traits"] == ["EFO_0004340 is obsolete — OLS4 replaces it with EFO_0007041"]
    assert ident["stale_genes"] == ["CYP2C19 is retired — HGNC now approves CYP2C19P1"]
    assert len(ident["unchecked"]) == 1 and "DOID_1234" in ident["unchecked"][0]
    # The unroutable CURIE is not counted as checked, and `clean` is about what was asked.
    assert ident["checked_traits"] == 1 and ident["checked_genes"] == 1
    assert ident["clean"] is False
    assert body["would_publish"] is True


def _ontology_placing_the_gene_on(chromosome: Optional[str]):
    """A stand-in HGNC/OLS4 client that approves every symbol and puts it on `chromosome`.

    `location` is a cytogenetic band because that is what HGNC serves and what `GeneStatus.chromosome`
    parses — passing a bare contig would test a parse the real answer never takes. `None` stands for the
    records where HGNC carries no location at all, which is the "could not compare" case.
    """
    from just_dna_enricher.identifiers import GeneStatus, TraitStatus

    class _Ontology:
        def trait(self, curie: str) -> TraitStatus:
            return TraitStatus(curie=curie, state="current", label="obesity")

        def gene(self, symbol: str) -> GeneStatus:
            return GeneStatus(
                symbol=symbol,
                state="approved",
                current=symbol,
                location=f"{chromosome}q12.2" if chromosome else None,
            )

    return _Ontology()


def test_a_gene_on_another_chromosome_is_a_finding_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S24: the row's `gene` against the chromosome the row's own variant sits on.

    A question neither existing field asks. `stale_genes` asks whether HGNC approves the symbol — it
    does — and `unresolved` asks whether the variant has a position — it has one. Both halves are true
    and the *relationship* between them is false, which is exactly the shape a generated citation takes:
    a real gene name beside an rs number that resolves because dbSNP is dense enough that almost any
    number hits something.

    `clean` folds it in, and `would_publish` deliberately does not: a publish never runs this pass, so
    reporting it as a blocker would predict a rejection that will not happen.
    """
    from types import SimpleNamespace

    from just_dna_registry.services import enrich as enrich_service

    monkeypatch.setattr(
        enrich_service,
        "shared_lookup_clients",
        lambda: SimpleNamespace(
            ontology=_ontology_placing_the_gene_on("16"), gnomad=None, ensembl=None,
            eutils=None, europepmc=None, crossref=None,
        ),
    )
    # The variant is authored on chromosome 10; HGNC puts its gene on 16.
    resp = _app(tmp_path, enrich_verify_ref=False).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": False, "identifiers": True},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ident = body["enrichment"]["identifiers"]

    assert len(ident["gene_loci"]) == 1
    finding = ident["gene_loci"][0]
    assert "CYP2C19" in finding and "10" in finding and "16" in finding
    # The comparison ran, so the sibling field must stay silent — this is the half that makes an empty
    # `gene_loci` readable in the other direction.
    assert ident["gene_loci_not_checked"] is None
    assert ident["stale_genes"] == []  # a different axis, and it really is approved here
    assert ident["clean"] is False
    assert body["would_publish"] is True


def test_an_uncomparable_gene_locus_says_so_rather_than_reporting_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The empty-list trap, on the newest field to have one.

    With no chromosome from HGNC there is nothing to compare against, and `gene_loci: []` then means
    "never compared" while rendering identically to "compared everything, nothing disagreed". The
    sibling reason is the only thing that separates them, so it is asserted here rather than assumed —
    the same rule `clin_sig_not_checked` exists for.
    """
    from types import SimpleNamespace

    from just_dna_registry.services import enrich as enrich_service

    monkeypatch.setattr(
        enrich_service,
        "shared_lookup_clients",
        lambda: SimpleNamespace(
            ontology=_ontology_placing_the_gene_on(None), gnomad=None, ensembl=None,
            eutils=None, europepmc=None, crossref=None,
        ),
    )
    resp = _app(tmp_path, enrich_verify_ref=False).post(
        "/api/v1/modules/just-dna-seq/coronary/check",
        params={"offline": False, "identifiers": True},
        files=_parts(),
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    ident = resp.json()["enrichment"]["identifiers"]

    assert ident["gene_loci"] == []
    assert ident["gene_loci_not_checked"], "an unchecked comparison must not read as a clean one"
    assert "chromosome" in ident["gene_loci_not_checked"]


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


# ── An upstream that does not answer ───────────────────────────────────────────
#
# Every one of these was a `500` until 0.17. The shape of the bug is one line long: each pass adapter
# caught the *pass's* own error type (`FrequencyEnrichmentError`, `LiteratureEnrichmentError`, …) while
# the pass itself lets its **client's** error type through untranslated — `enrich_frequencies` carries
# no `except` at all, and `enrich_literature` calls `esummary` inside a bare `try/finally`. So a gnomAD
# 503 arrived as `GnomadError` (as `httpx.HTTPStatusError` before enricher 0.6.1 / RM97) and sailed
# past the handler written for exactly this case, failing a *reporting* endpoint over somebody else's
# outage. The stubs below raise what the real client raises; nothing here egresses.


def _bundle(**over):
    """A `LookupClients`-shaped stand-in. Every leg explicit, so a slip builds no live client."""
    from types import SimpleNamespace

    base = dict(
        ensembl=None, gnomad=None, eutils=None, europepmc=None, crossref=None, ontology=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _no_live_lookups(tmp_path: Path, **over) -> TestClient:
    """An app whose only network touch is the pass under test.

    `verify_ref` and `verify_rsids` reach live Ensembl and dbSNP from inside `enrich()` itself, and
    `use_gnomad` gives it its own gnomAD link — none of which is the pass being tested, so all three
    are off. The `no_network` fixture is what makes that a checked claim rather than a hope.
    """
    return _app(
        tmp_path,
        enrich_verify_ref=False,
        enrich_verify_rsids=False,
        enrich_use_gnomad=False,
        **over,
    )


def test_a_gnomad_outage_is_a_finding_rather_than_a_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gnomAD 503s; `/check` answers 200 and says the coverage figures are unchecked."""
    from just_dna_enricher.gnomad import GnomadError

    from just_dna_registry.services import enrich as enrich_service

    class _Boom:
        def fetch_frequencies(self, *_a, **_k):
            raise GnomadError("gnomAD request failed: Server error '503 Service Unavailable'")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        enrich_service, "shared_lookup_clients", lambda: _bundle(gnomad=_Boom())
    )
    code, body = _check(_no_live_lookups(tmp_path), offline=False, frequencies=True)
    assert code == 200, body

    freq = body["enrichment"]["frequencies"]
    assert freq["unreachable"] == ["gnomad"]
    # The distinction the field exists for: this is not an offline run, and those empty lists are not
    # gnomAD saying it has nothing.
    assert freq["skipped_offline"] is False
    assert freq["covered"] == 0 and freq["missing"] == [] and freq["uncovered"] == []
    assert any("could not be reached" in w for w in freq["warnings"])
    # An outage upstream is not a defect in the module, so the verdict does not move.
    assert body["would_publish"] is True


def test_a_pubmed_outage_is_a_finding_rather_than_a_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same gap one pass over: `esummary` raises `EutilsError` through a bare `try/finally`."""
    from just_dna_enricher.eutils import EutilsError

    from just_dna_registry.services import enrich as enrich_service

    class _Boom:
        def esummary(self, *_a, **_k):
            raise EutilsError("eutils request failed: Server error '502 Bad Gateway'")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        enrich_service, "shared_lookup_clients", lambda: _bundle(eutils=_Boom())
    )
    code, body = _check(
        _no_live_lookups(tmp_path), offline=False, literature=True, spec={"studies": _STUDIES}
    )
    assert code == 200, body

    lit = body["enrichment"]["literature"]
    assert lit["unreachable"] == ["pubmed"]
    # `missing_pmids: []` is the empty-list trap this field answers: nobody asked, so no PMID was
    # established as absent.
    assert lit["missing_pmids"] == []
    assert body["would_publish"] is True


def test_a_clingen_outage_keeps_the_other_pgx_legs_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One PGx leg falling over must cost its own findings and none of the other three's.

    The four shared a single `try` until 0.17, so an unguarded `fetch_curation_list` inside
    `enrich_dosage_sensitivity` took the PharmVar/CPIC and ClinPGx results down with it — collected,
    then discarded by the exception on the way out, and served as a 500.

    `declared_use="unstated"` is what makes this a zero-egress test rather than a mocked one: the three
    licence-gated legs are skipped without a request, while ClinGen dosage is CC0 and runs anyway, so
    the only client that gets as far as HTTP is the one being made to fail.
    """
    import httpx
    import just_dna_enricher.clingen as clingen

    def refused(*_a, **_k):
        raise httpx.ConnectError("connection refused")

    # Patched at the transport, not at `fetch_curation_list`, so the `ClinGenError` under test is the
    # real one with the real cause chain — which is what `_pgx_leg_clingen` discriminates on.
    monkeypatch.setattr(clingen.httpx, "get", refused)
    code, body = _check(
        _no_live_lookups(tmp_path), offline=False, pgx=True, declared_use="unstated"
    )
    assert code == 200, body

    pgx = body["enrichment"]["pgx"]
    assert pgx["unreachable"] == ["clingen"]
    assert any("clingen" in w and "Unchecked" in w for w in pgx["warnings"])

    # The isolation assertion, and the whole point of the test: ClinGen runs **last**, so everything
    # here was already collected when it fell over. On the shared `try` both of these were empty —
    # the exception unwound past every line that fills them. Asserted as "a finding that is not
    # ClinGen's", rather than against the other passes' wording, which is upstream's to reword.
    assert [w for w in pgx["warnings"] if "clingen" not in w.lower()], pgx
    assert pgx["skipped"], pgx
    # `routes` records what answered, so a leg that did not gets no entry there.
    assert "clingen" not in pgx["routes"]
    assert body["would_publish"] is True


@pytest.mark.parametrize(
    "skip, expected_unreachable",
    [("unreachable", ["acmg-sf-list"]), ("no_reference", [])],
)
def test_an_unreadable_acmg_list_does_not_report_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip: str, expected_unreachable: list
) -> None:
    """`AcmgCheck.clean` defaults to `True`, so the failure return used to publish a pass nobody ran.

    `checked: 0` was honest and `clean: true` beside it was not. The verdict stays a plain bool —
    narrowing a published field to the tri-state `IdentifierCheck.clean` carries would be a major — so
    `unreachable` is what tells a vacuous `clean` from an established one.

    **Both `skip` values are driven, because only one of them is an outage.** `AcmgListUnavailable`
    predates 0.6.2 (RM72) and carries a `VALID_VERIFICATION_SKIPS` member decided where the failure
    happened: `unreachable` means the list was asked for and never came, `no_reference` means there
    was nothing to compare against — offline with no snapshot, a re-laid-out page, a list too short to
    trust. Reporting the second as an outage sends an operator to check a network that is fine when
    the fix is `just-dna-enricher acmg build`. Both are still `clean: true` and both must still say so.
    """
    import just_dna_enricher.acmg as acmg

    def boom(**_k):
        raise acmg.AcmgListUnavailable(
            "the ACMG SF page layout changed; refusing to guess", skip=skip
        )

    monkeypatch.setattr(acmg, "verify_acmg_sf", boom)
    code, body = _check(_no_live_lookups(tmp_path), offline=False, acmg=True)
    assert code == 200, body

    check = body["enrichment"]["acmg"]
    assert check["unreachable"] == expected_unreachable
    assert check["checked"] == 0
    assert check["clean"] is True  # vacuously — which is exactly why the field above is needed
    # Whichever it was, the reason reaches the reader and names which of the two it is.
    assert any("Nothing was checked" in w and skip in w for w in check["warnings"])


def test_an_acmg_list_that_was_read_is_never_an_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plain parent means the question was put and answered badly — never `unreachable`.

    `verify_acmg_sf` raises `AcmgSfError` for a `variants.csv` that will not load and for the strict
    disagreement, and `AcmgListUnavailable` for everything list-side. Catching only the parent would
    have collapsed the two, which is the same conflation `ClinGenError` carried until RM101.
    """
    import just_dna_enricher.acmg as acmg

    def boom(**_k):
        raise acmg.AcmgSfError("variants.csv is invalid: row 2 has no rsid")

    monkeypatch.setattr(acmg, "verify_acmg_sf", boom)
    code, body = _check(_no_live_lookups(tmp_path), offline=False, acmg=True)
    assert code == 200, body

    check = body["enrichment"]["acmg"]
    assert check["unreachable"] == []
    assert any("could not complete" in w for w in check["warnings"])


def test_an_ontology_outage_says_nothing_was_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real `OntologyClient` over a dead transport, which is the only honest way to stub this one.

    This arm caught raw `httpx.HTTPError` until enricher 0.6.2, and it was the only handler of ours a
    *client* fix rather than a pass fix turned off: RM97 declared the leaking-transport class closed
    while `OntologyClient` kept leaking `HTTPStatusError` from both its methods for a whole release,
    because RM97's own guard walked a hand-written list of eight modules that did not include
    `identifiers`. Patching `check_identifiers` itself to raise `httpx` — which is what this test did
    first — kept passing against a stub of the defect after the defect was gone. Breaking the
    transport underneath the real client is what tells the two apart.
    """
    import httpx
    from just_dna_enricher.identifiers import OntologyClient

    from just_dna_registry.services import enrich as enrich_service

    class _Dead(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

    def unreachable_ontology():
        client = OntologyClient()
        client._client = httpx.Client(transport=_Dead())
        return _bundle(ontology=client)

    monkeypatch.setattr(enrich_service, "shared_lookup_clients", unreachable_ontology)
    code, body = _check(_no_live_lookups(tmp_path), offline=False, identifiers=True)
    assert code == 200, body

    check = body["enrichment"]["identifiers"]
    assert check["unreachable"] == ["ols4/hgnc"]
    assert check["stale_traits"] == [] and check["stale_genes"] == []
    assert check["clean"] is None  # already tri-state here, and stays that way
