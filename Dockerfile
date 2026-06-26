# syntax=docker/dockerfile:1

# ==============================================================================
# Stage 1: backend-builder — uv sync, all build-time prep
# ==============================================================================
# Build-time deps (apt cache, intermediate uv-sync state) are confined to this
# stage. The runtime layer rebuilds from a clean python:3.14.3-slim base and
# only copies the resolved /app venv from this builder.
FROM python:3.14.6-slim AS backend-builder

# uv is build-time + runtime: see runtime-stage comment below for runtime rationale.
# Aligned uv installer pin across builder + runtime stages.
COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /uvx /bin/

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
# Overlay bake — BUILD-TIME (BUG-003 / BAKE-01)
# ==============================================================================
# The runtime container runs with read_only: true rootfs (see docker-compose.yml
# x-hardened-base anchor).  A runtime `uv add --editable` cannot write into
# the baked /app/.venv — it silently fails, and BUG-003's startup check then
# refuses to boot as OSS when GEOLENS_EDITION=enterprise was set.
#
# The architecturally correct solution is to pre-bake overlays INTO the image
# at BUILD time so the read_only runtime never needs to write.
#
# BAKE-01: this block now accepts a SPACE-SEPARATED LIST of overlay dirs so
# both an enterprise and a cloud overlay can bake into one image. Each listed
# dir must already exist inside the build context (staged via COPY in a derived
# Dockerfile) and must contain a pyproject.toml — the guard fails closed
# otherwise (exit 1).
#
# Usage (single enterprise build — derived image, three steps):
#
#   1. Place the overlay source in the build context and allow it in .dockerignore:
#        cp -r /path/to/geolens-enterprise ./enterprise
#        # Temporarily append to .dockerignore for the enterprise build:
#        #   !enterprise/
#        #   !enterprise/**
#
#   2. In a DERIVED Dockerfile add a COPY that stages the overlay BEFORE the
#      INSTALL_OVERLAYS RUN below.  The OSS image intentionally omits it — an
#      unconditional `COPY enterprise/ /enterprise/` would fail the OSS build:
#        COPY enterprise/ /enterprise/
#
#   3. Build with the ARG set:
#        docker build \
#            --build-arg INSTALL_OVERLAYS="/enterprise" \
#            -t geolens-api:enterprise .
#
# Usage (combined enterprise + cloud build):
#
#   1. Stage both overlay dirs:
#        COPY enterprise/ /enterprise/
#        COPY cloud/ /cloud/
#        # Allow both in .dockerignore:
#        #   !enterprise/
#        #   !enterprise/**
#        #   !cloud/
#        #   !cloud/**
#
#   2. Build with both dirs listed (space-separated):
#        docker build \
#            --build-arg INSTALL_OVERLAYS="/enterprise /cloud" \
#            -t geolens-api:enterprise-cloud .
#
# Back-compat alias: INSTALL_ENTERPRISE_OVERLAY (legacy single-overlay ARG from
# pre-BAKE-01 builds). When set/non-empty, /enterprise is prepended to the
# effective overlay list, so existing CI pipelines using
# `--build-arg INSTALL_ENTERPRISE_OVERLAY=1` continue to work unchanged.
#
# When both ARGs are empty (the default) this block is a no-op and the OSS
# image is byte-for-byte unchanged.  CI always builds without the ARGs so the
# OSS path is exercised on every run.
#
# NOTE: overlay dirs are excluded from the OSS build context by .dockerignore
# (default deny-then-allow pattern), and this OSS Dockerfile has NO unconditional
# COPY for any overlay (an unconditional copy would break the OSS build).  The
# guard fails closed unless the operator both allows the overlay dir in
# .dockerignore (step 1) AND stages it via COPY in a derived image (step 2).
ARG INSTALL_ENTERPRISE_OVERLAY=
ARG INSTALL_OVERLAYS=
RUN --mount=type=cache,target=/root/.cache/uv \
    _effective_overlays="${INSTALL_OVERLAYS:-}"; \
    if [ -n "${INSTALL_ENTERPRISE_OVERLAY:-}" ]; then \
        _effective_overlays="/enterprise${_effective_overlays:+ $_effective_overlays}"; \
    fi; \
    for _dir in ${_effective_overlays}; do \
        if [ ! -d "${_dir}" ] || [ ! -f "${_dir}/pyproject.toml" ]; then \
            echo "ERROR: overlay dir '${_dir}' is missing or has no pyproject.toml." >&2; \
            echo "Ensure the overlay source is in the build context:" >&2; \
            echo "  - Add '!${_dir}/' and '!${_dir}/**' to .dockerignore" >&2; \
            echo "  - Add 'COPY ${_dir#/}/ ${_dir}/' before this RUN in your derived image." >&2; \
            exit 1; \
        fi; \
        echo "Baking overlay '${_dir}' into image at build time..." && \
        uv add --editable "${_dir}" --no-dev; \
    done

# ==============================================================================
# Stage 2: backend-base — clean python:3.14.3-slim runtime; venv from builder
# ==============================================================================
# True multi-stage split: runtime starts from a fresh
# python:3.14.3-slim base (no apt-cache layer from builder, no intermediate
# uv-sync state). Only the resolved /app/.venv + code arrive via COPY --from.
#
# Note: uv is kept in the runtime layer because the entrypoints and CMD use
# `uv run --no-dev` to launch uvicorn/worker inside the project environment.
# The enterprise overlay is NOT installed at runtime (read_only rootfs prevents
# it — see BUG-003); use the build-time bake path above (ARG
# INSTALL_ENTERPRISE_OVERLAY) to pre-bake the overlay into an enterprise image.
# gcc/dev libs are still excluded from the runtime layer.
#
# Pin: python:3.14.3-slim. backend/pyproject.toml requires-python>=3.13 for
# adopter flexibility; this image ships 3.14.3 as the project's tested runtime.
# See backend/pyproject.toml comment at requires-python for the matching note.
FROM python:3.14.6-slim AS backend-base

# uv kept for `uv run --no-dev` launch pattern (entrypoints + CMD).
# Aligned uv installer pin across builder + runtime stages.
COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /uvx /bin/

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

# ==============================================================================
# Stage: backup — pg_dump 17 + SigV4-capable S3 client; self-contained backup
# ==============================================================================
# Base: official postgres:17 (Debian Bookworm, multi-arch: amd64 + arm64).
# db/Dockerfile uses postgis/postgis:17-3.5 which is amd64-ONLY — this stage
# uses the plain postgres:17 base so publish.yml can build both arches (BKP-01).
# PostGIS is NOT needed client-side: pg_dump streams the raw catalog over the
# wire and custom-format dumps preserve PostGIS types without PostGIS libs.
#
# Placement note: this stage is intentionally NOT last. An unqualified
# `docker build .` resolves to the FINAL stage, and the default image must be an
# app image (frontend), never this postgres-based backup tool. Every image is
# built with an explicit `target:` (publish.yml + docker-compose*.yml), so stage
# order only governs that unqualified-build default — keep `backup` non-final.
FROM postgres:17 AS backup

LABEL org.opencontainers.image.title="geolens-backup"
LABEL org.opencontainers.image.description="Automated pg_dump backup service with S3 offload"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# awscli (SigV4-capable S3 client) for the BKP-02 S3 upload path; procps for the
# compose healthcheck (`pgrep -f backup-entrypoint || pgrep -f sleep`) — pgrep is
# present in the postgres:17 base today but is installed explicitly so the
# default-on healthcheck's pgrep dependency survives a base-image change.
# Installed from Debian apt only — no pip/PyPI (T-1247-SC mitigation).
RUN apt-get update && apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
    awscli \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Bake the backup and restore scripts so the image is self-contained and
# runnable without a host bind-mount. The compose bind-mount
# (./scripts:/scripts:ro) may override at runtime for local development.
COPY scripts/backup-entrypoint.sh scripts/restore.sh /scripts/
RUN chmod +x /scripts/backup-entrypoint.sh /scripts/restore.sh

ENTRYPOINT ["/scripts/backup-entrypoint.sh"]

FROM node:26.3.0-alpine AS frontend-build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline
COPY frontend/ ./

# ==============================================================================
# Frontend overlay bake — FEOVL-03 / BAKE-01 extension
# ==============================================================================
# Mirrors the backend BAKE-01 block (Dockerfile lines 46-127). The OSS build
# leaves INSTALL_FRONTEND_OVERLAYS unset so this block is a no-op and the OSS
# dist is byte-identical to the pre-FEOVL-03 build.
#
# CR-03 (Phase 1212): the merged-source path (INSTALL_FRONTEND_OVERLAYS set to
# a cloud overlay dir) is NOT a supported build path for the cloud image.
# The cloud overlay src-cloud/App.tsx and main.tsx import from '@cloud/*', which
# has no alias in this OSS vite.config — using this path produces unresolved-
# module errors.
#
# SUPPORTED build path for the cloud frontend: use the STANDALONE cloud Vite
# build in geolens-overlays/geolens_cloud/frontend/Dockerfile (Stage 2).  That
# build has its own vite.config.ts with both '@' (OSS src) and '@cloud'
# (cloud src-cloud/) aliases and produces a correct dist.
#
# The ARG and loop below are preserved so the OSS Dockerfile remains a no-op
# (INSTALL_FRONTEND_OVERLAYS unset → loop body never runs → byte-identical OSS
# dist).  Do NOT set INSTALL_FRONTEND_OVERLAYS to a cloud overlay dir unless
# the overlay vite.config alias issue (CR-03) has been resolved.
ARG INSTALL_FRONTEND_OVERLAYS=
ARG GEOLENS_FRONTEND_EDITION=community
RUN set -e; \
    for _dir in ${INSTALL_FRONTEND_OVERLAYS:-}; do \
        if [ ! -f "${_dir}/package.json" ]; then \
            echo "ERROR: frontend overlay '${_dir}' missing package.json." >&2; \
            echo "Ensure the overlay source is staged in the build context:" >&2; \
            echo "  - Add '!${_dir#/}/' and '!${_dir#/}/**' to .dockerignore" >&2; \
            echo "  - Add 'COPY ${_dir#/}/ ${_dir}/' before this stage in your derived image." >&2; \
            exit 1; \
        fi; \
        echo "Merging frontend overlay '${_dir}' into build context..."; \
        cp -r "${_dir}/src/." /app/src/; \
    done

RUN GEOLENS_FRONTEND_EDITION=${GEOLENS_FRONTEND_EDITION} npm run build:app

FROM nginxinc/nginx-unprivileged:1.31.1-alpine AS frontend

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
