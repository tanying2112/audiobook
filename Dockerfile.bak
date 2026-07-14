# =============================================================================
# Multi-stage build: Builder (heavy compile toolchain) → Runner (lean runtime)
# Task 6.1 — limit image size + strip large model assets into a Volume.
# =============================================================================

# ---------- Stage 1: Builder ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Compile toolchain stays in Builder ONLY — never leaks into Runner (size win).
# build-essential / libffi-dev cover C-extension wheel fallback (cryptography/bcrypt).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker layer cache.
COPY requirements.txt .

# Install into a throwaway venv that Runner copies wholesale
# (no pip cache / build residue carried into the runtime image).
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------- Stage 2: Runner ----------
FROM python:3.11-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:$PATH" \
    # Task 6.1 asset-stripping: point asset_manager.CACHE_DIR at a Volume, not the image.
    AUDIOBOOK_STUDIO_MODEL_CACHE=/app/models_cache

# Runtime libs only (no build-essential / git / libffi-dev) — keeps the image lean.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        libsndfile1 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the pre-built venv from Builder.
COPY --from=builder /opt/venv /opt/venv

# Copy source (.dockerignore keeps tests / .git / node_modules / build artifacts / model cache out).
COPY . .

# Runtime directories incl. the model cache mount point.
RUN mkdir -p /app/output /app/checkpoints /app/logs /app/data /app/storage /app/models_cache

# Non-root user.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Task 6.1 资产剥离死铁律: large model cache lives in a Volume, never baked into the image.
VOLUME ["/app/models_cache"]

# env_checker runs as a HARD GATE in CI (.github/workflows/ci.yml).
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# CMD (not ENTRYPOINT) so `docker run <image> celery -A ...` and compose
# `command: uvicorn|celery ...` cleanly override the default web server.
# Default boots the FastAPI app (python -m audiobook_studio.main → uvicorn → /health).
CMD ["python", "-m", "audiobook_studio.main"]
