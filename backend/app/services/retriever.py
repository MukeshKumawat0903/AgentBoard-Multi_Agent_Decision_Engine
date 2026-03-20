"""
Knowledge Base RAG service for AgentBoard.

Uses ChromaDB as a persistent vector store with sentence-transformers
for embedding.  Documents are chunked, embedded, and stored on disk.
At debate time, the ``retrieve()`` method returns top-k relevant chunks
that are injected into agent prompts.

Usage::

    from app.services.retriever import knowledge_base

    # Ingest a document
    n = await knowledge_base.ingest("path/to/file.pdf", {"source": "report"})

    # Retrieve context for a query
    chunks = await knowledge_base.retrieve("Should we expand to Asia?")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("agentboard.retriever")

_CHUNK_SIZE = 1_000
_CHUNK_OVERLAP = 200
_SIMILARITY_THRESHOLD = 0.50
_DEFAULT_K = 5


def _load_chroma():
    """Lazy import to avoid startup failure when chromadb is not installed."""
    try:
        import chromadb  # type: ignore[import]  # noqa: F401
        return chromadb
    except ImportError as exc:
        raise RuntimeError(
            "chromadb is required for the knowledge base.  "
            "Install it with: pip install chromadb"
        ) from exc


def _load_embedder(model_name: str):
    """Lazy import of sentence-transformers embedding model."""
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model_name)
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for the knowledge base.  "
            "Install it with: pip install sentence-transformers"
        ) from exc


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if not text.strip():
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
        if start >= len(text):
            break
    return chunks


def _load_file(file_path: str) -> str:
    """Extract text from PDF, TXT, or Markdown files."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore[import]
            reader = pypdf.PdfReader(file_path)
            return "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError as exc:
            raise RuntimeError(
                "pypdf is required for PDF ingestion.  "
                "Install it with: pip install pypdf"
            ) from exc

    # TXT / Markdown fallback
    return path.read_text(encoding="utf-8", errors="ignore")


class KnowledgeBase:
    """
    Persistent vector store backed by ChromaDB.

    Provides ``ingest()``, ``retrieve()``, ``list_documents()``,
    and ``delete_document()`` operations.

    Instantiated once at application startup as a module singleton.
    Thread-safe for concurrent reads; writes are serialised by a lock.
    """

    def __init__(self, persist_dir: str, embedding_model: str = "all-MiniLM-L6-v2") -> None:
        self._persist_dir = persist_dir
        self._embedding_model_name = embedding_model
        self._client: Any = None
        self._collection: Any = None
        self._embedder: Any = None
        self._lock = asyncio.Lock()
        self._available = False

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _ensure_available(self) -> None:
        """Lazily initialise ChromaDB and the embedding model on first use."""
        if self._available:
            return
        chromadb = _load_chroma()
        self._client = chromadb.PersistentClient(path=self._persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="agentboard_docs",
            metadata={"hnsw:space": "cosine"},
        )
        self._embedder = _load_embedder(self._embedding_model_name)
        self._available = True

    @property
    def is_available(self) -> bool:
        """Return True if chromadb and sentence-transformers are installed."""
        try:
            self._ensure_available()
            return True
        except RuntimeError:
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest(self, file_path: str, metadata: dict[str, Any] | None = None) -> int:
        """
        Chunk, embed, and store a document.

        Returns the number of chunks ingested.
        """
        async with self._lock:
            self._ensure_available()
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._ingest_sync, file_path, metadata or {}
            )

    def _ingest_sync(self, file_path: str, metadata: dict[str, Any]) -> int:
        text = _load_file(file_path)
        chunks = _chunk_text(text)
        if not chunks:
            return 0

        doc_name = Path(file_path).name
        doc_hash = hashlib.md5(text.encode()).hexdigest()[:12]

        doc_ids = [f"{doc_hash}_chunk_{i}" for i in range(len(chunks))]
        chunk_metadata = [{**metadata, "source": doc_name, "chunk": i} for i in range(len(chunks))]

        embeddings = self._embedder.encode(chunks, show_progress_bar=False).tolist()

        self._collection.upsert(
            ids=doc_ids,
            documents=chunks,
            metadatas=chunk_metadata,
            embeddings=embeddings,
        )
        logger.info(
            "knowledge_base_ingested",
            extra={"file": doc_name, "chunks": len(chunks)},
        )
        return len(chunks)

    async def retrieve(self, query: str, k: int = _DEFAULT_K) -> list[str]:
        """
        Return top-k relevant text chunks for the given query.

        Only chunks with cosine similarity > SIMILARITY_THRESHOLD are returned.
        Returns an empty list if the knowledge base is empty or unavailable.
        """
        if not self.is_available:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._retrieve_sync, query, k)

    def _retrieve_sync(self, query: str, k: int) -> list[str]:
        query_embedding = self._embedder.encode([query], show_progress_bar=False).tolist()
        result = self._collection.query(
            query_embeddings=query_embedding,
            n_results=min(k, max(self._collection.count(), 1)),
            include=["documents", "distances"],
        )
        docs = result.get("documents", [[]])[0]
        distances = result.get("distances", [[]])[0]

        # ChromaDB cosine distance → similarity = 1 - distance
        filtered: list[str] = [
            doc
            for doc, dist in zip(docs, distances)
            if (1.0 - dist) >= _SIMILARITY_THRESHOLD
        ]
        return filtered

    async def list_documents(self) -> list[dict[str, Any]]:
        """Return unique document names and their chunk counts."""
        if not self.is_available:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._list_sync)

    def _list_sync(self) -> list[dict[str, Any]]:
        result = self._collection.get(include=["metadatas"])
        metadatas = result.get("metadatas") or []
        counts: dict[str, int] = {}
        for m in metadatas:
            src = m.get("source", "unknown")
            counts[src] = counts.get(src, 0) + 1
        return [{"name": name, "chunks": cnt} for name, cnt in sorted(counts.items())]

    async def delete_document(self, doc_name: str) -> int:
        """Delete all chunks for a given document by source name.  Returns deleted count."""
        if not self.is_available:
            return 0
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._delete_sync, doc_name)

    def _delete_sync(self, doc_name: str) -> int:
        result = self._collection.get(
            where={"source": doc_name},
            include=["metadatas"],
        )
        ids = result.get("ids") or []
        if ids:
            self._collection.delete(ids=ids)
        logger.info(
            "knowledge_base_deleted",
            extra={"doc": doc_name, "chunks_deleted": len(ids)},
        )
        return len(ids)
