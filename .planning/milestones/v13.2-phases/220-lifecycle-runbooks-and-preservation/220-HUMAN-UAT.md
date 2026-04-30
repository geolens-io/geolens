---
status: partial
phase: 220-lifecycle-runbooks-and-preservation
source: [220-VERIFICATION.md]
started: 2026-04-30
updated: 2026-04-30
---

## Current Test

UAT-2 (CI observation) — deferred to 2026-05-01 (free-tier Actions minutes reset). Secret is set; workflow file loads correctly; only blocker is org-level billing.

## Tests

### 1. End-to-end lifecycle pytest execution
expected: `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` exits 0 with `test_overlay_removal_preserves_saml_data PASSED`. Requires Docker (PostgreSQL + PostGIS + pgvector test stack) and an editable install of `~/Code/geolens-enterprise`. Test is correctly authored — all 13 static grep assertions pass and `pytest --collect-only` confirms collection (1 item).
result: passed (1 passed in 3.04s, after fixing two real bugs surfaced during UAT — see Notes)

### 2. Add GEOLENS_ENTERPRISE_TOKEN repository secret + observe CI
expected: After the user adds `GEOLENS_ENTERPRISE_TOKEN` (fine-grained PAT, `Contents: Read` on `geolens-io/geolens-enterprise`) at GitHub repo Settings → Secrets and variables → Actions, the next push to `main` runs the `backend-test` job with `OVERLAY_INSTALLED=1` and the log line "Running pytest with lifecycle marker INCLUDED". Lifecycle test passes in CI.
result: deferred to 2026-05-01 — secret is set; workflow file is valid; remaining blocker is the geolens-io free-tier GitHub Actions minutes exhaustion (every push event since 2026-04-27 has failed at the runner-assignment step, `runner_id: 0`, `steps: []`). Free-tier resets tomorrow. Re-run by pushing any commit to `main` after reset and confirming the `Backend Tests` job log shows `Running pytest with lifecycle marker INCLUDED` and the lifecycle test passes.

## Notes

UAT surfaced three real bugs in the phase 220 deliverables that were fixed inline:

1. **`test_lifecycle.py`** (commit `ca9a5e8a`) — original code compared `survivor.idp_certificate == encrypt_secret(LIFECYCLE_CERT_PEM)`, but Fernet uses a random IV per call so the two ciphertexts never matched. Fixed by decrypting the survivor and comparing against the plaintext (also strengthens the assertion: column persisted AND value is recoverable).
2. **`.github/workflows/ci.yml` repo owner** (commit `ca9a5e8a`) — `repository:` was set to `ishiland/geolens-enterprise`, but the actual remote is `geolens-io/geolens-enterprise` (confirmed via `git remote -v` in the sibling repo). Without the fix, the cross-repo checkout would have failed in CI even after the secret is added.
3. **`.github/workflows/ci.yml` step-level secret in `if:`** (commit `4c2b0479`) — `if: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN != '' }}` caused GitHub's workflow validator to reject the file (run 25161720335 failed in 0s with `total_count: 0` jobs). Refactored to probe the secret in a normal run step that writes `HAS_ENTERPRISE_TOKEN=1|0` to `$GITHUB_ENV`, and gate the cross-repo checkout on `env.HAS_ENTERPRISE_TOKEN == '1'`. Workflow now loads cleanly (10 jobs spawned in run 25161889207).

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
