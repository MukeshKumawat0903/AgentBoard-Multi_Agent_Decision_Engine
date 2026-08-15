# ============================================================
# Stage 1 — builder: install Python dependencies into a venv
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# System libraries required by project dependencies:
#   weasyprint  → libglib, libpango, libcairo, libffi, libgdk-pixbuf
#   numexpr / sentence-transformers → libgomp (OpenMP)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libglib2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libffi-dev \
        libgdk-pixbuf-xlib-2.0-0 \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create isolated virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first (cached layer — only invalidated when requirements.txt changes)
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ============================================================
# Stage 2 — runtime: lean final image
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system libraries (no compilers needed in final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-xlib-2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY app/       ./app/
COPY alembic/   ./alembic/
COPY alembic.ini .

# Persistent data directory (SQLite DB + knowledge base)
# Mount a named volume here in production: -v agentboard-data:/data
RUN mkdir -p /data/kb
ENV DATABASE_URL=/data/agentboard.db
ENV KNOWLEDGE_BASE_DIR=/data/kb

# Security: run as non-root
RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser \
    && chown -R appuser:appgroup /app /data

USER appuser

EXPOSE 8000

# Health check — maps to the /health endpoint in main.py
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
