# syntax=docker/dockerfile:1

FROM python:3.14.3-slim AS backend-base

# Install uv from official image.
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

WORKDIR /app

# Refresh base image packages before installing runtime dependencies so
# release scans pick up patched OpenSSL/libssl packages from Debian.
# Install GDAL/ogr2ogr for geospatial file processing.
# libexpat1 is required for rasterio manylinux wheel on slim base.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
    gdal-bin \
    libexpat1 \
    xmlsec1 libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user shared by the API and worker runtime targets.
RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --gid 1001 --uid 1001 --create-home appuser

# Environment for uv.
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

# Create writable directories for volumes and transfer ownership.
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
CMD ["sh", "-c", "uv run --no-dev uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]

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
RUN npm ci
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
