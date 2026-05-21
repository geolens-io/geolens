---
created: 2026-05-04T14:17:18.838Z
title: Add root multi-stage Dockerfile targets
area: tooling
files:
  - Dockerfile
  - .dockerignore
  - backend/Dockerfile
  - frontend/Dockerfile
  - frontend/Dockerfile.dev
  - docker-compose.yml
  - docker-compose.demo.yml
  - docker-compose.enterprise.yml
  - .github/workflows/publish.yml
  - .planning/quick/20260424-validate-research-investigate-the-feasab/20260424-RESEARCH.md
  - .planning/ROADMAP.md:502
  - .planning/ROADMAP.md:513
---

## Problem

GeoLens currently has separate backend and frontend Dockerfiles plus separate GHCR publish entries. That is operationally sound, but packaging/distribution work could benefit from one repository-root multi-stage Dockerfile with named targets for separate runtime images.

Important context from the 2026-05-04 feasibility investigation:

- This is **not** worth turning into a standalone milestone by itself. It fits best as part of future distribution/package work, especially existing backlog Phase 999.14 (`Helm chart + AMI Packer pipeline`) and Phase 999.15 (`SBOM + signed image distribution`).
- For open source distribution, the valuable move is **one root Dockerfile with multiple targets**, not one combined production container. The user-facing `docker compose up` flow already hides most Dockerfile complexity.
- Preserve separate runtime artifacts/images for `api`, `worker`, and `frontend`. This keeps scaling, CVE scanning, SBOMs, attestations, and operational ownership clear.
- Avoid making a single all-in-one production container the primary deployment path. GeoLens's nginx frontend currently owns `/api/` proxying, raster auth subrequests, TiTiler proxying, tile/auth caches, SPA fallback, runtime `env-config.js`, gzip/security headers, upload size, and long API proxy timeouts.
- Enterprise packaging should remain explicit. A root Dockerfile must not accidentally include private enterprise code in the community build context. Add a strong root `.dockerignore`; use explicit build targets/contexts; keep enterprise as a separate downstream/private target or image if needed.
- ECS and Kubernetes scale better with separate services/images. ECS task definitions can include one or more containers, but separate services remain cleaner for API/worker/frontend scaling. Kubernetes one-container-per-Pod is the common model; multi-container Pods are best reserved for tightly coupled sidecars, not API + worker + frontend + TiTiler.

## Solution

When distribution packaging work is next promoted, consider a low-risk implementation:

1. Add a repository-root `Dockerfile` with named targets such as `api`, `worker`, and `frontend`.
2. Add a repository-root `.dockerignore` before switching any build context to `.`.
3. Update compose files to build from the root Dockerfile with `target: api`, `target: worker`, and `target: frontend`, preserving existing service boundaries.
4. Update `.github/workflows/publish.yml` to publish separate GHCR images from the same Dockerfile using target-specific matrix entries.
5. Keep TiTiler as a separate image/service.
6. Treat any later combined `app` image as an optional convenience/demo target with dedicated tests, not the default production path.

Verification to require when implemented:

- `docker compose config --quiet`
- `docker compose -f docker-compose.yml -f docker-compose.demo.yml config --quiet`
- `docker compose -f docker-compose.yml -f docker-compose.enterprise.yml config --quiet`
- Build all root Dockerfile targets locally or in CI.
- Confirm published image names and SBOM/attestation flows remain separate.

## Completed

Completed 2026-05-05.

- Root `Dockerfile` has separate `api`, `worker`, and `frontend` runtime targets.
- Core compose builds `migrate`/`api` from target `api` and `worker` from target `worker`.
- Demo compose builds production frontend from target `frontend`; base compose intentionally keeps Vite dev server via `frontend/Dockerfile.dev`.
- Enterprise overlay in `../geolens-enterprise/docker-compose.enterprise.yml` inherits the core target builds and only mounts `/enterprise`.
- GHCR publish matrix builds and pushes `geolens-api`, `geolens-worker`, and `geolens-frontend` from the same root Dockerfile.
- Published image docs and verifier now include the worker image.

Verification run:

- `docker compose config --quiet`
- `docker compose -f docker-compose.yml -f docker-compose.demo.yml config --quiet`
- `docker compose -f docker-compose.yml -f ../geolens-enterprise/docker-compose.enterprise.yml config --quiet`
- `docker build --call=targets -f Dockerfile .`
- `docker build --check --target api -f Dockerfile .`
- `docker build --check --target worker -f Dockerfile .`
- `docker build --check --target frontend -f Dockerfile .`
- `docker build --target api -t geolens-api:local -f Dockerfile .`
- `docker build --target worker -t geolens-worker:local -f Dockerfile .`
- `docker build --target frontend -t geolens-frontend:local -f Dockerfile .`

## Open WebUI Reference Comparison

Captured 2026-05-05.

The Open WebUI reference pattern is a single root multi-stage Dockerfile that builds frontend assets in a Node stage, copies them into a Python backend runtime image, and publishes one primary web image with optional variant tags such as Ollama/CUDA. GeoLens is aligned with the root-Dockerfile part of that pattern, but should not copy the single-runtime-container part as the default distribution model.

GeoLens has stronger service boundaries than Open WebUI:

- `api`, `worker`, and `frontend` have different scaling, health, and restart semantics.
- The worker must scale/restart independently for ingest/export/raster jobs.
- The frontend nginx runtime owns real product behavior: SPA serving, `/api/` proxying, raster tile auth subrequests, TiTiler proxying, raster tile cache policy, upload proxy limits, gzip/security headers, and runtime `env-config.js`.
- TiTiler and PostGIS remain separate service boundaries; folding them into one production image would increase image size and operational fragility.
- Separate images keep SBOMs, CVE scans, rollout blast radius, and enterprise overlay boundaries clearer.

Decision: keep separate `geolens-api`, `geolens-worker`, and `geolens-frontend` images as the primary distribution model. A future optional `standalone`/`app` target may bundle API plus built frontend for demos or very small installs, but it should not include worker, PostGIS, or TiTiler and should not become the production default without dedicated tests.
