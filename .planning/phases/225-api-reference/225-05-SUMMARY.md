---
phase: 225-api-reference
plan: "05"
subsystem: docs
tags: [ogc, stac, tiles, documentation]
dependency_graph:
  requires: [225-04]
  provides: [ogc.mdx]
  affects: [getgeolens.com/docs/src/content/docs/guides/api/]
tech_stack:
  added: []
  patterns: [Starlight MDX, Expressive Code fences, placeholder-host convention]
key_files:
  created:
    - getgeolens.com/docs/src/content/docs/guides/api/ogc.mdx
  modified: []
decisions:
  - "Tile tokens documented as HMAC-signed, session-bound, single-dataset-scoped — not generic API keys (T-225-04 mitigation)"
  - "One CQL2 example only in Records section (D-20)"
  - "Placeholder host https://geolens.example.com throughout (D-19)"
metrics:
  duration: "5 minutes"
  completed: "2026-04-25"
---

# Phase 225 Plan 05: OGC API & Standards Endpoints Summary

Created `/guides/api/ogc.mdx` — a single-page OGC/STAC/Tiles landing page for integrators using standards-based GeoLens endpoints.

## What Was Built

Hand-authored MDX page with five sections covering OGC API Common, Records, Features, STAC 1.1, and Tile endpoints. Each section follows the D-17 shape: what the standard provides, verified endpoint paths, curl example, and at least one client-tool example.

## Section Count and Order

Five sections in the exact D-16 order:

1. `## OGC API — Common`
2. `## OGC API — Records`
3. `## OGC API — Features`
4. `## STAC 1.1`
5. `## Tile Endpoints`

## Curl Example Count

Six curl examples total (one per section minimum, CQL2 filter gets a second):
- `GET /api/` and `GET /api/conformance` (Common)
- `GET /api/collections/datasets/items` (Records)
- CQL2 filter: `?filter=keywords%3D%27hydrology%27&filter-lang=cql2-text` (Records — only one)
- `GET /api/collections/{dataset_id}/items` (Features)
- `GET /api/stac/` (STAC)

## Client Tools Demonstrated

| Tool | Section | Example |
|------|---------|---------|
| QGIS MetaSearch | Records | OGC API - Records catalog connection |
| GDAL ogrinfo (OAPIF) | Records | `ogrinfo OAPIF:https://geolens.example.com/api/` |
| QGIS Add WFS | Features | OGC API Features layer connection |
| GDAL ogr2ogr (OAPIF) | Features | `ogr2ogr -f GPKG out.gpkg "OAPIF:..."` |
| pystac-client | STAC | `Client.open(...)` + search + item iteration |
| QGIS XYZ Tiles | Tiles | XYZ tile connection with token URL |

## Tile Token Disambiguation (T-225-04 Mitigation)

Tiles section contains explicit HMAC disambiguation language:
- States tokens are "HMAC-signed, scoped to a single dataset, and time-limited"
- States they are "**not** generic API keys"
- Explains purpose: embedded maps serving tiles without exposing permanent credentials
- URL shape described (`?token={hmac_signed_token}`) with no hard-coded fake token

## Verified Endpoint Paths

All paths verified against backend source files:

| Path | Source | Line |
|------|--------|------|
| `GET /api/` | `backend/app/standards/ogc/router.py` | 81 |
| `GET /api/conformance` | `backend/app/standards/ogc/router.py` | 128 |
| `GET /api/collections/datasets/items` | `backend/app/modules/catalog/search/router.py` | 1272 |
| `GET /api/collections/{dataset_id}/items` | `backend/app/standards/ogc/router.py` | 244 |
| `GET /api/stac/` | `backend/app/standards/stac/router.py` | 241 |
| `GET /api/stac/collections` | `backend/app/standards/stac/router.py` | 299 |
| `POST /api/stac/search` | `backend/app/standards/stac/router.py` | 1072 |
| `GET /api/tiles/{table_path}/{z}/{x}/{y}.pbf` | `backend/app/processing/tiles/router.py` | 563 |
| `POST /api/tiles/tokens/` | `backend/app/processing/tiles/router.py` | 510 |
| `GET /api/tiles/token/{dataset_id}/` | `backend/app/processing/tiles/router.py` | 468 |

## Deviations from Plan

None — plan executed exactly as written. The plan included the complete target content verbatim; the file was created matching the spec, with all verification checks passing.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. This plan creates documentation only.

## Self-Check: PASSED

- File exists: `/Users/ishiland/Code/getgeolens.com/docs/src/content/docs/guides/api/ogc.mdx` — FOUND
- Commit `3ff2569` exists in sibling repo — FOUND
- `astro check`: 0 errors, 0 warnings, 0 hints
- All grep verifications passed: H2 count (5), section names (5/5), placeholder host, no demo URL, OAPIF, pystac_client, cql2-text, HMAC, "not generic API keys", no fake tokens, ogr2ogr, cross-links
