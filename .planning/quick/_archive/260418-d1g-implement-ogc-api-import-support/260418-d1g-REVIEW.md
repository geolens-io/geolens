---
phase: 260418-d1g-implement-ogc-api-import-support
reviewed: 2026-04-18T00:00:00Z
depth: quick
files_reviewed: 18
files_reviewed_list:
  - backend/alembic/versions/2026_04_18_0001-add_ogcapi_features_source_format.py
  - backend/app/modules/catalog/datasets/domain/models.py
  - backend/app/modules/catalog/sources/adapters/ogcapi.py
  - backend/app/modules/catalog/sources/preview.py
  - backend/app/modules/catalog/sources/probe.py
  - backend/app/processing/ingest/ogr.py
  - backend/app/processing/ingest/tasks_common.py
  - frontend/src/components/import/ServiceUrlForm.tsx
  - frontend/src/components/import/WorkflowRail.tsx
  - frontend/src/i18n/labels.ts
  - frontend/src/i18n/locales/de/common.json
  - frontend/src/i18n/locales/de/import.json
  - frontend/src/i18n/locales/en/common.json
  - frontend/src/i18n/locales/en/import.json
  - frontend/src/i18n/locales/es/common.json
  - frontend/src/i18n/locales/es/import.json
  - frontend/src/i18n/locales/fr/common.json
  - frontend/src/i18n/locales/fr/import.json
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 260418-d1g: Code Review Report

**Reviewed:** 2026-04-18
**Depth:** quick
**Files Reviewed:** 18
**Status:** issues_found

## Summary

This change introduces an OGC API Features import adapter alongside WFS and ArcGIS FeatureServer as the third supported service type. The backend implementation (`ogcapi.py`, `probe.py`, `tasks_common.py`, `preview.py`) is consistent with the existing adapter contract and the SSRF gate is correctly applied upstream before `detect_service_type` is invoked. The migration is structurally correct and the `models.py` CHECK constraint matches. No hardcoded secrets, dangerous function misuse, or empty catch blocks were found.

Two warnings and three info items follow, dominated by missing i18n translation keys and a secondary-URL SSRF gap in the new adapter.

---

## Warnings

### WR-01: SSRF gate only covers the primary URL — /conformance secondary fetch is unprotected

**File:** `backend/app/modules/catalog/sources/adapters/ogcapi.py:83-96`
**Issue:** `probe_ogcapi` performs a second HTTP request to the `/conformance` URL obtained from the landing page response (`conformance_href`). The upstream probe router calls `validate_url_for_ssrf(request.url)` against the user-supplied base URL before `detect_service_type` is invoked, but that check does not cover URLs injected via the service's own JSON response. A malicious OGC API landing page can return a `links` entry with `"rel": "conformance"` and `"href": "http://169.254.169.254/latest/meta-data/"` (or any other private address). `urljoin(url, conformance_href)` preserves absolute URLs as-is, so a fully-qualified private URL in the `href` bypasses the original SSRF gate entirely.

**Fix:** Validate the resolved `abs_href` before fetching it:
```python
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf

if conformance_href:
    abs_href = urljoin(url, conformance_href)
    try:
        await validate_url_for_ssrf(abs_href)
    except SSRFError:
        logger.debug(
            "OGC API probe: conformance href failed SSRF check, skipping",
            href=abs_href,
        )
    else:
        try:
            conf_resp = await client.get(abs_href, headers=headers)
            ...
```

This matches the pattern the reupload router already uses (`router_reupload.py:156`).

---

### WR-02: Missing i18n translation keys — new UI strings will silently fall back to English in all locales

**File:** `frontend/src/components/import/ServiceUrlForm.tsx:154,167,186,288` and `frontend/src/components/import/WorkflowRail.tsx:29-38,93-113,129-152`
**Issue:** Both components call `t(key, { defaultValue: '...' })` for a large set of new translation keys (`serviceUrl.detectedLabel`, `serviceUrl.clear`, `serviceUrl.probe`, `serviceUrl.supported`, `serviceUrl.layersAvailable`, `serviceUrl.noLayers`, `rail.stageTitle`, `rail.stageDesc`, `rail.reviewTitle`, `rail.reviewDesc`, `rail.importTitle`, `rail.importDesc`, `rail.whatImported`, `rail.vectorLabel`, `rail.vectorDesc`, `rail.rasterLabel`, `rail.rasterDesc`, `rail.tableLabel`, `rail.tableDesc`, `rail.tip`, `rail.tipText`, `rail.workflow`, `rail.registerHint`, `rail.serviceHint`, `rail.registerDesc`, `rail.serviceDesc`, `rail.registerNote`, `rail.serviceNote`, `rail.comparedToUpload`, `rail.compareRegister`, `rail.compareService`). None of these keys exist in any locale file (en, de, es, fr). All four `import.json` files are identical in line count and none contain a `"rail"` block or the new `serviceUrl.*` keys.

The `defaultValue` fallback means users always see English text regardless of their language setting — this is a regression for the de/es/fr locales that were previously fully translated for the `serviceUrl` section.

**Fix:** Add the missing keys to all four `import.json` locale files. At minimum, add them to `en/import.json` as the source-of-truth and translate for de/es/fr:
```json
// en/import.json — add to "serviceUrl" block:
"detectedLabel": "Service URL — detected",
"clear": "Clear",
"probe": "Probe →",
"supported": "Supported:",
"layersAvailable": "{{count}} layers available",
"noLayers": "No layers were found in this service.",

// en/import.json — add new top-level "rail" block:
"rail": {
  "workflow": "Workflow",
  "stageTitle": "Stage files",
  "stageDesc": "Drop or pick files. No commit yet — you can remove any before detection.",
  "reviewTitle": "Review detection",
  "reviewDesc": "Confirm geometry type, CRS, schema, and preview for each file.",
  "importTitle": "Import & catalog",
  "importDesc": "Tile, index, publish — datasets appear in the Catalog immediately.",
  "whatImported": "What gets imported",
  "vectorLabel": "Vector",
  "vectorDesc": "tiled to MVT, spatial index, reprojected to 3857 on read.",
  "rasterLabel": "Raster",
  "rasterDesc": "converted to COG, overviews built, bands kept intact.",
  "tableLabel": "Tabular",
  "tableDesc": "ingested as a joinable table. Optionally specify geometry columns during import.",
  "tip": "Tip",
  "tipText": "Drop multiple files at once to create a batch. Each file becomes its own dataset — you can review and adjust metadata before committing.",
  "registerHint": "Registering existing infrastructure",
  "serviceHint": "Connecting remote services",
  "registerDesc": "Register existing PostGIS tables as datasets — GeoLens tiles them on the fly from your database.",
  "serviceDesc": "Connect a remote WFS, ArcGIS FeatureServer, or OGC API Features service. GeoLens imports the layer into the catalog for tiling and querying.",
  "registerNote": "No data copied · tiles generated directly from your tables",
  "serviceNote": "Service tokens are used during import only and are not persisted",
  "comparedToUpload": "Compared to Upload",
  "compareRegister": "Upload ingests from a file. Register points at an existing table — no duplication, but the table must stay in your database.",
  "compareService": "Upload ingests from a file. Service URL fetches from a remote API and imports the data into GeoLens for local tiling and querying."
}
```

---

## Info

### IN-01: `probe_ogcapi` accepts a service that advertises no conformsTo and no /conformance link if it has a "data" rel link

**File:** `backend/app/modules/catalog/sources/adapters/ogcapi.py:65-107`
**Issue:** The conformance check has a `has_data_link` escape hatch: if a landing page has no `conformsTo` array and no `conformance` link but does have a link with `"rel": "data"`, the adapter skips conformance validation entirely (`if not conforms_to and not has_data_link: return None` at line 98, and `if not is_ogc_features and not has_data_link: return None` at line 106-107). This means any JSON service that returns `{"links": [{"rel": "data", "href": "..."}]}` on its landing page will be probed as an OGC API Features service, which will then hit `/collections`. This is more permissive than the WFS adapter (which requires valid WFS XML) and could cause false-positive probe attempts against non-OGC endpoints. This is acceptable if intentional but worth documenting explicitly.

**Fix:** If this is intentional (to support OGC API implementations that omit conformance declarations in the root), add a code comment explaining the decision. Otherwise, tighten to require either a valid `conformsTo` or a working `/conformance` endpoint.

---

### IN-02: `enrich_ogcapi_layers` does not propagate `TimeoutError` — timeout leaves process uncleaned

**File:** `backend/app/modules/catalog/sources/adapters/ogcapi.py:178-214`
**Issue:** The enrichment function uses `asyncio.wait_for(proc.communicate(), timeout=30.0)` but the `TimeoutError` handler at line 208 only calls `logger.debug` and returns a partial result — it does not kill the subprocess. If the `ogrinfo` process times out, it is left running as a zombie until the OS reclaims it. Compare to `ogr.py:_communicate_with_timeout` which explicitly calls `proc.kill()` followed by `proc.wait()` on timeout. The WFS adapter has the same gap (it predates the `_communicate_with_timeout` helper), but this is the right moment to use the shared helper.

**Fix:**
```python
from app.processing.ingest.ogr import _communicate_with_timeout

# Replace lines 178-214 in _enrich_one:
try:
    stdout, stderr = await _communicate_with_timeout(
        proc, timeout=30.0, tool_name="ogrinfo"
    )
except IngestionError:
    return {**layer, "geometry_type": None, "feature_count": None}
```

This also applies to `wfs.py:enrich_wfs_layers` which has the same pattern, but that is out of scope for this review.

---

### IN-03: Migration `down_revision` is a literal string — not verified against actual Alembic chain

**File:** `backend/alembic/versions/2026_04_18_0001-add_ogcapi_features_source_format.py:13`
**Issue:** `down_revision = "c3d4e5f6a7b8"` uses a placeholder-looking hex value. If this does not correspond to the actual previous migration revision ID in the Alembic chain, `alembic upgrade head` will fail with a "Can't locate revision" error. This is worth confirming matches the real prior migration's `revision` field before deploying.

**Fix:** Run `alembic history` and verify `c3d4e5f6a7b8` matches the actual head revision before merging.

---

_Reviewed: 2026-04-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
