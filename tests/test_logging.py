"""Debug-logging configuration + request tracing (behind REGISTRY_DEBUG)."""

import importlib.util
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.logging_setup import configure_logging


def test_debug_sets_root_to_debug() -> None:
    configure_logging(Settings(debug=True))
    assert logging.getLogger().level == logging.DEBUG


def test_non_debug_uses_log_level() -> None:
    configure_logging(Settings(debug=False, log_level="WARNING"))
    assert logging.getLogger().level == logging.WARNING


def test_app_boots_and_traces_requests_in_debug(tmp_path: Path, capsys) -> None:
    app = create_app(
        Settings(debug=True, db_path=tmp_path / "m.db", local_storage_dir=tmp_path / "a")
    )
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    out = capsys.readouterr().out
    assert "GET /health -> 200" in out  # request tracing lands on stdout in debug


def test_every_installed_http_transport_is_quiet_in_debug() -> None:
    """Debug logging leaves each installed HTTP transport's loggers at WARNING.

    huggingface-hub 2.0 sends its requests through `httpx2`/`httpcore2`, whose loggers are named
    after those packages, so quieting only `httpx`/`httpcore` logged every Hub request again under
    `REGISTRY_DEBUG` (the liaison's H2). Checked on a child logger too, since `httpcore2` logs from
    `httpcore2.connection` and friends.
    """
    transports = [
        name for name in ("httpx", "httpcore", "httpx2", "httpcore2")
        if importlib.util.find_spec(name) is not None
    ]
    # Floor: hf-hub 2.0 brings the `2` pair beside the original pair.
    assert len(transports) >= 4, transports
    configure_logging(Settings(debug=True))
    for name in transports:
        for logger in (name, f"{name}.connection"):
            assert logging.getLogger(logger).getEffectiveLevel() >= logging.WARNING, logger
