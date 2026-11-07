"""`REGISTRY_LOG_FILE` (0.28.4): the server keeps a log file of its own, since `serve` is not a run.

Driven through the real `create_app` (which configures the root logger) and the real uvicorn config the
`serve` command hands uvicorn, so the file catches both the app's records and uvicorn's own, which do not
propagate to the root and are the only record of a worker that failed to import the app.
"""

import logging
import logging.config
from pathlib import Path

from fastapi.testclient import TestClient

from just_dna_registry.api.app import create_app
from just_dna_registry.config import Settings
from just_dna_registry.logging_setup import uvicorn_log_config


def _settings(tmp_path: Path, **extra: object) -> Settings:
    return Settings(
        db_path=tmp_path / "registry.db", storage_backend="local",
        local_storage_dir=tmp_path / "artifacts", **extra,
    )


def _flush() -> None:
    for logger in (logging.getLogger(), logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")):
        for handler in logger.handlers:
            handler.flush()


def test_the_app_and_uvicorn_both_reach_the_file_with_keys_redacted(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "registry.log"
    settings = _settings(tmp_path, log_file=log)
    logging.config.dictConfig(uvicorn_log_config(settings))
    try:
        TestClient(create_app(settings)).get("/health")
        logging.getLogger("just_dna_registry.test").warning("key mk_live_abcdef123 seen")
        logging.getLogger("uvicorn.error").error("Error loading ASGI app")
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "1.2.3.4", "GET", "/health", "1.1", 200)
        _flush()
        text = log.read_text()
    finally:
        logging.config.dictConfig(uvicorn_log_config(_settings(tmp_path)))
        logging.basicConfig(force=True)
    assert "just_dna_registry.test | key mk_live_…(redacted) seen" in text, text
    assert "mk_live_abcdef123" not in text
    assert "uvicorn.error | Error loading ASGI app" in text, text
    assert 'uvicorn.access | 1.2.3.4 - "GET /health HTTP/1.1" 200' in text, text


def test_unset_writes_no_file_and_leaves_uvicorn_as_it_ships(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    config = uvicorn_log_config(settings)
    assert "registry_file" not in config["handlers"]
    assert config["loggers"]["uvicorn"]["handlers"] == ["default"]
    create_app(settings)
    assert not [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]


def test_it_rotates(tmp_path: Path) -> None:
    log = tmp_path / "registry.log"
    create_app(_settings(tmp_path, log_file=log, log_file_max_bytes=2000, log_file_backups=2))
    try:
        for n in range(200):
            logging.getLogger("just_dna_registry.test").warning("line %d %s", n, "x" * 40)
        _flush()
    finally:
        logging.basicConfig(force=True)
    assert {p.name for p in tmp_path.glob("registry.log*")} == {"registry.log", "registry.log.1", "registry.log.2"}
    assert log.stat().st_size <= 2000
