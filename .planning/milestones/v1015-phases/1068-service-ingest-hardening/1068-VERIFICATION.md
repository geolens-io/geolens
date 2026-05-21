---
phase: 1068
status: passed
requirements_satisfied: 2
requirements_total: 2
shipped: 2026-05-20
---

# Phase 1068 VERIFICATION — Service Ingest Hardening

## Phase goal

Bearer tokens are never observable in subprocess environments, and `.vrt` ingest is hardened against bypass and path-traversal attacks.

## Requirement coverage

| REQ-ID | Status | Evidence |
|---|---|---|
| **IA-P1-06** | ✓ Verified | `run_ogr2ogr_service` now writes the `Authorization: Bearer <token>` line to a 0600 tempfile, sets `GDAL_HTTP_HEADER_FILE=<path>` in subprocess env, and unlinks the file in `finally`. `GDAL_HTTP_HEADERS` env var is removed from the codebase. 4/4 unit tests pin: token absent from env, no-token = no file, 0600 perms, cleanup-on-failure. |
| **IA-P1-03** | ✓ Verified | `validate_vrt_body` enforces `<VRTDataset` root + rejects `..` segments + rejects absolute paths outside the GDAL VSI allowlist (7 prefixes). `validate_file_content` routes `.vrt` through it. `_build_vrt` subprocess inherits `_VRT_SAFE_ENV` overlay (3 GDAL safety vars). 14/14 unit tests cover XML sniff, traversal, VSI allowlist, and env clamp. |

## Success criteria

- **No `Authorization:` substring in subprocess env** — ✓ Test `test_token_not_in_subprocess_env_via_header_file` asserts `GDAL_HTTP_HEADERS not in env`.
- **Invalid `.vrt` XML rejected at validation** — ✓ Tests `test_non_vrt_xml_rejected`, `test_empty_vrt_rejected`, `test_plaintext_with_vrt_extension_rejected`.
- **Path-traversal in `<SourceFilename>` blocked** — ✓ Tests `test_dotdot_segment_rejected`, `test_absolute_filesystem_path_rejected`, `test_multiple_sources_one_bad_rejected`.
- **Worker env caps set before GDAL VRT operations** — ✓ Test `test_gdalbuildvrt_subprocess_uses_safe_env` asserts `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=tif,tiff,vrt`, `VRT_VIRTUAL_OVERVIEWS=NO`, `GDAL_HTTP_FOLLOWLOCATION=NO`.

## Files touched

- `backend/app/processing/ingest/ogr.py` — `run_ogr2ogr_service` switched to `GDAL_HTTP_HEADER_FILE` with tempfile lifecycle in try/finally.
- `backend/app/processing/ingest/validation.py` — new `validate_vrt_body` + `.vrt` dispatch in `validate_file_content`.
- `backend/app/processing/raster/vrt.py` — new `_VRT_SAFE_ENV` overlay + `_gdal_safe_env()` helper applied to `_build_vrt` subprocess.

## Commit chain

1. (current) `feat(1068): service ingest hardening — IA-P1-06 + IA-P1-03`

## Deferred to Phase 1070 close-gate

- Full backend pytest run.
- `pre-commit run` to confirm the `ssrf-safe-client` hook (v1014 SEC-GUARD-01) still passes on the touched files.

## Verdict

**PASSED** — 2/2 requirements satisfied. 18/18 unit tests green. Defense-in-depth applied at validation, subprocess env, and GDAL config layers.
