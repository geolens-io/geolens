---
phase: 1060-close-gate
artifact: catalog-cleanup-log
created: 2026-05-20T14:25:00Z
status: passed
delete_count: 7
verify_404_count: 7
---

# Phase 1060: Catalog Cleanup Log (CLEAN-01)

**Purpose:** ROADMAP success criterion #1 — delete v1012 smoke-repro datasets from the live `localhost:8080` catalog. Per A-03 user decision, Claude executes the DELETEs against the live admin API.

Plan 1060-03's named targets are the 3 v1012 fixtures (`ec18b546…`, `54763119…`, `667a6c65…`). G-01, G-07, and G-08..G-12 created 4 additional test datasets + 1 test map during MCP re-verify that also need cleanup — added to the target list per MCP log frontmatter `extra_cleanup_targets`.

## Targets

| ID | Title | Source | DELETE | Post-GET | Verdict |
|---|---|---|---|---|---|
| `ec18b546-d86d-4375-8e1f-8564b6a75687` | smoke-test-v1012 | v1012 reupload sandbox (Wildfire Response Points v3) | HTTP 204 | HTTP 404 | PASS |
| `54763119-0cf4-448e-a950-81551d090267` | Wildfire Response Points | v1012 fresh AGO import | HTTP 204 | HTTP 404 | PASS |
| `667a6c65-cdbc-4158-87f2-21a7e791ba7c` | Large Lakes | v1012 fresh OGC API import | HTTP 204 | HTTP 404 | PASS |
| `8c86dedc-c9b0-42b2-aa7d-621e18e82ecc` | Countries of the World | G-01 WFS test ingest (post-fix MCP re-verify) | HTTP 204 | HTTP 404 | PASS |
| `e44c1141-9f99-4ec4-86e2-c813eb2ba83e` | multi-layer-gpkg: addresses | G-07 fan-out test (post-fix MCP re-verify) | HTTP 204 | HTTP 404 | PASS |
| `0c1dceb8-4076-4be9-b0a1-f7738d02e96a` | multi-layer-gpkg: buildings | G-07 fan-out test (post-fix MCP re-verify) | HTTP 204 | HTTP 404 | PASS |
| `a5e0a16a-03a2-4948-96b2-dcc11b6158a6` | BSE-01 reverify (map) | G-08..G-12 BSE-01 reverify test map | HTTP 204 | HTTP 404 | PASS (map, not dataset) |

## Execution Method

Used the admin API via Bash + curl per A-03:

1. `POST /api/auth/login` with `admin/admin` → captured Bearer token.
2. For each dataset: `GET /api/datasets/{id}` to extract `title` (the DELETE endpoint requires `confirm_title` per `backend/app/modules/catalog/datasets/api/router.py:382`).
3. `DELETE /api/datasets/{id}` with JSON body `{"confirm_title": "<title>"}` — expect HTTP 204.
4. `GET /api/datasets/{id}` → expect HTTP 404 (verifies cascade cleanup completed).
5. For the map: `DELETE /api/maps/{id}` (no `confirm_title` required) — expect HTTP 204; verify with GET → 404.

**Note on trailing-slash:** `DELETE /api/datasets/{id}` works without trailing slash; `DELETE /api/maps/{id}/` returned HTTP 307 (redirect to internal hostname) while `DELETE /api/maps/{id}` (no slash) returned 204. Mirror behavior pinned in MEMORY.

## Acceptance

- **CLEAN-01 (3 named fixtures):** PASS — all 3 datasets deleted + verified 404.
- **Extra targets (G-01 + G-07 + G-08..G-12 outputs):** PASS — 3 datasets + 1 map deleted to keep the dev catalog clean post-close-gate.
- **Total:** 7/7 deletes returned 204; 7/7 post-deletion GETs returned 404. Zero leftover state from v1013 close-gate work in the dev catalog.
