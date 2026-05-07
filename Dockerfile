# syntax=docker/dockerfile:1

# ==============================================================================
# Stage 1: backend-builder — uv sync, all build-time prep
# ==============================================================================
# Build-time deps (apt cache, intermediate uv-sync state) are confined to this
# stage. The runtime layer rebuilds from a clean python:3.14.3-slim base and
# only copies the resolved /app venv from this builder.
FROM python:3.14.3-slim AS backend-builder

# uv is build-time + runtime: see runtime-stage comment below for runtime rationale.
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

WORKDIR /app

# Refresh base image packages and install runtime deps the resolved venv needs
# at install time (gdal-bin, libexpat1 for rasterio, libxmlsec1 for SAML).
# These are reinstalled cleanly in the runtime stage; they're here so `uv sync`
# can run native-extension build steps.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
    gdal-bin \
    libexpat1 \
    xmlsec1 libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_SYSTEM_PYTHON=1
ENV PYTHONPATH=/app

# Install dependencies first using only the backend lockfiles for layer caching.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Copy backend application code and install the project into the uv environment.
COPY backend/ /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev
RUN chmod +x /app/scripts/api-entrypoint.sh /app/scripts/worker-entrypoint.sh

# ==============================================================================
# Stage 2: backend-base — clean python:3.14.3-slim runtime; venv from builder
# ==============================================================================
# True multi-stage split per INF-06: runtime starts from a fresh
# python:3.14.3-slim base (no apt-cache layer from builder, no intermediate
# uv-sync state). Only the resolved /app/.venv + code arrive via COPY --from.
#
# Note: uv is INTENTIONALLY KEPT in the runtime layer because
# api-entrypoint.sh runs `uv add --editable ${ENTERPRISE_PATH}` to install the
# enterprise overlay at startup. Removing uv from runtime breaks the enterprise
# install path (M-32 audit subset deferred per 272-RESEARCH-NOTES.md §INF-06).
# gcc/dev libs are still excluded from the runtime layer.
#
# Pin: python:3.14.3-slim. backend/pyproject.toml requires-python>=3.13 for
# adopter flexibility; this image ships 3.14.3 as the project's tested runtime.
# See backend/pyproject.toml comment at requires-python for the matching note.
# Per .planning/REQUIREMENTS.md INF-15.
FROM python:3.14.3-slim AS backend-base

# uv kept for enterprise overlay install (api-entrypoint.sh runs `uv add --editable`).
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

# Runtime apt deps — clean install on a fresh layer (no apt cache from builder).
RUN apt-get update && apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
    gdal-bin \
    libexpat1 \
    xmlsec1 libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (shared by api and worker runtime targets).
RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --gid 1001 --uid 1001 --create-home appuser

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_SYSTEM_PYTHON=1
ENV PYTHONPATH=/app

WORKDIR /app

# Copy the resolved venv + code from the builder. No uv sync runs in runtime.
COPY --from=backend-builder --chown=appuser:appgroup /app /app

# Create writable directories used by the entrypoint.
RUN mkdir -p /app/staging /home/appuser/.cache/uv && \
    chown -R appuser:appgroup /app /app/staging /home/appuser

FROM backend-base AS api

LABEL org.opencontainers.image.title="geolens-api"
LABEL org.opencontainers.image.description="PostGIS-native GIS data catalog API"
LABEL org.opencontainers.image.licenses="Apache-2.0"

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

USER appuser

ENTRYPOINT ["/app/scripts/api-entrypoint.sh"]
CMD ["sh", "-c", "uv run --no-dev uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1} --timeout-keep-alive ${UVICORN_TIMEOUT_KEEP_ALIVE:-5} --timeout-graceful-shutdown ${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-30}"]

FROM backend-base AS worker

LABEL org.opencontainers.image.title="geolens-worker"
LABEL org.opencontainers.image.description="PostGIS-native GIS data catalog worker"
LABEL org.opencontainers.image.licenses="Apache-2.0"

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health/live')"

USER appuser

ENTRYPOINT ["/app/scripts/worker-entrypoint.sh"]
CMD ["sh", "-c", "uv run --no-dev python -m app.worker"]

FROM node:25.9.0-alpine AS frontend-build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build:app

FROM nginxinc/nginx-unprivileged:1.29.8-alpine AS frontend

LABEL org.opencontainers.image.title="geolens-frontend"
LABEL org.opencontainers.image.description="PostGIS-native GIS data catalog frontend"
LABEL org.opencontainers.image.licenses="Apache-2.0"

USER root
RUN apk upgrade --no-cache
USER nginx

COPY --from=frontend-build --chown=nginx:nginx /app/dist /usr/share/nginx/html
COPY --from=frontend-build --chown=nginx:nginx /app/public/env-config.template.js /usr/share/nginx/html/env-config.template.js
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 frontend/docker-entrypoint.sh /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

EXPOSE 8080
