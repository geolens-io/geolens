# syntax=docker/dockerfile:1

# ==============================================================================
# Stage 1: backend-builder — uv sync, all build-time prep
# ==============================================================================
# Build-time deps (apt cache, intermediate uv-sync state) are confined to this
# stage. The runtime layer rebuilds from a clean python:3.14-slim base and
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
# These arguments are a legacy hook for distributors that vendor and modify
# this Dockerfile so their own COPY instructions occur before this RUN. They
# are not a supported derived-image interface: a child Dockerfile cannot insert
# a COPY into the middle of its parent build. Official paid distributions own
# an immutable overlay Dockerfile that starts from the completed core runtime,
# installs a locked wheel at build time, and promotes that same image to API,
# worker, and migration services.
#
# Back-compat alias: INSTALL_ENTERPRISE_OVERLAY (legacy single-overlay ARG from
# pre-BAKE-01 distributor-owned Dockerfiles). When their Dockerfile already
# stages /enterprise, the alias still prepends that path. It does not make an
# unmodified public build capable of copying a private overlay.
#
# When both ARGs are empty (the only supported public build) this block is a no-op and the OSS
# image is byte-for-byte unchanged.  CI always builds without the ARGs so the
# OSS path is exercised on every run.
#
# NOTE: overlay dirs are excluded from the OSS build context by .dockerignore
# and this Dockerfile has no overlay COPY. The guard therefore fails closed in
# an unmodified checkout. Do not advertise this hook as a paid-image build.
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
            echo "This legacy hook requires a distributor-owned Dockerfile that stages the overlay before this RUN." >&2; \
            echo "Use the overlay repository's immutable image build for supported distributions." >&2; \
            exit 1; \
        fi; \
        echo "Baking overlay '${_dir}' into image at build time..." && \
        uv add --editable "${_dir}" --no-dev; \
    done

# ==============================================================================
# Stage 2: backend-base — clean python:3.14-slim runtime; venv from builder
# ==============================================================================
# True multi-stage split: runtime starts from a fresh
# python:3.14-slim base (no apt-cache layer from builder, no intermediate
# uv-sync state). Only the resolved /app/.venv + code arrive via COPY --from.
#
# Note: uv is kept in the runtime layer because the entrypoints and CMD use
# `uv run --no-dev` to launch uvicorn/worker inside the project environment.
# An overlay is NOT installed at runtime (read_only rootfs prevents it — see
# BUG-003); supported paid distributions use their overlay-owned immutable
# Dockerfile to install a locked wheel into this completed runtime image.
# gcc/dev libs are still excluded from the runtime layer.
#
# Pin: see the `FROM python:3.14-slim` line below (Dependabot bumps the exact
# patch, so this prose names only the minor). backend/pyproject.toml
# requires-python>=3.13 for adopter flexibility; this image ships the pinned
# 3.14-slim as the project's tested runtime.
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

# Create writable directories used by the entrypoint. The builder COPY already
# owns /app; install only the runtime directories so this layer does not
# recursively duplicate metadata for the full application tree.
RUN install -d -o appuser -g appgroup \
    /app/staging \
    /home/appuser/.cache/uv

# fix(#441): stamp the build commit for /health `build` reporting. publish.yml
# passes it on release builds; local and dev builds leave it empty. Declared
# last in this shared stage so a changing SHA invalidates no heavy layers, and
# as ENV so the api and worker child stages inherit it.
ARG GEOLENS_BUILD_SHA=
ENV GEOLENS_BUILD_SHA=${GEOLENS_BUILD_SHA}

FROM backend-base AS api

LABEL org.opencontainers.image.title="geolens-api"
LABEL org.opencontainers.image.description="PostGIS-native GIS data catalog API"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/geolens-io/geolens"

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

USER appuser

ENTRYPOINT ["/app/scripts/api-entrypoint.sh"]
CMD ["sh", "-c", "uv run --no-dev uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1} --timeout-keep-alive ${UVICORN_TIMEOUT_KEEP_ALIVE:-5} --timeout-graceful-shutdown ${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-30} ${UVICORN_MAX_REQUESTS:+--limit-max-requests ${UVICORN_MAX_REQUESTS}}"]

FROM backend-base AS worker

LABEL org.opencontainers.image.title="geolens-worker"
LABEL org.opencontainers.image.description="PostGIS-native GIS data catalog worker"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/geolens-io/geolens"

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health/live')"

USER appuser

ENTRYPOINT ["/app/scripts/worker-entrypoint.sh"]
CMD ["sh", "-c", "uv run --no-dev python -m app.worker"]

# ==============================================================================
# Stage: backup — pg_dump 17 + SigV4-capable S3 client; self-contained backup
# ==============================================================================
# Base: official postgres:17 (Debian Bookworm, multi-arch: amd64 + arm64),
# pinned by digest. Dependabot tracks Docker digest updates for this file.
# db/Dockerfile uses postgis/postgis:17-3.5 which is amd64-ONLY — this stage
# uses the digest-pinned postgres:17 base so publish.yml can build both arches
# (BKP-01).
# PostGIS is NOT needed client-side: pg_dump streams the raw catalog over the
# wire and custom-format dumps preserve PostGIS types without PostGIS libs.
#
# Placement note: this stage is intentionally NOT last. An unqualified
# `docker build .` resolves to the FINAL stage, and the default image must be an
# app image (frontend), never this postgres-based backup tool. Every image is
# built with an explicit `target:` (publish.yml + docker-compose*.yml), so stage
# order only governs that unqualified-build default — keep `backup` non-final.
FROM postgres:17@sha256:a426e44bac0b759c95894d68e1a0ac03ecc20b619f498a91aae373bf06d8508d AS backup

LABEL org.opencontainers.image.title="geolens-backup"
LABEL org.opencontainers.image.description="Automated pg_dump backup service with S3 offload"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/geolens-io/geolens"

# awscli (SigV4-capable S3 client) for the BKP-02 S3 upload path; procps for the
# compose healthcheck (`pgrep -f backup-entrypoint || pgrep -f sleep`) — pgrep is
# present in the postgres:17 base today but is installed explicitly so the
# default-on healthcheck's pgrep dependency survives a base-image change.
# Installed from Debian apt only — no pip/PyPI (T-1247-SC mitigation).
RUN apt-get update && apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
    awscli \
    procps \
    && rm -rf /var/lib/apt/lists/* \
    # fix(#517): drop the base image's gosu — the backup entrypoint never
    # invokes it, and its Go-built binary trips Trivy's CRITICAL/HIGH gate
    # (Go stdlib CVEs) independently of our own code.
    && rm -f /usr/local/bin/gosu

# Bake the backup and restore scripts so the image is self-contained and
# runnable without a host bind-mount. The compose bind-mount
# (./scripts:/scripts:ro) may override at runtime for local development.
COPY scripts/backup-entrypoint.sh scripts/restore.sh /scripts/
RUN chmod +x /scripts/backup-entrypoint.sh /scripts/restore.sh

ENTRYPOINT ["/scripts/backup-entrypoint.sh"]

FROM node:26.5.0-alpine AS frontend-build

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
            echo "This legacy hook requires a distributor-owned Dockerfile that stages the overlay before this RUN." >&2; \
            echo "Use the overlay repository's standalone frontend image build instead." >&2; \
            exit 1; \
        fi; \
        echo "Merging frontend overlay '${_dir}' into build context..."; \
        cp -r "${_dir}/src/." /app/src/; \
    done

RUN GEOLENS_FRONTEND_EDITION=${GEOLENS_FRONTEND_EDITION} npm run build:app

FROM nginxinc/nginx-unprivileged:1.31.3-alpine AS frontend

LABEL org.opencontainers.image.title="geolens-frontend"
LABEL org.opencontainers.image.description="PostGIS-native GIS data catalog frontend"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/geolens-io/geolens"

USER root
RUN apk upgrade --no-cache
# The vhost ships as a template rendered into /tmp/geolens-nginx at startup
# (envsubst of API_UPSTREAM/NGINX_RESOLVER — see frontend/docker-entrypoint.sh),
# so the stock conf.d include must point at the rendered location. Remove the
# base image's default vhost so nothing can serve if conf.d ever gets
# re-included, and assert the include rewrite matched so a base-image layout
# change fails this build instead of shipping an nginx with no server block.
RUN rm -f /etc/nginx/conf.d/default.conf && \
    sed -i 's|include /etc/nginx/conf\.d/\*\.conf;|include /tmp/geolens-nginx/*.conf;|' /etc/nginx/nginx.conf && \
    grep -q 'include /tmp/geolens-nginx/\*\.conf;' /etc/nginx/nginx.conf
USER nginx

# Keep the built SPA immutable. The entrypoint copies it into /tmp at startup,
# then writes the operator-specific runtime config there. This supports a
# read-only production root filesystem without mutating image layers.
COPY --from=frontend-build --chown=nginx:nginx /app/dist /opt/geolens/html
COPY --from=frontend-build --chown=nginx:nginx /app/public/env-config.template.js /opt/geolens/html/env-config.template.js
COPY frontend/nginx.conf /opt/geolens/default.conf.template
COPY --chmod=755 frontend/docker-entrypoint.sh /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/ || exit 1

EXPOSE 8080
