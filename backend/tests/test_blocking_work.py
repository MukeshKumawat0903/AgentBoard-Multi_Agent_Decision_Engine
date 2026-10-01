"""
Slow, blocking work must stay off the event loop: loading the knowledge base
(Chroma + embedding model, possibly a first-time download) and rendering PDFs.
Otherwise every live SSE stream stalls while it runs, and container startup
waits for the model download.
"""

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
from fastapi.testclient import TestClient

import app.services.retriever as retriever
from app.core.config import settings
from app.db.crud import save_decision
from app.main import app
from app.schemas.final_decision import FinalDecision
from app.services.retriever import KnowledgeBase, KnowledgeBaseUnavailable


def _kb(tmp_path) -> KnowledgeBase:
    return KnowledgeBase(persist_dir=str(tmp_path / "kb"))


def test_is_available_never_loads_anything(tmp_path):
    kb = _kb(tmp_path)
    with patch.object(retriever, "_dependencies_installed", return_value=True), \
         patch.object(KnowledgeBase, "_ensure_available", side_effect=AssertionError("loaded!")):
        assert kb.is_available is True


@pytest.mark.anyio
async def test_failed_init_is_logged_once_and_not_retried_immediately(tmp_path, monkeypatch, caplog):
    kb = _kb(tmp_path)
    calls = {"n": 0}

    def no_chroma():
        calls["n"] += 1
        raise RuntimeError("chromadb is required for the knowledge base")

    monkeypatch.setattr(retriever, "_load_chroma", no_chroma)
    assert await kb.ensure_ready() is False
    assert await kb.ensure_ready() is False
    assert await kb.retrieve("anything") == []
    assert calls["n"] == 1
    assert kb.is_available is False
    assert any("chromadb is required" in str(getattr(r, "error", "")) for r in caplog.records)

    monkeypatch.setattr(retriever, "_INIT_RETRY_AFTER_SECONDS", 0.0)
    assert await kb.ensure_ready() is False
    assert calls["n"] == 2  # retried once the window passed


@pytest.mark.anyio
async def test_ingest_raises_a_typed_error_when_unavailable(tmp_path, monkeypatch):
    kb = _kb(tmp_path)
    monkeypatch.setattr(retriever, "_load_chroma", MagicMock(side_effect=RuntimeError("no chromadb")))
    with pytest.raises(KnowledgeBaseUnavailable):
        await kb.ingest(str(tmp_path / "doc.txt"), {"source": "doc.txt"})


def test_upload_reports_501_when_the_kb_cannot_start():
    kb = MagicMock(is_available=True)
    kb.ingest = AsyncMock(side_effect=KnowledgeBaseUnavailable("model download failed"))
    app.state.limiter.reset()
    with patch("app.api.dependencies.get_knowledge_base", return_value=kb):
        resp = TestClient(app).post("/knowledge/upload", files={"file": ("a.txt", b"hello world", "text/plain")})
    assert resp.status_code == 501


def test_startup_does_not_wait_for_the_embedding_model():
    def slow_init(self):
        time.sleep(2.0)

    with patch.object(retriever, "_dependencies_installed", return_value=True), \
         patch.object(KnowledgeBase, "_ensure_available", slow_init):
        started = time.perf_counter()
        with TestClient(app) as client:
            ready_after = time.perf_counter() - started
            assert client.get("/health").status_code == 200
    assert ready_after < 1.5


@pytest.mark.anyio
async def test_pdf_export_renders_off_the_event_loop_thread():
    decision = FinalDecision(
        thread_id="pdf-1", decision="Proceed", rationale_summary="why", confidence_score=0.8,
        agreement_score=0.7, total_rounds=1, termination_reason="consensus_reached",
    )
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await save_decision(db, decision, "Should we expand?")

    loop_thread = threading.get_ident()
    seen: dict = {}

    def fake_render_pdf(_decision):
        seen["thread"] = threading.get_ident()
        return b"%PDF-1.4 fake"

    from httpx import ASGITransport, AsyncClient

    with patch("app.services.exporter.render_pdf", side_effect=fake_render_pdf):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
            resp = await client.get("/decision/pdf-1/export?format=pdf")

    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    assert seen["thread"] != loop_thread
    await asyncio.sleep(0)
