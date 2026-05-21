# Phase 1068: Service Ingest Hardening - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous mode)

<domain>
## Phase Boundary

Two defense-in-depth hardenings:
1. **IA-P1-06** — Replace `GDAL_HTTP_HEADERS=Authorization: Bearer <token>` subprocess env (observable via `/proc/<pid>/environ`) with `GDAL_HTTP_HEADER_FILE` pointing at a 0600 tempfile.
2. **IA-P1-03** — VRT magic-byte + path-traversal guard + GDAL VSI extension allowlist clamp.

Out of phase: download token (1065), upload size (1066), heartbeat (1067), export (1069), hygiene (1070).

</domain>

<decisions>
## Implementation Decisions

### IA-P1-06 — GDAL_HTTP_HEADER_FILE

- Tempfile via `tempfile.mkstemp()` + explicit `os.chmod(0o600)` for clarity.
- `try/finally` cleanup — file is unlinked even when subprocess fails.
- `GDAL_HTTP_HEADER_FILE` is GDAL ≥2.3 (safe for modern deploys).

### IA-P1-03 — VRT hardening (3 layers)

- **Magic-byte sniff:** `validate_vrt_body` reads up to 256 KiB, skips optional `<?xml ?>` decl, asserts `<VRTDataset` root. Wired into `validate_file_content` via a `.vrt` shortcut (don't go through `EXTENSION_CONTENT_MAP` because XML magic isn't reliably distinguished from plaintext).
- **Path-traversal guard:** scan every `<SourceFilename>` body for `..` segments. Reject absolute paths EXCEPT GDAL VSI prefixes (`/vsis3/`, `/vsicurl/`, `/vsizip/`, `/vsigs/`, `/vsiaz/`, `/vsitar/`, `/vsimem/`). VSI URIs are how the COG manifest path legitimately references managed-storage assets.
- **GDAL VSI extension allowlist:** `_VRT_SAFE_ENV` overlay applied to the `gdalbuildvrt` subprocess in `raster/vrt.py:_build_vrt`. Vars: `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=tif,tiff,vrt`, `VRT_VIRTUAL_OVERVIEWS=NO`, `GDAL_HTTP_FOLLOWLOCATION=NO`. The first clamps what URL-fetched extensions GDAL will open; the second blocks implicit overview-pyramid expansion; the third blocks redirect-following inside the VRT build.

</decisions>

<code_context>
## Existing Code Insights

- `backend/app/processing/ingest/ogr.py:578-707` — `run_ogr2ogr_service` (the IA-P1-06 fix site).
- `backend/app/processing/ingest/ogr.py:21-54` — `_sanitize_authorization_token` (SEC-FU-04 from v1014) for token charset sanitization.
- `backend/app/processing/ingest/validation.py:57` — `validate_file_content` (extended).
- `backend/app/processing/raster/vrt.py:194-209` — `_build_vrt` subprocess call (env added).
- v1014 SEC-S04 `_revalidate_redirect` already runs on the `make_safe_client()` factory — no overlap.

</code_context>

<specifics>
## Specific Ideas

- VSI allow-list is intentionally generous (7 prefixes) — every GDAL VSI scheme that the COG/raster path legitimately consumes. Adding a new VSI scheme later requires updating both the allow-list in `validate_vrt_body` AND the `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` overlay (currently the latter only allows `tif,tiff,vrt`).
- Don't apply `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` to non-VRT subprocesses — it would break ZIP/GPKG/CSV URL fetches the rest of the pipeline relies on. Scoped only to `_build_vrt`.

</specifics>

<deferred>
## Deferred Ideas

- Apply the same `_gdal_safe_env()` overlay to all GDAL subprocesses (raster ingest, COG conversion). Speculative scope expansion.
- Lock down `<KernelFilteredSource>` and `<ComplexSource>` VRT XML branches with stricter parsing (currently we scan all `<SourceFilename>` bodies regardless of parent).
- Move `_VRT_SAFE_ENV` to `core.config` so deployments can override via env var (e.g., for COG providers that legitimately use `.tar` extensions).

</deferred>
