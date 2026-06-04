"""
Knowledge Base RAG service for AgentBoard.

Uses ChromaDB as a persistent vector store with sentence-transformers
for embedding.  Documents are chunked, embedded, and stored on disk.
At debate time, the ``retrieve()`` method returns top-k relevant hits
that are injected into agent prompts.

Usage::

    from app.services.retriever import knowledge_base

    # Ingest a document
    n = await knowledge_base.ingest("path/to/file.pdf", {"source": "report"})

    # Retrieve context for a query
    hits = await knowledge_base.retrieve("Should we expand to Asia?")
    for hit in hits:
        print(hit["text"], hit["source"], hit["score"])
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("agentboard.retriever")

# ---------------------------------------------------------------------------
# Module-level shared embedder cache (R5)
# Keyed by model name; both KnowledgeBase and SemanticConsensusEngine use this
# so the model weights are loaded only once.
# ---------------------------------------------------------------------------

_embedder_lock = threading.Lock()
_embedder_cache: dict[str, Any] = {}


def get_shared_embedder(model_name: str) -> Any:
    """Return a cached SentenceTransformer instance, loading it on first call."""
    if model_name not in _embedder_cache:
        with _embedder_lock:
            if model_name not in _embedder_cache:
                try:
                    from sentence_transformers import SentenceTransformer  # type: ignore[import]
                    logger.info("Loading sentence-transformer model", extra={"model": model_name})
                    _embedder_cache[model_name] = SentenceTransformer(model_name)
                except ImportError as exc:
                    raise RuntimeError(
                        "sentence-transformers is required for the knowledge base.  "
                        "Install it with: pip install sentence-transformers"
                    ) from exc
    return _embedder_cache[model_name]


# ---------------------------------------------------------------------------
# Separator-aware recursive text splitter (R4)
# ---------------------------------------------------------------------------

_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _chunk_text(text: str, chunk_size: int = 1_000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks at natural boundaries (R4).

    Falls back through paragraph → newline → sentence → word → char.
    Guards the chunk_size <= overlap edge case (R4 fix).
    """
    if not text.strip():
        return []
    if chunk_size <= overlap:
        raise ValueError(f"chunk_size ({chunk_size}) must be greater than overlap ({overlap})")
    return _recursive_split(text.strip(), _SEPARATORS, chunk_size, overlap)


def _recursive_split(text: str, separators: list[str], chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # Find a separator that splits this text
    sep = ""
    remaining_seps: list[str] = []
    for i, s in enumerate(separators):
        if s == "" or s in text:
            sep = s
            remaining_seps = separators[i + 1 :]
            break

    raw_pieces = text.split(sep) if sep else list(text)

    merged: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for piece in raw_pieces:
        joiner_len = len(sep) if current_parts else 0
        if current_len + joiner_len + len(piece) > chunk_size and current_parts:
            chunk = sep.join(current_parts)
            if len(chunk) > chunk_size:
                merged.extend(_recursive_split(chunk, remaining_seps, chunk_size, overlap))
            else:
                merged.append(chunk)
            # Retain overlap from the tail of current_parts
            tail = sep.join(current_parts)[-overlap:] if overlap else ""
            current_parts = [tail] if tail else []
            current_len = len(tail)

        if len(piece) > chunk_size:
            if current_parts:
                chunk = sep.join(current_parts)
                if chunk.strip():
                    merged.append(chunk)
                current_parts, current_len = [], 0
            merged.extend(_recursive_split(piece, remaining_seps, chunk_size, overlap))
        else:
            current_parts.append(piece)
            current_len += len(sep) * (1 if len(current_parts) > 1 else 0) + len(piece)

    if current_parts:
        chunk = sep.join(current_parts)
        if len(chunk) > chunk_size:
            merged.extend(_recursive_split(chunk, remaining_seps, chunk_size, overlap))
        elif chunk.strip():
            merged.append(chunk)

    return [c for c in merged if c.strip()]


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def _load_file(file_path: str) -> str:
    """Extract text from PDF, TXT, or Markdown files."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore[import]
            reader = pypdf.PdfReader(file_path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError as exc:
            raise RuntimeError(
                "pypdf is required for PDF ingestion.  "
                "Install it with: pip install pypdf"
            ) from exc

    return path.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# ChromaDB loader
# ---------------------------------------------------------------------------

def _load_chroma() -> Any:
    """Lazy import to avoid startup failure when chromadb is not installed."""
    try:
        import chromadb  # type: ignore[import]
        return chromadb
    except ImportError as exc:
        raise RuntimeError(
            "chromadb is required for the knowledge base.  "
            "Install it with: pip install chromadb"
        ) from exc


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """
    Persistent vector store backed by ChromaDB.

    Provides ``ingest()``, ``retrieve()``, ``list_documents()``,
    and ``delete_document()`` operations.

    Instantiated once at application startup as a module singleton.
    Thread-safe: writes are serialised by an asyncio lock; init is
    guarded by a threading lock for concurrent first-use (R8).
    """

    def __init__(
        self,
        persist_dir: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        chunk_size: int = 1_000,
        chunk_overlap: int = 200,
        similarity_threshold: float = 0.30,
        top_k: int = 5,
    ) -> None:
        self._persist_dir = persist_dir
        self._embedding_model_name = embedding_model
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._similarity_threshold = similarity_threshold
        self._top_k = top_k

        self._client: Any = None
        self._collection: Any = None
        self._lock = asyncio.Lock()          # serialise async writes
        self._init_lock = threading.Lock()   # guard sync init (R8)
        self._available = False

        # Per-instance retrieval cache: keyed by (query, k) → list[dict] (R6)
        self._retrieve_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Lazy initialisation (R8: thread-safe double-check)
    # ------------------------------------------------------------------

    def _ensure_available(self) -> None:
        if self._available:
            return
        with self._init_lock:
            if self._available:
                return
            chromadb = _load_chroma()
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._collection = self._client.get_or_create_collection(
                name="agentboard_docs",
                metadata={"hnsw:space": "cosine"},
            )
            # Load via shared cache (R5)
            get_shared_embedder(self._embedding_model_name)
            self._available = True

    @property
    def is_available(self) -> bool:
        """Return True if chromadb and sentence-transformers are installed."""
        try:
            self._ensure_available()
            return True
        except (RuntimeError, Exception):  # noqa: BLE001  (R8: tolerate Chroma errors)
            return False

    async def warm(self) -> None:
        """Pre-load the embedding model and Chroma client in a thread (R8)."""
        await asyncio.to_thread(self._ensure_available)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest(self, file_path: str, metadata: dict[str, Any] | None = None) -> int:
        """Chunk, embed, and store a document.  Returns the number of chunks ingested."""
        async with self._lock:
            self._ensure_available()
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._ingest_sync, file_path, metadata or {}
            )
            self._retrieve_cache.clear()  # invalidate cache on new content (R6)
            return result

    def _ingest_sync(self, file_path: str, metadata: dict[str, Any]) -> int:
        text = _load_file(file_path)
        chunks = _chunk_text(text, self._chunk_size, self._chunk_overlap)
        if not chunks:
            return 0

        doc_name = Path(file_path).name
        content_hash = hashlib.md5(text.encode()).hexdigest()[:12]

        # R2: delete stale chunks for this source before inserting
        existing = self._collection.get(where={"source": doc_name}, include=["metadatas"])
        old_ids = existing.get("ids") or []
        if old_ids:
            self._collection.delete(ids=old_ids)
            logger.info(
                "knowledge_base_stale_purged",
                extra={"file": doc_name, "removed": len(old_ids)},
            )

        doc_ids = [f"{content_hash}_chunk_{i}" for i in range(len(chunks))]
        chunk_metadata = [
            {**metadata, "source": doc_name, "chunk": i, "content_hash": content_hash}
            for i in range(len(chunks))
        ]
        embedder = get_shared_embedder(self._embedding_model_name)
        embeddings = embedder.encode(chunks, show_progress_bar=False).tolist()

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

    async def retrieve(
        self, query: str, k: int | None = None
    ) -> list[dict[str, Any]]:
        """Return top-k relevant hits as ``{text, source, score}`` dicts (R6).

        Only hits with cosine similarity ≥ similarity_threshold are returned.
        Results are cached per (query, k) for the life of this instance (R6).
        Returns an empty list if the knowledge base is empty or unavailable.
        """
        if not self.is_available:
            return []
        effective_k = k if k is not None else self._top_k
        cache_key = (query, effective_k)
        if cache_key in self._retrieve_cache:
            return self._retrieve_cache[cache_key]
        result = await asyncio.get_event_loop().run_in_executor(
            None, self._retrieve_sync, query, effective_k
        )
        self._retrieve_cache[cache_key] = result
        return result

    def _retrieve_sync(self, query: str, k: int) -> list[dict[str, Any]]:
        collection_count = self._collection.count()
        if collection_count == 0:
            return []

        embedder = get_shared_embedder(self._embedding_model_name)
        query_embedding = embedder.encode([query], show_progress_bar=False).tolist()
        result = self._collection.query(
            query_embeddings=query_embedding,
            n_results=min(k, collection_count),
            include=["documents", "distances", "metadatas"],
        )
        docs = result.get("documents", [[]])[0]
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]

        hits: list[dict[str, Any]] = []
        for doc, dist, meta in zip(docs, distances, metadatas):
            score = 1.0 - dist  # cosine distance → similarity
            if score >= self._similarity_threshold:
                hits.append({
                    "text": doc,
                    "source": meta.get("source", "unknown"),
                    "score": round(score, 4),
                })

        # R7: retrieval observability
        top_score = hits[0]["score"] if hits else 0.0
        logger.info(
            "kb_retrieve",
            extra={
                "query_preview": query[:80],
                "n_candidates": len(docs),
                "n_kept": len(hits),
                "top_score": top_score,
                "threshold": self._similarity_threshold,
            },
        )
        return hits

    async def list_documents(self) -> list[dict[str, Any]]:
        """Return unique document names and their chunk counts."""
        if not self.is_available:
            return []
        return await asyncio.get_event_loop().run_in_executor(None, self._list_sync)

    def _list_sync(self) -> list[dict[str, Any]]:
        result = self._collection.get(include=["metadatas"])
        metadatas = result.get("metadatas") or []
        counts: dict[str, int] = {}
        for m in metadatas:
            src = m.get("source", "unknown")
            counts[src] = counts.get(src, 0) + 1
        return [{"name": name, "chunks": cnt} for name, cnt in sorted(counts.items())]

    async def delete_document(self, doc_name: str) -> int:
        """Delete all chunks for a given document.  Returns deleted count."""
        if not self.is_available:
            return 0
        async with self._lock:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._delete_sync, doc_name
            )
            self._retrieve_cache.clear()  # invalidate cache after deletion (R6)
            return result

    def _delete_sync(self, doc_name: str) -> int:
        result = self._collection.get(where={"source": doc_name}, include=["metadatas"])
        ids = result.get("ids") or []
        if ids:
            self._collection.delete(ids=ids)
        logger.info(
            "knowledge_base_deleted",
            extra={"doc": doc_name, "chunks_deleted": len(ids)},
        )
        return len(ids)
