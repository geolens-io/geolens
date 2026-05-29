---
phase: 1142-og-image-social-cards-sharepanel-typography
plan: "01"
subsystem: backend
tags: [share, og-image, social-cards, fastapi, alembic, pillow, html-escape]
dependency_graph:
  requires: []
  provides:
    - "GET /api/maps/shared/{token}/card (OG/Twitter HTML meta, crawler-facing)"
    - "PUT /api/maps/{id}/og-image/ (owner-only, PIL-verified, capped 750KB)"
    - "GET /api/maps/{id}/og-image/ (visibility-checked, cache 86400s public)"
    - "MapResponse.og_image_url field"
    - "migration 0024 (catalog.maps.og_image_uri TEXT NULL)"
  affects:
    - backend/app/modules/catalog/maps/router.py
    - backend/app/modules/catalog/maps/models.py
    - backend/app/modules/catalog/maps/schemas.py
    - backend/alembic/versions/0024_maps_og_image_uri.py
tech_stack:
  added: []
  patterns:
    - "html.escape() for user-controlled text in server-rendered HTML meta"
    - "Path A: separate og_image_uri column + routes; ThumbnailUploadRequest unchanged"
    - "Crawler meta via dedicated /card route (zero nginx change, zero SSR framework)"
key_files:
  created:
    - backend/alembic/versions/0024_maps_og_image_uri.py
    - backend/tests/test_maps_og_image.py
  modified:
    - backend/app/modules/catalog/maps/models.py
    - backend/app/modules/catalog/maps/schemas.py
    - backend/app/modules/catalog/maps/router.py
decisions:
  - "D-03 (carried): Path A for OG image — new og_image_uri column + routes. ThumbnailUploadRequest.max_length=100_000 unchanged (locked contract Phase 254 / D-03)."
  - "Card route include_in_schema=False — crawler-only HTML surface, no OpenAPI/SDK change needed for this route."
  - "card route returns 404 (not 410) for expired tokens — do not leak expired-vs-missing distinction to crawlers."
  - "OgImageUploadRequest.max_length=750_000 — generous for 1200x630 JPEG (~540KB base64); separate schema from ThumbnailUploadRequest."
metrics:
  duration: "5m 24s"
  completed_date: "2026-05-28"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 3
---

# Phase 1142 Plan 01: OG-Image Social Cards (SHARE-08 Backend) Summary

**One-liner:** SHARE-08 backend: per-map OG/Twitter social-card HTML route (`/card`), dedicated 1200x630 og-image PUT/GET pipeline, `og_image_uri` column in migration 0024, and `MapResponse.og_image_url` — all security tests (T-1142-01 XSS, T-1142-02 private-map leak) pinned and passing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | og_image_uri column + migration 0024 + OgImageUploadRequest + MapResponse.og_image_url | `50447c59` | models.py, schemas.py, 0024_maps_og_image_uri.py, test_maps_og_image.py |
| 2 | PUT/GET /maps/{id}/og-image/ routes + og_image_url in _build_map_response | `63967ef1` | router.py |
| 3 | GET /shared/{token}/card HTML OG meta route + escaping + access control | `c4f8fa37` | router.py |

## What Was Built

### Migration 0024

`backend/alembic/versions/0024_maps_og_image_uri.py` — adds `catalog.maps.og_image_uri TEXT NULL`. Upgrade adds the column; downgrade drops it. `down_revision = "0023_geolens_readonly_role"`. Applied cleanly in test DB (every test run migrates from baseline).

### OgImageUploadRequest

New Pydantic schema after `ThumbnailUploadRequest` (which is UNCHANGED at `max_length=100_000`). `OgImageUploadRequest.data_uri` cap is `max_length=750_000` — accommodates 1200x630 JPEG at quality 0.85 (~540KB base64). Locked contract D-03 preserved.

### MapResponse.og_image_url

Added `og_image_url: str | None = None` to `MapResponse` (after `thumbnail_url`). `_build_map_response` computes it as `/maps/{id}/og-image/` when `og_image_uri` is set, `None` otherwise.

### PUT /maps/{id}/og-image/

Owner-only (same `require_permission("edit_metadata")` + `check_map_ownership` as thumbnail PUT). PIL `Image.verify()` block cloned from thumbnail PUT. `maps/og-images/{map_id}.{ext}` storage key. `map_obj.og_image_uri = storage_key`. 502 on storage error; 400 on PIL failure; 422 on oversized payload.

### GET /maps/{id}/og-image/

`get_optional_user` + `_check_map_read_access`. `404` when `og_image_uri` is `None`. `public, max-age=86400` for public maps (longer than thumbnail's 3600s — OG images change less often).

### GET /shared/{token}/card

Registered at `GET /shared/{token}/card` BEFORE `GET /{map_id}` catch-all (Pitfall 6 — avoids UUID parse). `include_in_schema=False`.

Access control: `_validate_share_token(db, token)` → `isinstance(token_obj, str)` guard → `get_map` → `visibility != "public"` → 404. Identical to the `/m` viewer rule.

HTML output: `<!doctype html>` with `og:type`, `og:title`, `og:description`, `og:image`, `twitter:card=summary_large_image`, `twitter:title`, `twitter:description`, `twitter:image`, and `<meta http-equiv="refresh" content="0;url=/m/{token}">`. `Cache-Control: public, max-age=300`.

Absolute image URL: `str(request.base_url).rstrip("/")` + `/api/maps/{id}/og-image/` (or `/thumbnail/` or `/og-image.png` fallback). Pitfall 1 (relative URLs ignored by crawlers) mitigated.

HTML escaping: `html.escape()` on `map_obj.name` and `map_obj.description` before interpolation. Pitfall 3 + T-1142-01 mitigated.

## Test Coverage

`backend/tests/test_maps_og_image.py` — 22 tests, all passing.

| Test | Category | Status |
|------|----------|--------|
| test_og_image_upload_request_max_length_is_750000 | schema unit | PASS |
| test_og_image_upload_request_rejects_oversize | schema unit | PASS |
| test_thumbnail_upload_request_max_length_unchanged | schema unit | PASS |
| test_map_response_has_og_image_url_field | schema unit | PASS |
| test_map_model_has_og_image_uri_column | schema unit | PASS |
| TestOgImageRoutes::test_put_og_image_owner_stores_image | integration | PASS |
| TestOgImageRoutes::test_get_og_image_returns_bytes_after_upload | integration | PASS |
| TestOgImageRoutes::test_get_og_image_public_map_cache_control | integration | PASS |
| TestOgImageRoutes::test_get_og_image_404_when_none_uploaded | integration | PASS |
| TestOgImageRoutes::test_put_og_image_non_owner_forbidden | integration | PASS |
| TestOgImageRoutes::test_put_og_image_non_image_payload_rejected | integration | PASS |
| TestOgImageRoutes::test_map_response_includes_og_image_url_after_upload | integration | PASS |
| TestCardRoute::test_card_route_public_map_emits_og_meta | integration | PASS |
| TestCardRoute::test_card_route_og_image_url_is_absolute | integration | PASS |
| TestCardRoute::test_card_route_escapes_html_in_title **(T-1142-01 BLOCKING)** | security | PASS |
| TestCardRoute::test_card_route_404_for_private_map **(T-1142-02 BLOCKING)** | security | PASS |
| TestCardRoute::test_card_route_404_for_invalid_token **(T-1142-02 BLOCKING)** | security | PASS |
| TestCardRoute::test_card_route_404_for_expired_token **(T-1142-02 BLOCKING)** | security | PASS |
| TestCardRoute::test_card_route_uses_og_image_uri_when_set | integration | PASS |
| TestCardRoute::test_card_route_uses_thumbnail_when_no_og_image | integration | PASS |
| TestCardRoute::test_card_route_uses_site_fallback_when_no_images | integration | PASS |
| TestCardRoute::test_card_route_viewer_redirect_present | integration | PASS |

## Security Threat Mitigations

| Threat | STRIDE | Mitigation | Test |
|--------|--------|-----------|------|
| T-1142-01 XSS/meta injection | Tampering | `html.escape()` on map name + description | `test_card_route_escapes_html_in_title` PASS |
| T-1142-02 private-map leak | Information Disclosure | `_validate_share_token` + `visibility != public` → 404 | 3 access-control tests PASS |
| T-1142-03 image content spoofing | Spoofing | PIL `Image.verify()` in upload_og_image | `test_put_og_image_non_image_payload_rejected` PASS |
| T-1142-04 DoS oversize upload | DoS | `OgImageUploadRequest.max_length=750_000` → Pydantic 422 | `test_og_image_upload_request_rejects_oversize` PASS |
| T-1142-05 non-owner upload | EoP | `require_permission` + `check_map_ownership` | `test_put_og_image_non_owner_forbidden` PASS |
| T-1142-06 relative og:image URL | Tampering | `str(request.base_url)` absolute URL | `test_card_route_og_image_url_is_absolute` PASS |

## Deviations from Plan

None — plan executed exactly as written.

## FLAG for Phase 1143: OpenAPI/SDK Refresh Required

The following backend schema changes introduced in this plan ARE in the OpenAPI schema and require a SDK refresh in Phase 1143:

1. `PUT /api/maps/{id}/og-image/` — new route with `OgImageUploadRequest` body
2. `GET /api/maps/{id}/og-image/` — new route
3. `MapResponse.og_image_url: str | None` — new field on the existing maps response schema

Refresh order (per MEMORY.md dual-snapshot rule):
1. `make openapi` in the geolens repo (regenerates `openapi.json` from live FastAPI)
2. `npm run fetch-openapi` in the sibling docs repo (reads the live HTTP snapshot)

DO NOT regen SDK in Phase 1142. Phase 1143 (Quality Sweep & Close-Gate) handles this.

The `/card` route (`GET /shared/{token}/card`) is `include_in_schema=False` and does NOT require a refresh.

## Known Stubs

None — all data paths are fully wired. The `og_image_url` field in `MapResponse` correctly returns `None` until an og-image is uploaded, and the card route falls back to `/thumbnail/` then `/og-image.png` as documented.

## Self-Check: PASSED

Files verified:
- `backend/alembic/versions/0024_maps_og_image_uri.py` — exists, revision="0024", down_revision="0023_geolens_readonly_role"
- `backend/app/modules/catalog/maps/models.py` — `og_image_uri` column added after `thumbnail_uri`
- `backend/app/modules/catalog/maps/schemas.py` — `OgImageUploadRequest` (max_length=750_000), `MapResponse.og_image_url`, `ThumbnailUploadRequest.max_length=100_000` unchanged
- `backend/app/modules/catalog/maps/router.py` — `shared_map_card_endpoint` at GET /shared/{token}/card (before GET /{map_id}), `upload_og_image`, `get_og_image`, `og_image_url` in `_build_map_response`
- `backend/tests/test_maps_og_image.py` — 22 tests, all passing

Commits verified:
- `50447c59` — Task 1 (column, migration, schemas, initial tests)
- `63967ef1` — Task 2 (og-image PUT/GET routes, _build_map_response)
- `c4f8fa37` — Task 3 (/card route, escaping, access control)
