---
phase: 228-run-cold-publish-workflows
plan: 02
status: complete
subsystem: release
tags: [pypi, npm, trusted-publishing, oidc, github-actions, credentials]

requires:
  - phase: 228-run-cold-publish-workflows
    plan: 01
    provides: publish-sdks.yml + publish-cli.yml migrated to PyPI Trusted Publishing and NPM_TOKEN-based npm publish
provides:
  - NPM_TOKEN repo secret confirmed present in geolens-io/geolens
  - PYPI_TOKEN repo secret confirmed absent; PyPI releases use Trusted Publishing
  - geolens PyPI project bootstrapped as 0.0.0 and Trusted Publisher added for publish-sdks.yml
  - geolens-cli PyPI pending publisher confirmed by maintainer for publish-cli.yml
  - @geolens npm organization and NPM_TOKEN scope confirmed by maintainer
affects: [228-03, 228-04, release-publish, docs-publishing]

tech-stack:
  added: []
  patterns:
    - "PyPI name bootstrap fallback: one-time 0.0.0 upload with account token, then add Trusted Publisher to existing project"
    - "Keep PYPI_TOKEN absent from GitHub; temporary account token stays local and is revoked after bootstrap"

key-files:
  created:
    - .planning/phases/228-run-cold-publish-workflows/228-02-SUMMARY.md
  modified:
    - .planning/ROADMAP.md

key-decisions:
  - "Post-plan pivot: publish the Python SDK as `geolens` and the CLI distribution as `geolens-cli`."
  - "Use a temporary 0.0.0 bootstrap upload because the PyPI pending-publisher form repeatedly returned 503 for `geolens`."
  - "Keep the real release target at 1.0.0 via Trusted Publishing after adding the publisher to the existing `geolens` project."

patterns-established:
  - "For blocked pending-publisher project-name setup, a temporary account-token upload can create the project; Trusted Publishing is then configured on the existing project page."

requirements-completed:
  - PUBLISH-01

duration: ~2h
completed: 2026-05-02
---

# Phase 228 Plan 02: Credential Setup Checkpoint Summary

**Release credentials are ready for hot publishing: npm credentials are present, PyPI token auth is not stored in GitHub, `geolens` is the Python SDK project with Trusted Publishing attached, and `geolens-cli` has its CLI publisher configured.**

## Performance

- **Duration:** ~2h including PyPI troubleshooting and bootstrap
- **Started:** 2026-05-02T21:10:00Z
- **Completed:** 2026-05-02T23:26:51Z
- **Tasks:** 1 blocking human-action checkpoint
- **Files modified:** 2 planning files

## Accomplishments

- Confirmed `NPM_TOKEN` exists in `geolens-io/geolens` and `PYPI_TOKEN` is absent.
- Maintainer confirmed the `@geolens` npm organization exists and the `NPM_TOKEN` token is scoped appropriately for publishing.
- Recovered from the PyPI `geolens` pending-publisher 503 by publishing a one-time `geolens==0.0.0` bootstrap release, then maintainer added the GitHub Actions Trusted Publisher to the existing `geolens` project for workflow `publish-sdks.yml`.
- Maintainer configured `geolens-cli` for GitHub Actions workflow `publish-cli.yml`.
- Verified `geolens==0.0.0` is visible on PyPI and `pip3 index versions geolens` returns the bootstrap version.

## Evidence

### GitHub Secrets

```text
$ gh secret list --repo geolens-io/geolens | grep -E '^(NPM_TOKEN|PYPI_TOKEN|GEOLENS_ENTERPRISE_TOKEN)' || true
GEOLENS_ENTERPRISE_TOKEN  2026-04-30T10:59:00Z
NPM_TOKEN                 2026-05-02T11:59:11Z
```

`PYPI_TOKEN` is intentionally absent from repository secrets. PyPI release workflows use OIDC Trusted Publishing.

### PyPI Project State

```text
$ pip3 index versions geolens
geolens (0.0.0)
Available versions: 0.0.0

$ python3 - <<'PY'
import urllib.request, json
with urllib.request.urlopen("https://pypi.org/pypi/geolens/json", timeout=10) as r:
    data = json.load(r)
print(data["info"]["name"], data["info"]["version"])
print(",".join(sorted(data["releases"].keys())))
PY
geolens 0.0.0
0.0.0
```

`geolens-sdk` is not a published package after the package-name pivot:

```text
$ pip3 index versions geolens-sdk
ERROR: No matching distribution found for geolens-sdk
```

### Maintainer Confirmations

- `@geolens` npm organization: confirmed by maintainer on 2026-05-02.
- `NPM_TOKEN` scope/read-write/Bypass 2FA: confirmed by maintainer on 2026-05-02.
- `geolens` existing-project Trusted Publisher for `publish-sdks.yml`: confirmed by maintainer on 2026-05-02 after bootstrap.
- `geolens-cli` pending publisher for `publish-cli.yml`: confirmed by maintainer on 2026-05-02.

## Task Commits

Plan metadata commit created after this summary.

## Files Created/Modified

- `.planning/phases/228-run-cold-publish-workflows/228-02-SUMMARY.md` — credential setup audit trail and PyPI bootstrap evidence.
- `.planning/ROADMAP.md` — marks Plan 228-02 complete.

## Decisions Made

- Pivoted final package names so the Python SDK uses `geolens` and the CLI distribution uses `geolens-cli`.
- Used a temporary local-only PyPI account token to publish `geolens==0.0.0` after the pending-publisher UI repeatedly returned 503 for `geolens`.
- Added Trusted Publishing to the existing `geolens` project after bootstrap so the real `1.0.0` release still uses OIDC through `publish-cli.yml`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Bootstrapped `geolens` project after PyPI pending-publisher 503**

- **Found during:** Task 1 (Combined credential setup runbook)
- **Issue:** PyPI accepted the `geolens-sdk` pending publisher but repeatedly returned HTTP 503 when creating the `geolens` pending publisher. Public PyPI APIs returned 404 for `geolens`, while third-party mirrors showed historical `geolens==0.0.1`, indicating a likely deleted/name-state edge case.
- **Fix:** Built a temporary `geolens==0.0.0` artifact from a copy of `cli/` under `/tmp`, uploaded it with a temporary PyPI account token, then had the maintainer add the Trusted Publisher to the now-existing `geolens` project.
- **Files modified:** No tracked package files; bootstrap artifacts were built under `/tmp/geolens-bootstrap-dist`.
- **Verification:** `pip3 index versions geolens` returns `0.0.0`; `https://pypi.org/pypi/geolens/json` returns `200`; maintainer confirmed the Trusted Publisher was added.
- **Committed in:** plan metadata commit.

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The public release name remains `geolens`; GitHub Actions still uses Trusted Publishing for the real `1.0.0` release. The only extra public artifact is `geolens==0.0.0`, which should be yanked after `geolens==1.0.0` is published and verified.

## Issues Encountered

- Initial PyPI API token attempts failed because the pasted value was the short token identifier, not the full `pypi-...` token. The final token parsed correctly as an account token and the upload succeeded.
- The temporary PyPI account token should be revoked now that the project has been bootstrapped and the Trusted Publisher is attached.

## User Setup Required

- Revoke the temporary PyPI account token created for the bootstrap upload.
- Keep the `NPM_TOKEN` rotation reminder aligned with its 90-day expiration.

## Next Phase Readiness

Plan 228-03 is unblocked:

- `publish-sdks.yml` can publish `geolens==1.0.0` to PyPI via Trusted Publishing and verify/publish `@geolens/sdk==1.0.0` via `NPM_TOKEN`.
- `publish-cli.yml` can publish `geolens-cli==1.0.0` to PyPI via Trusted Publishing.

---
*Phase: 228-run-cold-publish-workflows*
*Completed: 2026-05-02*
