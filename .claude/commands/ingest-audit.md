# /ingest-audit - Ingestion, Export & VRT Lifecycle Audit

Audit GeoLens data lifecycle paths end to end: upload, preview, commit, reupload, background jobs, vector/table/raster processing, VRT creation, export formats, cleanup, and test coverage. Findings must cite file:line evidence and name the lifecycle state that can break.

**Usage:** `/ingest-audit` (full audit) or `/ingest-audit <scope>` where scope is `upload`, `jobs`, `vector`, `raster`, `vrt`, `export`, `ui`, or `tests`

Arguments: $ARGUMENTS

---

## INTAKE (Serial - do this first)

### Step 0: Determine scope

```bash
SCOPE="${ARGUMENTS:-full}"
echo "Scope: $SCOPE"
```

Scope routing:
- `upload`: run upload, preview, commit, validation, and temp-file cleanup checks.
- `jobs`: run background job, progress, retry, idempotency, and failure-state checks.
- `vector`: run vector/table ingestion, non-spatial table, SQL safety, and metadata checks.
- `raster`: run raster validation, COG/tile readiness, bounds/bands, and cleanup checks.
- `vrt`: run VRT source ownership, lifecycle, deletion/reupload, and builder rendering checks.
- `export`: run export format, CRS, streaming/temp-file, and authorization checks.
- `ui`: run frontend lifecycle UX checks.
- `tests`: run coverage and smoke parity checks only.
- `full`: run every section.

State the resolved scope in the report and mark skipped sections explicitly.

### Step 1: Inventory the lifecycle surface

```bash
# Backend processing and dataset API surface
find backend/app/processing/ingest backend/app/processing/export backend/app/processing/raster -type f -name "*.py" 2>/dev/null | sort
find backend/app/modules/catalog/datasets/api -type f -name "router*.py" 2>/dev/null | sort
find backend/app/modules/catalog/datasets/domain -type f -name "*.py" 2>/dev/null | sort
find backend/app/modules/catalog/sources -type f -name "*.py" 2>/dev/null | sort

# Frontend ingest/export/VRT surface
find frontend/src/api frontend/src/components/import frontend/src/components/dataset -type f 2>/dev/null | sort | grep -Ei "ingest|upload|vrt|reupload|export|source|validation"

# E2E and unit tests that should cover lifecycle behavior
find backend/tests frontend/src e2e -type f 2>/dev/null | sort | grep -Ei "ingest|upload|vrt|raster|export|reupload|non-spatial|dataset-detail"
```

### Step 2: Read canonical source files

```bash
# Ingest pipeline
for f in \
  backend/app/processing/ingest/router.py \
  backend/app/processing/ingest/schemas.py \
  backend/app/processing/ingest/service.py \
  backend/app/processing/ingest/tasks.py \
  backend/app/processing/ingest/tasks_common.py \
  backend/app/processing/ingest/tasks_vector.py \
  backend/app/processing/ingest/tasks_raster.py \
  backend/app/processing/ingest/tasks_vrt.py \
  backend/app/processing/ingest/metadata.py \
  backend/app/processing/ingest/validation.py \
  backend/app/processing/ingest/warnings.py; do
  echo "=== $f ==="
  cat "$f" 2>/dev/null
done

# Export, raster, and dataset lifecycle routers
for f in \
  backend/app/processing/export/router.py \
  backend/app/processing/export/service.py \
  backend/app/processing/export/schemas.py \
  backend/app/processing/export/ogr.py \
  backend/app/processing/raster/cog.py \
  backend/app/processing/raster/vrt.py \
  backend/app/modules/catalog/datasets/api/router_export.py \
  backend/app/modules/catalog/datasets/api/router_reupload.py \
  backend/app/modules/catalog/datasets/api/router_vrt.py; do
  echo "=== $f ==="
  cat "$f" 2>/dev/null
done
```

### Step 3: Optional live checks

```bash
# Only run if the local stack is healthy
curl -sf http://localhost:8080/health >/dev/null 2>&1 && npm run e2e:smoke:fixtures
curl -sf http://localhost:8080/health >/dev/null 2>&1 && npm run e2e:export

# Discover current OpenAPI paths for ingest/export/VRT
API_ORIGIN="${API_ORIGIN:-http://localhost:${API_PORT:-8001}}"
curl -s "$API_ORIGIN/openapi.json" 2>/dev/null | python3 -c "
import json, sys
spec = json.load(sys.stdin)
for p in sorted(spec.get('paths', {})):
    if any(k in p.lower() for k in ('ingest', 'export', 'vrt', 'reupload')):
        print(p, sorted(spec['paths'][p]))
" 2>/dev/null || echo "NO_RUNNING_INSTANCE"
```

---

## AUDIT CHECKS

### 1. Upload, preview, and commit contract

Verify:
- file type detection uses content sniffing, not extension alone
- size limits, allowed formats, and shapefile sidecars are enforced consistently
- preview output matches commit input and cannot be forged to reference another upload
- commit is idempotent or fails cleanly after partial success
- temp files, staged rows, and failed jobs are cleaned up
- progress, heartbeat, status, warnings, and error payloads are stable API contracts

Flag as P0 when an invalid file can be committed, another user's upload can be referenced, or partial failure leaves a ready dataset with missing data.

### 2. Vector and table ingestion

Check:
- GDAL/ogr subprocess calls quote paths and cannot be shell-injected
- SQL identifiers go through the repo's identifier quoting helpers
- geometry construction for X/Y and WKT columns validates SRID and coordinate ranges
- non-spatial tables keep schema, preview, search, and export behavior coherent
- transactions prevent ready datasets from pointing at missing or half-loaded tables
- metadata extraction updates extent, geometry type, feature count, schema, and quality score
- source connectors preserve open-core boundaries: one-shot WFS/ArcGIS/STAC/S3 import is Community; stored credentials, scheduled mirroring, recurring sync, connector health UI, and background re-sync require an Enterprise seam

### 3. Raster and VRT lifecycle

Check:
- raster validation distinguishes valid COGs, convertible GeoTIFFs, unsupported rasters, and corrupt files
- raster asset rows, file paths, bounds, band metadata, DEM flags, and tile URLs stay in sync
- VRT creation validates source ownership, source compatibility, band count, CRS, and missing-source behavior
- deleting, reuploading, or hiding a source dataset cannot silently break VRT rendering
- VRT and raster records behave consistently in catalog, builder, viewer, tiles, export, and permissions

### 4. Export correctness and safety

Check:
- export format allowlists match API schemas, frontend options, CLI docs, and OpenAPI
- CRS transforms are explicit and tested; exported geometry preserves SRID expectations
- large exports stream or spool safely and clean temp files
- table names, column names, filters, and bbox parameters are quoted/validated
- export authorization matches dataset visibility and role rules
- export failures return actionable errors without leaking filesystem paths

### 5. Frontend lifecycle UX

Read:
- `frontend/src/api/ingest.ts`, `frontend/src/api/vrt.ts`, `frontend/src/api/datasets.ts`
- `frontend/src/components/import/`
- `frontend/src/components/dataset/ReuploadDialog.tsx`, `ExportButton.tsx`, and validation/source tabs

Verify:
- upload, progress, cancellation/failure, retry, VRT creation, reupload, and export states are represented
- duplicate submissions and stale job polling cannot create confusing UI state
- errors preserve backend details that help remediation without exposing internals
- disabled actions explain permission, validation, or lifecycle blockers

### 6. Test and smoke coverage

Require focused coverage for:
- vector upload -> preview -> commit -> dataset detail
- non-spatial upload and export
- raster ingest and tile readiness
- VRT creation, source deletion/reupload behavior, and builder rendering
- export formats, CRS behavior, and unauthorized export attempts
- backend task failure paths and cleanup

Cross-check `npm run e2e:smoke:fixtures`, `npm run e2e:export`, backend pytest coverage, and frontend component tests. Missing VRT lifecycle tests are P1 unless the feature is explicitly disabled.

---

## DELIVERY

Write full reports to `docs-internal/audits/ingest-audit-{YYYYMMDD}.md`.

Report structure:
- Findings first, sorted P0/P1/P2
- Lifecycle map: upload, preview, commit, jobs, raster, VRT, export, cleanup
- Broken or missing tests
- Highest-value remediation plan
- Commands run and environment limits

---

## RELATIONSHIP TO OTHER COMMANDS

- `/perf-profile` covers ingest throughput and memory. This command covers lifecycle correctness.
- `/test-audit` covers test health. This command names the ingest/export/VRT tests that matter.
- `/sec-audit` covers broad security. This command flags ingest/export-specific injection, ownership, and path risks.
