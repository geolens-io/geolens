---
status: partial
phase: 220-lifecycle-runbooks-and-preservation
source: [220-VERIFICATION.md]
started: 2026-04-30
updated: 2026-04-30
---

## Current Test

[awaiting human testing]

## Tests

### 1. End-to-end lifecycle pytest execution
expected: `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` exits 0 with `test_overlay_removal_preserves_saml_data PASSED`. Requires Docker (PostgreSQL + PostGIS + pgvector test stack) and an editable install of `~/Code/geolens-enterprise`. Test is correctly authored — all 13 static grep assertions pass and `pytest --collect-only` confirms collection (1 item). Only runtime execution requires infrastructure the verifier could not start in-session.
result: [pending]

### 2. Add GEOLENS_ENTERPRISE_TOKEN repository secret + observe CI
expected: After the user adds `GEOLENS_ENTERPRISE_TOKEN` (fine-grained PAT, `Contents: Read` on `ishiland/geolens-enterprise`) at GitHub repo Settings → Secrets and variables → Actions, the next push to `main` runs the `backend-test` job with `OVERLAY_INSTALLED=1` and the log line "Running pytest with lifecycle marker INCLUDED". Lifecycle test passes in CI.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
