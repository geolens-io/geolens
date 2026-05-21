---
created: 2026-05-20T00:00:00Z
title: "IN-02: run_ogr2ogr missing comment explaining GDAL_HTTP_FOLLOWLOCATION omission"
area: maintainability
phase: 1061
resolves_phase: 1070
severity: info
source: 1061-REVIEW.md
files:
  - backend/app/processing/ingest/ogr.py
---

## Finding

Phase 1061 REVIEW.md IN-02 (informational, not a blocker).

`run_ogr2ogr` (file-ingest path) at `backend/app/processing/ingest/ogr.py:524-537`
does not set `GDAL_HTTP_FOLLOWLOCATION=NO` in the subprocess env, while
`run_ogr2ogr_service` (HTTP-ingest path) does.

This is intentional: `run_ogr2ogr` processes local file paths only, so libcurl
redirect control is irrelevant. The Plan 04 SUMMARY documents this explicitly.

The issue is the absence of a comment in `run_ogr2ogr` explaining why the env
override is absent, creating a "why is this missing here?" question for future
maintainers who read `run_ogr2ogr_service` and expect consistency.

## Solution

Add a one-line comment at the subprocess creation site in `run_ogr2ogr`:

```python
# GDAL_HTTP_FOLLOWLOCATION not set here — run_ogr2ogr processes local file
# paths only; no libcurl redirect control needed (contrast: run_ogr2ogr_service).
proc = await asyncio.create_subprocess_exec(...)
```

## Deferred Rationale

Maintainability-only change. Deferred from Phase 1061 per review scope
(info-only findings deferred to pending todos).
