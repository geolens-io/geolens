---
phase: 225-api-reference
plan: "03"
subsystem: docs/api-reference
tags: [starlight-openapi, openapi, docs, astro, sidebar]
dependency_graph:
  requires: [225-02]
  provides: [225-04, 225-05, 225-06, 225-08]
  affects: [getgeolens.com/docs/astro.config.mjs, getgeolens.com/docs/src/content/openapi/geolens.json]
tech_stack:
  added: [starlight-openapi@0.25.0]
  patterns: [Starlight plugin registration, openAPISidebarGroups spread, OAS 3.1 $defs-to-components promotion]
key_files:
  modified:
    - getgeolens.com/docs/astro.config.mjs
    - getgeolens.com/docs/package.json
    - getgeolens.com/docs/package-lock.json
    - getgeolens.com/docs/src/content/openapi/geolens.json
decisions:
  - "Registered starlight-openapi as a Starlight plugin (inside starlight({plugins:[...]})), not as a top-level Astro integration"
  - "Promoted $defs inline schemas to components/schemas to fix @apidevtools/json-schema-ref-parser OAS 3.1 incompatibility"
metrics:
  duration: ~8 minutes
  completed: 2026-04-26T12:09:39Z
  tasks_completed: 2
  files_modified: 4
---

# Phase 225 Plan 03: starlight-openapi Plugin Registration Summary

Installed starlight-openapi@0.25.0 exactly pinned, registered as a Starlight plugin in astro.config.mjs pointing at the committed snapshot, merged openAPISidebarGroups after the four Phase 224 sidebar entries, and auto-fixed an OAS 3.1 `$defs` incompatibility in the snapshot so the build emits all 18 tag pages under `/guides/api/operations/tags/`.

## What Was Built

- **starlight-openapi@0.25.0** installed with exact pin (no caret) — implements T-225-06 mitigation
- **astro.config.mjs** updated with:
  - Import: `import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';`
  - Plugin registration inside `starlight({ plugins: [...] })` with `base: 'guides/api'` and `schema: './src/content/openapi/geolens.json'`
  - `...openAPISidebarGroups` spread into sidebar AFTER the four Phase 224 autogenerate entries
- **Build output**: 237 pages total, 18 tag overview pages at `/guides/api/operations/tags/<slug>/`
- **geolens.json snapshot**: `$defs` inline schemas promoted to `components/schemas`, refs rewritten from `#/$defs/` to `#/components/schemas/` (OAS 3.1 compat fix)

## Verification Results

| Check | Result |
|-------|--------|
| `npm run build` exits 0 | PASS |
| Tag pages at `dist/guides/api/operations/tags/` | 18 directories |
| Hand-authored `dist/guides/api/auth/index.html` | EXISTS |
| Auto-tag `dist/guides/api/operations/tags/auth/index.html` | EXISTS (different namespace, no collision) |
| `starlight-openapi` version in package.json | `"0.25.0"` (exact, no caret) |
| `backend/app/api/main.py` diff | Empty — zero backend changes |

## Collision Confirmation

- Auto-generated tag page: `/guides/api/operations/tags/auth/index.html`
- Hand-authored page: `/guides/api/auth/index.html`
- These are different paths. No collision. Backend tag rename is unnecessary (D-33 confirmed).

## Tag Pages Rendered (18 total)

`admin`, `admin-embed-tokens`, `auth`, `config-ops`, `datasets`, `datasets---data`, `datasets---export`, `datasets---metadata`, `datasets---reupload`, `datasets---vrt`, `embed-tokens`, `features`, `maps`, `ogc-features`, `records`, `search`, `stac`, `tiles`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed OAS 3.1 $defs incompatibility in OpenAPI snapshot**
- **Found during:** Task 2 (build verification)
- **Issue:** The committed snapshot used JSON Schema Draft 2020-12 inline `$defs` within path response schemas. `@apidevtools/json-schema-ref-parser` (used by starlight-openapi) treats `#/$defs/...` as root-document pointers, so it failed with `Missing $ref pointer "#/$defs/OGCLink"`.
- **Fix:** Promoted 4 inline `$defs` schemas (`GeoJSONFeature`, `GeoJSONGeometry`, `Link`, `OGCLink`) to `components/schemas`. Rewrote all 10 `$ref: "#/$defs/..."` pointers to `#/components/schemas/...`. The snapshot remains valid OAS 3.1.
- **Files modified:** `docs/src/content/openapi/geolens.json`
- **Commit:** fd07d68

## Commits

| Commit | Description |
|--------|-------------|
| 3cbf10a | feat(225-03): install starlight-openapi@0.25.0 exact pin |
| fd07d68 | feat(225-03): register starlight-openapi plugin and merge sidebar groups |

## Self-Check: PASSED

- `docs/astro.config.mjs` modified — confirmed
- `docs/package.json` contains `"starlight-openapi": "0.25.0"` — confirmed
- `dist/guides/api/operations/tags/` has 18 directories — confirmed
- `dist/guides/api/auth/index.html` exists — confirmed
- Both commits exist in git log — confirmed
