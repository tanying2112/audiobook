# =============================================================================
# Audiobook Studio — Hardened Multi-Stage Dockerfile
# Task 6.3: Non-Root + Multi-Stage + Security Hardening
# =============================================================================

# ---- Build Arguments ---------------------------------------------------------
ARG PYTHON_VERSION=3.11-slim
ARG APP_UID=1000
ARG APP_GID=1000
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

# ---- Stage 1: Builder --------------------------------------------------------
FROM python:${PYTHON_VERSION} AS builder

# Prevent bytecode / buffering; disable pip cache to keep layer small.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build deps only (no runtime libs here).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first for maximum layer caching.
COPY requirements.txt .
COPY pyproject.toml ./

# Create virtualenv and install deps — completely isolated from runtime.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: Runtime --------------------------------------------------------
FROM python:${PYTHON_VERSION} AS runner

# ---- Metadata / Labels (OCI Image Spec) ----
LABEL org.opencontainers.image.title="Audiobook Studio" \
      org.opencontainers.image.description="Production-grade AI audiobook generation pipeline" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/tanying2112/AI_Lab" \
      org.opencontainers.image.licenses="MIT"

# ---- Runtime Environment -----------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:${PATH}" \
    # Model cache lives on a Volume at runtime — never baked into the image.
    AUDIOBOOK_STUDIO_MODEL_CACHE=/app/models_cache \
    # Security: prevent python from loading site-packages from user directory.
    PYTHONNOUSERSITE=1

# Install ONLY runtime dependencies (no build toolchain).
# tini: proper signal handling & zombie reaping for PID 1.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libsndfile1 \
    postgresql-client \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

WORKDIR /app

# Copy pre-built virtualenv from builder (no pip cache, no build residue).
COPY --from=builder /opt/venv /opt/venv

# Copy application source with correct ownership (no chown layer needed).
COPY --chown=${APP_UID}:${APP_GID} . .

# Create required runtime directories with correct ownership.
RUN mkdir -p /app/output /app/checkpoints /app/logs /app/data /app/storage /app/models_cache \
    && chown -R ${APP_UID}:${APP_GID} /app

# ---- Non-Root User -----------------------------------------------------------
# Create user/group with fixed UID/GID (matches CI / K8s expectations).
RUN groupadd -g ${APP_GID} appgroup \
    && useradd -m -u ${APP_UID} -g ${APP_GID} -s /bin/bash appuser

# Switch to non-root user.
USER appuser

# ---- Security Hardening ------------------------------------------------------
# Drop all capabilities — container runs with minimal privileges.
# (Override in compose/k8s only if a specific capability is truly required.)
# Note: This is enforced at runtime via `docker run --cap-drop=ALL` or
# Kubernetes `securityContext.capabilities.drop: ["ALL"]`.
# The image itself does not require capabilities.

# Read-only root filesystem where possible (opt-in via `docker run --read-only`).
# App writes only to /app/output, /app/logs, /app/data, /app/storage, /app/models_cache, /app/checkpoints.

# ---- Health Check ------------------------------------------------------------
# Use tini-wrapped endpoint check with graceful timeout.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# ---- Ports -------------------------------------------------------------------
EXPOSE 8000

# ---- Entrypoint / Command ----------------------------------------------------
# tini as PID 1 ensures signals propagate to the Python process (uvicorn/celery).
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default: run FastAPI app (uvicorn via main.py).
# Override in docker-compose / k8s for workers: `celery -A audiobook_studio.celery_app worker -l info`
CMD ["python", "-m", "audiobook_studio.main"]