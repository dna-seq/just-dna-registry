"""Publish recovery in the client (0.28): a large publish can outlive its connection, and the server
finishes and indexes the version while the client sees `RemoteProtocolError`. `publish()` then polls
the version's manifest for a stated time and returns it when it appears with the inputs this call
sent. Driven through a transport that delivers the upload to the real app and then drops the
response, so the comparison runs against what the server really stored."""

import io
import tarfile
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sdk_transport import sdk_transport
from typer.testing import CliRunner

from just_dna_registry import client_cli
from just_dna_registry.client import RegistryClient, sent_input_hashes

# `version: 1` is an integer, which the server stringifies in the `module:` block: the stored
# `module_spec.yaml` then differs from the sent one, as it does for every sample spec in data/input.
_MODULE_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  version: 1
  title: Coronary
  description: Coronary artery disease risk
  report_title: Coronary
  icon: heart
  color: "#db2828"
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category\n"
    "rs4244285,10,94781859,G,A,A/G,{weight},risk,het,CYP2C19,cyp2c19\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,1,T,0.05,E,U\n"


def _spec(root: Path, weight: str = "-0.8") -> Path:
    root.mkdir(parents=True)
    (root / "module_spec.yaml").write_text(_MODULE_YAML)
    (root / "variants.csv").write_text(_VARIANTS.format(weight=weight))
    (root / "studies.csv").write_text(_STUDIES)
    return root


class _DropTheResponse(httpx.BaseTransport):
    """Delivers a publish to the app (or not, with `deliver=False`), then fails as a proxy would."""

    def __init__(self, inner: httpx.BaseTransport, *, deliver: bool = True,
                 error: type[httpx.TransportError] = httpx.RemoteProtocolError) -> None:
        self.inner, self.deliver, self.error = inner, deliver, error
        self.polls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/versions"):
            if self.deliver:
                self.inner.handle_request(request)
            raise self.error("Server disconnected without sending a response.", request=request)
        if request.url.path.endswith("/manifest"):
            self.polls += 1
        return self.inner.handle_request(request)


def _sdk(client: TestClient, key: str, **drop: object) -> tuple[RegistryClient, _DropTheResponse]:
    transport = _DropTheResponse(sdk_transport(client), **drop)  # type: ignore[arg-type]
    sdk = RegistryClient("http://testserver", token=key, transport=transport, check_version=False)
    sdk.recover_poll_seconds = 0.05
    return sdk, transport


def test_a_lost_response_returns_the_version_that_landed(
    client: TestClient, api_key: str, tmp_path: Path
) -> None:
    sdk, transport = _sdk(client, api_key)
    manifest = sdk.publish("just-dna-seq", "coronary", "1.0.0", _spec(tmp_path / "spec"), recover_within=5)
    stored = client.get("/api/v1/modules/just-dna-seq/coronary/versions/1.0.0/manifest").json()
    assert manifest.artifact.digest == stored["artifact"]["digest"] and transport.polls >= 1
    # The yaml really was rewritten, so the recovery succeeded on the tables, not on every input.
    sent = sent_input_hashes(tmp_path / "spec")
    yaml_entry = next(i for i in manifest.inputs if i.name == "module_spec.yaml")
    assert yaml_entry.sha256 != sent["module_spec.yaml"]


@pytest.mark.parametrize("form", ["pack", "archive"])
def test_the_archive_forms_recover_by_the_names_the_server_records(
    client: TestClient, api_key: str, tmp_path: Path, form: str
) -> None:
    spec = _spec(tmp_path / "spec")
    if form == "archive":  # members under a folder, which the server hoists to the root
        archive = tmp_path / "spec.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in spec.iterdir():
                data = path.read_bytes()
                info = tarfile.TarInfo(f"authored/{path.name}")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        spec = archive
        assert "variants.csv" in sent_input_hashes(archive)
    sdk, _ = _sdk(client, api_key)
    manifest = sdk.publish("just-dna-seq", "coronary", "1.0.0", spec, pack=form == "pack", recover_within=5)
    assert manifest.identity.canonical_id == "just-dna-seq/coronary@1.0.0"


def test_a_version_that_landed_with_other_tables_is_not_claimed(
    client: TestClient, api_key: str, tmp_path: Path
) -> None:
    RegistryClient(
        "http://testserver", token=api_key, transport=sdk_transport(client), check_version=False
    ).publish("just-dna-seq", "coronary", "1.0.0", _spec(tmp_path / "theirs"))
    sdk, _ = _sdk(client, api_key, deliver=False)
    with pytest.raises(httpx.RemoteProtocolError) as lost:
        sdk.publish("just-dna-seq", "coronary", "1.0.0", _spec(tmp_path / "mine", weight="-0.7"),
                    recover_within=5)
    assert "variants.csv differ" in "\n".join(lost.value.__notes__)


def test_a_version_that_never_appears_gives_up_at_the_deadline_and_says_so(
    client: TestClient, api_key: str, tmp_path: Path
) -> None:
    sdk, transport = _sdk(client, api_key, deliver=False)
    started = time.monotonic()
    with pytest.raises(httpx.RemoteProtocolError) as lost:
        sdk.publish("just-dna-seq", "coronary", "1.0.0", _spec(tmp_path / "spec"), recover_within=0.3)
    assert time.monotonic() - started >= 0.3 and transport.polls >= 2
    assert "gave up after 0.3s" in "\n".join(lost.value.__notes__)


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.WriteError])
def test_a_request_that_never_left_is_not_waited_on(
    client: TestClient, api_key: str, tmp_path: Path, error: type[httpx.TransportError]
) -> None:
    sdk, transport = _sdk(client, api_key, deliver=False, error=error)
    started = time.monotonic()
    with pytest.raises(error):
        sdk.publish("just-dna-seq", "coronary", "1.0.0", _spec(tmp_path / "spec"), recover_within=60)
    assert time.monotonic() - started < 5 and transport.polls == 0


def test_recovery_off_raises_at_once(client: TestClient, api_key: str, tmp_path: Path) -> None:
    sdk, transport = _sdk(client, api_key)
    with pytest.raises(httpx.RemoteProtocolError):
        sdk.publish("just-dna-seq", "coronary", "1.0.0", _spec(tmp_path / "spec"), recover_within=0)
    assert transport.polls == 0


def test_the_cli_prints_what_it_gave_up_on(
    client: TestClient, api_key: str, tmp_path: Path, monkeypatch
) -> None:
    def made(*_a: object, **_k: object) -> RegistryClient:
        cli_client = client_cli._CliClient(
            "http://testserver", api_key,
            transport=_DropTheResponse(sdk_transport(client), deliver=False), check_version=False,
        )
        cli_client.recover_poll_seconds = 0.05
        return cli_client

    monkeypatch.setattr(client_cli, "_client", made)
    result = CliRunner().invoke(client_cli.app, [
        "publish", "just-dna-seq", "coronary", "1.0.0", str(_spec(tmp_path / "spec")),
        "--recover-within", "0.2", "--token", api_key,
    ])
    assert result.exit_code == 1, result.output
    assert "connection lost: RemoteProtocolError" in result.stdout and "gave up after 0.2s" in result.stdout
