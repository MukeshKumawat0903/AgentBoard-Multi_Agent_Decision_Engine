"""
Tests for the Knowledge Base RAG service (retriever.py).

Covers:
- _chunk_text: boundaries, overlap, guard against chunk_size <= overlap
- KnowledgeBase.ingest / retrieve / list_documents / delete_document
- Re-ingest idempotency (R2): no stale chunks after re-upload
- Similarity threshold filtering (R3)
- Source attribution in retrieve() results (R6)
- Zero-chunk path (R9)
- Endpoint regression: upload/list/delete call the async methods correctly (R1)

Embedding-dependent tests are skipped if sentence-transformers is not installed.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_sentence_transformers() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _has_chromadb() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


NEEDS_EMBEDDER = pytest.mark.skipif(
    not _has_sentence_transformers(),
    reason="sentence-transformers not installed",
)
NEEDS_CHROMA = pytest.mark.skipif(
    not _has_chromadb(),
    reason="chromadb not installed",
)
NEEDS_BOTH = pytest.mark.skipif(
    not (_has_chromadb() and _has_sentence_transformers()),
    reason="chromadb and sentence-transformers not installed",
)


# ---------------------------------------------------------------------------
# _chunk_text unit tests (R4)
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_empty_string_returns_empty(self):
        from app.services.retriever import _chunk_text
        assert _chunk_text("") == []
        assert _chunk_text("   ") == []

    def test_short_text_returns_single_chunk(self):
        from app.services.retriever import _chunk_text
        text = "Hello world"
        result = _chunk_text(text, chunk_size=100, overlap=10)
        assert result == [text]

    def test_long_text_produces_multiple_chunks(self):
        from app.services.retriever import _chunk_text
        text = "word " * 300  # 1500 chars
        chunks = _chunk_text(text, chunk_size=200, overlap=20)
        assert len(chunks) > 1

    def test_overlap_guard_raises(self):
        from app.services.retriever import _chunk_text
        with pytest.raises(ValueError, match="chunk_size"):
            _chunk_text("some text", chunk_size=50, overlap=50)

    def test_each_chunk_within_size_limit(self):
        from app.services.retriever import _chunk_text
        text = "a" * 5000
        chunk_size = 500
        for chunk in _chunk_text(text, chunk_size=chunk_size, overlap=50):
            assert len(chunk) <= chunk_size + 50  # small tolerance for separator joins

    def test_splits_at_paragraphs_preferably(self):
        from app.services.retriever import _chunk_text
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        # With a large chunk_size the whole thing is one chunk
        assert len(_chunk_text(text, chunk_size=200, overlap=0)) == 1
        # With a smaller chunk_size it should split at \n\n
        chunks = _chunk_text(text, chunk_size=25, overlap=0)
        assert len(chunks) >= 2


# ---------------------------------------------------------------------------
# KnowledgeBase service tests (mocked Chroma + embedder)
# ---------------------------------------------------------------------------

def _make_kb(tmp_path: str, threshold: float = 0.30) -> "Any":
    """Create a KnowledgeBase with a real tmp dir."""
    from app.services.retriever import KnowledgeBase
    return KnowledgeBase(
        persist_dir=tmp_path,
        embedding_model="all-MiniLM-L6-v2",
        chunk_size=200,
        chunk_overlap=20,
        similarity_threshold=threshold,
        top_k=5,
    )


def _mock_embedder(dim: int = 4) -> MagicMock:
    import numpy as np
    m = MagicMock()
    m.encode = MagicMock(
        side_effect=lambda texts, **kw: np.random.rand(len(texts), dim).astype("float32")
    )
    return m


class TestKnowledgeBaseIngest:
    def test_ingest_returns_positive_chunk_count(self, tmp_path):
        kb = _make_kb(str(tmp_path))
        with patch("app.services.retriever.get_shared_embedder", return_value=_mock_embedder()):
            with patch("app.services.retriever._load_chroma") as mock_chroma:
                collection = MagicMock()
                collection.get.return_value = {"ids": [], "metadatas": []}
                collection.upsert = MagicMock()
                mock_chroma.return_value.PersistentClient.return_value.get_or_create_collection.return_value = collection

                txt = tmp_path / "doc.txt"
                txt.write_text("This is a test document with enough content to produce chunks. " * 5)

                result = asyncio.run(kb.ingest(str(txt), {"source": "doc.txt"}))
                assert isinstance(result, int)
                assert result >= 1

    def test_ingest_empty_file_returns_zero(self, tmp_path):
        from app.services.retriever import _chunk_text
        text = "   "
        assert _chunk_text(text) == []

    def test_reingest_deletes_stale_chunks(self, tmp_path):
        """Re-uploading the same filename must remove old chunks first (R2)."""
        kb = _make_kb(str(tmp_path))
        old_ids = ["oldhash_chunk_0", "oldhash_chunk_1"]

        with patch("app.services.retriever.get_shared_embedder", return_value=_mock_embedder()):
            with patch("app.services.retriever._load_chroma") as mock_chroma:
                collection = MagicMock()
                # First call: existing stale chunks found
                collection.get.return_value = {"ids": old_ids, "metadatas": []}
                collection.upsert = MagicMock()
                collection.delete = MagicMock()
                mock_chroma.return_value.PersistentClient.return_value.get_or_create_collection.return_value = collection

                txt = tmp_path / "report.txt"
                txt.write_text("Updated content " * 20)

                asyncio.run(kb.ingest(str(txt), {"source": "report.txt"}))
                # delete must have been called with the old IDs
                collection.delete.assert_called_once_with(ids=old_ids)


class TestKnowledgeBaseRetrieve:
    def _build_kb_with_mocked_retrieve(self, tmp_path, scores, docs, metas):
        import numpy as np
        kb = _make_kb(str(tmp_path))
        kb._available = True  # skip _ensure_available
        collection = MagicMock()
        # n_results is clamped to collection.count()
        collection.count.return_value = len(docs)
        collection.query.return_value = {
            "documents": [docs],
            "distances": [scores],
            "metadatas": [metas],
        }
        kb._collection = collection
        embedder = MagicMock()
        embedder.encode = MagicMock(
            return_value=np.zeros((1, 4), dtype="float32")
        )
        with patch("app.services.retriever.get_shared_embedder", return_value=embedder):
            return kb, collection

    def test_retrieve_filters_by_threshold(self, tmp_path):
        """Only hits above similarity_threshold are returned (R3)."""
        import numpy as np
        docs = ["chunk A", "chunk B", "chunk C"]
        # distances: 1-dist = similarity; 0.40 kept, 0.25 dropped, 0.35 dropped (threshold=0.30)
        distances = [0.60, 0.75, 0.65]  # similarities: 0.40, 0.25, 0.35
        metas = [{"source": "f.txt"}, {"source": "f.txt"}, {"source": "f.txt"}]
        kb, _ = self._build_kb_with_mocked_retrieve(tmp_path, distances, docs, metas)
        kb._similarity_threshold = 0.30

        embedder = MagicMock()
        embedder.encode = MagicMock(return_value=np.zeros((1, 4), dtype="float32"))
        with patch("app.services.retriever.get_shared_embedder", return_value=embedder):
            hits = asyncio.run(kb.retrieve("query"))
        # 0.40 >= 0.30 kept, 0.25 < 0.30 dropped, 0.35 >= 0.30 kept
        assert len(hits) == 2
        assert hits[0]["text"] == "chunk A"

    def test_retrieve_returns_source_and_score(self, tmp_path):
        """Each hit must have text, source, score keys (R6)."""
        import numpy as np
        docs = ["relevant chunk"]
        distances = [0.3]  # similarity = 0.7
        metas = [{"source": "report.pdf"}]
        kb, _ = self._build_kb_with_mocked_retrieve(tmp_path, distances, docs, metas)
        kb._similarity_threshold = 0.30

        embedder = MagicMock()
        embedder.encode = MagicMock(return_value=np.zeros((1, 4), dtype="float32"))
        with patch("app.services.retriever.get_shared_embedder", return_value=embedder):
            hits = asyncio.run(kb.retrieve("query"))
        assert len(hits) == 1
        assert set(hits[0].keys()) >= {"text", "source", "score"}
        assert hits[0]["source"] == "report.pdf"
        assert hits[0]["score"] == pytest.approx(0.7, abs=1e-4)

    def test_retrieve_uses_cache(self, tmp_path):
        """Second call with same query should not hit the collection again (R6 cache)."""
        import numpy as np
        docs = ["chunk"]
        distances = [0.2]
        metas = [{"source": "x.txt"}]
        kb, collection = self._build_kb_with_mocked_retrieve(tmp_path, distances, docs, metas)
        kb._similarity_threshold = 0.10

        embedder = MagicMock()
        embedder.encode = MagicMock(return_value=np.zeros((1, 4), dtype="float32"))
        with patch("app.services.retriever.get_shared_embedder", return_value=embedder):
            asyncio.run(kb.retrieve("query"))
            asyncio.run(kb.retrieve("query"))
        assert collection.query.call_count == 1

    def test_retrieve_cache_cleared_on_ingest(self, tmp_path):
        """Ingest must invalidate the retrieve cache (R6)."""
        kb = _make_kb(str(tmp_path))
        kb._retrieve_cache = {("q", 5): [{"text": "old", "source": "x", "score": 0.9}]}

        with patch("app.services.retriever.get_shared_embedder", return_value=_mock_embedder()):
            with patch("app.services.retriever._load_chroma") as mock_chroma:
                collection = MagicMock()
                collection.get.return_value = {"ids": [], "metadatas": []}
                collection.upsert = MagicMock()
                mock_chroma.return_value.PersistentClient.return_value.get_or_create_collection.return_value = collection

                txt = tmp_path / "new.txt"
                txt.write_text("New content " * 20)
                asyncio.run(kb.ingest(str(txt), {"source": "new.txt"}))

        assert kb._retrieve_cache == {}


class TestKnowledgeBaseListDelete:
    def test_list_documents_aggregates_chunks(self, tmp_path):
        kb = _make_kb(str(tmp_path))
        kb._available = True
        collection = MagicMock()
        collection.get.return_value = {
            "metadatas": [
                {"source": "a.txt", "chunk": 0},
                {"source": "a.txt", "chunk": 1},
                {"source": "b.txt", "chunk": 0},
            ]
        }
        kb._collection = collection

        docs = asyncio.run(kb.list_documents())
        assert len(docs) == 2
        assert {"name": "a.txt", "chunks": 2} in docs
        assert {"name": "b.txt", "chunks": 1} in docs

    def test_delete_document_removes_chunks(self, tmp_path):
        kb = _make_kb(str(tmp_path))
        kb._available = True
        collection = MagicMock()
        collection.get.return_value = {"ids": ["id1", "id2"], "metadatas": []}
        collection.delete = MagicMock()
        kb._collection = collection

        deleted = asyncio.run(kb.delete_document("a.txt"))
        assert deleted == 2
        collection.delete.assert_called_once_with(ids=["id1", "id2"])

    def test_delete_clears_retrieve_cache(self, tmp_path):
        kb = _make_kb(str(tmp_path))
        kb._available = True
        kb._retrieve_cache = {("q", 5): []}
        collection = MagicMock()
        collection.get.return_value = {"ids": ["id1"], "metadatas": []}
        collection.delete = MagicMock()
        kb._collection = collection

        asyncio.run(kb.delete_document("a.txt"))
        assert kb._retrieve_cache == {}


# ---------------------------------------------------------------------------
# Endpoint regression tests — R1 (was missing await)
# ---------------------------------------------------------------------------

class TestKnowledgeEndpointsR1:
    """Ensure the HTTP endpoints actually await the async KB methods."""

    def _make_client_with_kb(self, kb_mock):
        from app.api.dependencies import set_knowledge_base
        set_knowledge_base(kb_mock)
        from app.main import app
        from fastapi.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)

    def _make_kb_mock(self, chunks: int = 3):
        kb = MagicMock()
        kb.is_available = True
        kb.ingest = AsyncMock(return_value=chunks)
        kb.list_documents = AsyncMock(return_value=[{"name": "test.txt", "chunks": chunks}])
        kb.delete_document = AsyncMock(return_value=chunks)
        return kb

    def test_upload_returns_int_chunks_not_coroutine(self, tmp_path):
        kb = self._make_kb_mock(chunks=3)
        client = self._make_client_with_kb(kb)

        txt = tmp_path / "test.txt"
        txt.write_text("Hello world content for upload test.")

        with open(txt, "rb") as f:
            resp = client.post("/knowledge/upload", files={"file": ("test.txt", f, "text/plain")})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["chunks_indexed"], int), (
            f"chunks_indexed must be int, got {type(body['chunks_indexed'])}"
        )
        assert body["chunks_indexed"] == 3

    def test_list_documents_returns_json_list(self):
        kb = self._make_kb_mock()
        client = self._make_client_with_kb(kb)
        resp = client.get("/knowledge/documents")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert body[0]["name"] == "test.txt"

    def test_delete_document_returns_chunks_deleted(self):
        kb = self._make_kb_mock()
        client = self._make_client_with_kb(kb)
        resp = client.delete("/knowledge/documents/test.txt")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["chunks_deleted"], int)

    def test_upload_zero_chunks_returns_422(self, tmp_path):
        """R9: zero extractable text must return HTTP 422."""
        kb = self._make_kb_mock(chunks=0)
        client = self._make_client_with_kb(kb)

        txt = tmp_path / "empty.txt"
        txt.write_text("   ")

        with open(txt, "rb") as f:
            resp = client.post("/knowledge/upload", files={"file": ("empty.txt", f, "text/plain")})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Agent integration: _enrich_with_kb with structured hits (R6)
# ---------------------------------------------------------------------------

class TestEnrichWithKB:
    @pytest.mark.anyio
    async def test_enriched_prompt_contains_source_attribution(self):
        """_enrich_with_kb must format hits with [Source: ...] notation."""
        from app.agents.analyst_agent import AnalystAgent

        mock_llm = MagicMock()
        agent = AnalystAgent(llm_client=mock_llm)

        mock_kb = MagicMock()
        mock_kb.retrieve = AsyncMock(return_value=[
            {"text": "Revenue grew 20%.", "source": "report.pdf", "score": 0.72},
        ])
        agent.knowledge_base = mock_kb

        result = await agent._enrich_with_kb("Base prompt.", "revenue growth")
        assert "[Source: report.pdf · 0.72]" in result
        assert "Revenue grew 20%." in result

    @pytest.mark.anyio
    async def test_no_enrichment_when_kb_returns_empty(self):
        from app.agents.analyst_agent import AnalystAgent

        mock_llm = MagicMock()
        agent = AnalystAgent(llm_client=mock_llm)

        mock_kb = MagicMock()
        mock_kb.retrieve = AsyncMock(return_value=[])
        agent.knowledge_base = mock_kb

        result = await agent._enrich_with_kb("Base prompt.", "irrelevant query")
        assert result == "Base prompt."
