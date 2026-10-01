"""
Knowledge-base uploads must not be read into memory whole before their size
is checked: oversized requests are refused from Content-Length before the
body is parsed, and otherwise copied to disk in chunks with a hard cap.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def kb():
    mock = MagicMock(is_available=True)
    mock.ingest = AsyncMock(return_value=3)
    with patch("app.api.dependencies.get_knowledge_base", return_value=mock):
        yield mock


@pytest.fixture(autouse=True)
def one_mb_limit(monkeypatch):
    monkeypatch.setattr(settings, "KB_MAX_FILE_MB", 1)
    app.state.limiter.reset()


client = TestClient(app, raise_server_exceptions=False)


def test_oversized_upload_is_refused_before_ingest(kb):
    payload = b"a" * (2 * 1024 * 1024)
    resp = client.post("/knowledge/upload", files={"file": ("big.txt", payload, "text/plain")})

    assert resp.status_code == 413
    kb.ingest.assert_not_called()


def test_declared_oversized_body_is_refused_without_reading_it(kb):
    """Content-Length alone is enough — the (unsent) body is never parsed."""
    received = []

    def body():
        received.append(True)
        yield b"x" * 10

    resp = client.post(
        "/knowledge/upload",
        content=body(),
        headers={"Content-Type": "multipart/form-data; boundary=x", "Content-Length": str(50 * 1024 * 1024)},
    )
    assert resp.status_code == 413
    kb.ingest.assert_not_called()


def test_file_within_the_limit_is_ingested_from_a_temp_copy(kb):
    payload = b"Quarterly revenue analysis. " * 10_000  # ~280 KB
    resp = client.post("/knowledge/upload", files={"file": ("report.txt", payload, "text/plain")})

    assert resp.status_code == 200 and resp.json()["chunks_indexed"] == 3
    tmp_path, metadata = kb.ingest.call_args.args
    assert metadata["source"] == "report.txt"


def test_file_just_over_the_limit_is_caught_in_the_route(kb):
    """Slips past the Content-Length guard (within its framing allowance) but the
    route still measures the file itself."""
    payload = b"a" * (1024 * 1024 + 30 * 1024)
    resp = client.post("/knowledge/upload", files={"file": ("edge.txt", payload, "text/plain")})

    assert resp.status_code == 413
    kb.ingest.assert_not_called()
