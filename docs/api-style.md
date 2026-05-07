# GeoLens API Style Guide

This document describes the conventions GeoLens follows for HTTP routes, status codes, and request/response shapes. The conventions are **descriptive** — they document what shipped — and they're the reference for new routes added to the public API.

For the auto-generated OpenAPI surface, see `backend/openapi.json` and the live `/api/docs` Swagger UI when the server is running.

## Trailing-Slash Convention

GeoLens routes follow a deliberate trailing-slash split based on the route's *role*, not its HTTP method.

| Role | Convention | Example |
|------|------------|---------|
| **Collection root** | Trailing slash | `POST /maps/`, `GET /maps/` |
| **Single resource** | No trailing slash | `GET /maps/{map_id}` |
| **Sub-collection** | No trailing slash | `GET /maps/{map_id}/history`, `GET /maps/icons` |
| **Action endpoint** (a verb-shaped operation on a parent resource) | Trailing slash | `POST /maps/{map_id}/duplicate/`, `PUT /maps/{map_id}/thumbnail/`, `POST /maps/{map_id}/share/` |
| **Single resource with file extension** | No trailing slash | `GET /maps/{map_id}/style.json`, `GET /maps/sprites/geolens.json` |

### Why this split

A FastAPI route declared as `/foo/` and called as `/foo` (no slash) returns a 307 redirect. The mix above is intentional: the trailing slash *on action endpoints* mirrors the convention for collection roots — both are "things you POST/PUT to" rather than "things you GET by ID." Action endpoints with the trailing slash never collide with `/maps/{map_id}` parameter routes because the `duplicate/`, `share/`, `thumbnail/`, `visibility-check/` literal segments take precedence.

### Avoid

- **Don't** add a trailing slash to single-resource routes — `GET /maps/{map_id}/` would shadow `GET /maps/{map_id}` and force a 307 on every direct fetch.
- **Don't** mix conventions within a single sub-collection. The five `/share/` routes (GET/POST/PATCH/DELETE on the share token, plus GET on the shared map) are uniformly action-shaped or single-resource-shaped: pick one shape and stick to it.
- **Don't** add `/icons/` (trailing) variants — Phase 269 explicitly removed them because they shadowed the `/icons/{icon_id}/asset` parameter route. (See CHANGELOG `[Unreleased]` 2026-05-07 entry.)

### `/ingest/manifest/apply` is intentional

The manifest apply endpoint is `POST /ingest/manifest/apply` — no trailing slash. This is consistent with the rest of `/ingest/upload/...` (which also doesn't carry trailing slashes) and with the action-endpoint-on-sub-collection rule above (`/ingest/manifest/` is a sub-collection of `/ingest/`, and `apply` is a single action under it).

If you're adding a new manifest-related action, follow the same shape: `POST /ingest/manifest/{action}` with no trailing slash.

### Reference: full `/maps` route inventory

The complete `/maps` namespace as it ships today, annotated with the convention each route follows:

| Route | Method | Role |
|-------|--------|------|
| `/maps/` | POST | Collection root — CRUD create |
| `/maps/` | GET | Collection root — list |
| `/maps/shared/{token}` | GET | Single resource (token-scoped) |
| `/maps/{map_id}/visibility-check/` | GET | Action endpoint |
| `/maps/icons` | GET, POST | Sub-collection |
| `/maps/icons/{icon_id}/asset` | GET | Single resource action |
| `/maps/sprites/geolens.json` | GET | Single resource w/ extension |
| `/maps/sprites/geolens.png` | GET | Single resource w/ extension |
| `/maps/import` | POST | Action that creates a child resource |
| `/maps/{map_id}` | GET, PUT, DELETE | Single resource |
| `/maps/{map_id}/history` | GET | Sub-collection |
| `/maps/{map_id}/style.json` | GET | Single resource w/ extension |
| `/maps/{map_id}/layers` | PATCH, POST | Sub-collection |
| `/maps/{map_id}/layers/{layer_id}` | DELETE | Single resource |
| `/maps/{map_id}/duplicate/` | POST | Action endpoint |
| `/maps/{map_id}/share/` | GET, POST, PATCH, DELETE | Action endpoint family |
| `/maps/{map_id}/thumbnail/` | GET, PUT | Action endpoint |

## Status Code Convention

GeoLens uses a deliberate split between **CRUD endpoints** (which return 201 / 204) and **action endpoints** (which return 200 with a result envelope).

| Endpoint type | Status code | Body shape | Example |
|---------------|-------------|------------|---------|
| **CRUD create** | `201 Created` | Created resource | `POST /maps/` → `MapResponse` |
| **CRUD delete** | `204 No Content` | Empty | `DELETE /maps/{map_id}` |
| **CRUD update** | `200 OK` | Updated resource | `PUT /maps/{map_id}` → `MapResponse` |
| **Action endpoint** (operation on a parent resource that doesn't always create a long-lived child) | `200 OK` | Result envelope | `POST /ingest/manifest/apply` → `ManifestApplyResponse` |
| **Action that DOES create a long-lived child** | `201 Created` | Created child | `POST /maps/import` → `MapStyleImportResponse` (creates new map), `POST /maps/{map_id}/duplicate/` → `DuplicateMapResponse` |

### Why we don't always 201

Several action POSTs (`POST /maps/{map_id}/share/`, `POST /search/...`, `POST /ai/chat/...`) return `200 OK` even though they're POST. This is **conventional** in REST APIs because:

1. The body is a result envelope, not a freshly-created resource the client should `GET` again.
2. The same operation is idempotent or near-idempotent — repeated calls return the same envelope.
3. The "Location" header semantics of 201 don't apply (there's no canonical URL for the share token to follow).

Returning 200 here is **not a defect**; it's the most accurate semantic. New action endpoints should follow the same pattern unless they create a resource the client will later address by URL.

## Health Check Endpoint

`GET /health` returns:
- `200 OK` with `{"status": "healthy", ...}` when the API + DB + storage health checks all pass.
- `503 Service Unavailable` with `{"status": "degraded", ...}` if any check fails.

It is tagged `Health` in the OpenAPI spec so it groups under its own section in `/api/docs`. It bypasses rate limiting (`@limiter.exempt`).

The `/health` endpoint is the canonical liveness probe for ALB, Docker Compose `healthcheck:`, and Nginx upstream health.

## Other Conventions

- **Pagination**: list endpoints accept `skip` (offset) and `limit` (max 200 per Phase 270 / H-24). For large catalog scans, prefer the keyset cursor parameter (`after_gid` on `/datasets/{id}/features` and OGC `/items`) — see CHANGELOG `[Unreleased]` 2026-05-07 entry.
- **Errors**: 4xx errors return `{"detail": "..."}` (FastAPI default) or RFC 7807 `ProblemDetail` for OGC-compliant routes (see `backend/app/standards/ogc/errors.py`). 5xx errors are not exposed with a body in production.
- **Auth**: Bearer token in `Authorization` header is the canonical auth method. `?api_key=<key>` is supported as a fallback (precedence: header > query > JWT > anonymous; see `backend/app/modules/auth/dependencies.py`).
- **CORS**: configured via `CORS_ALLOWED_ORIGINS` (comma-separated). Empty = same-origin only.

## When in doubt

When adding a new route:
1. Match an existing route's shape and convention before inventing a new one.
2. Skim `/api/docs` to see how the route appears in the Swagger UI — that's how SDK consumers will read it.
3. For SDK ergonomics, prefer typed Pydantic request bodies over `dict = Body(...)`. See API-01 (Phase 275, Plan 01) for the canonical pattern.

## Provenance

This guide is a Phase 275 (v13.13 / API-03 + API-07) artifact documenting the conventions that shipped with v1.0.0 + v1.1.0. It supersedes the previous unwritten "ask in PR review" pattern.
