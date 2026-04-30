---
status: partial
phase: 220-lifecycle-runbooks-and-preservation
source: [220-VERIFICATION.md]
started: 2026-04-30
updated: 2026-04-30
---

## Current Test

UAT-2 (GitHub secret + CI observation) — awaiting user to add `GEOLENS_ENTERPRISE_TOKEN` repository secret.

## Tests

### 1. End-to-end lifecycle pytest execution
expected: `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` exits 0 with `test_overlay_removal_preserves_saml_data PASSED`. Requires Docker (PostgreSQL + PostGIS + pgvector test stack) and an editable install of `~/Code/geolens-enterprise`. Test is correctly authored — all 13 static grep assertions pass and `pytest --collect-only` confirms collection (1 item).
result: passed (1 passed in 3.04s, after fixing two real bugs surfaced during UAT — see Notes)

### 2. Add GEOLENS_ENTERPRISE_TOKEN repository secret + observe CI
expected: After the user adds `GEOLENS_ENTERPRISE_TOKEN` (fine-grained PAT, `Contents: Read` on `geolens-io/geolens-enterprise`) at GitHub repo Settings → Secrets and variables → Actions, the next push to `main` runs the `backend-test` job with `OVERLAY_INSTALLED=1` and the log line "Running pytest with lifecycle marker INCLUDED". Lifecycle test passes in CI.
result: pending (out-of-band: user must add the secret in GitHub repo Settings)

## Notes

UAT-1 surfaced two real bugs in the phase 220 deliverables that were fixed inline (commit `ca9a5e8a`):

1. **`test_lifecycle.py`** — original code compared `survivor.idp_certificate == encrypt_secret(LIFECYCLE_CERT_PEM)`, but Fernet uses a random IV per call so the two ciphertexts never matched. Fixed by decrypting the survivor and comparing against the plaintext (also strengthens the assertion: column persisted AND value is recoverable).
2. **`.github/workflows/ci.yml`** — `repository:` was set to `ishiland/geolens-enterprise`, but the actual remote is `geolens-io/geolens-enterprise` (confirmed via `git remote -v` in the sibling repo). Without the fix, the cross-repo checkout would have failed in CI even after the secret is added.

After both fixes, lifecycle test runs end-to-end locally:

```
============================= test session starts ==============================
tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data PASSED [100%]
======================== 1 passed, 16 warnings in 3.04s ========================
```

## Summary

total: 2
passed: 1
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
