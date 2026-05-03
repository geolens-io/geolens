---
phase: 228-run-cold-publish-workflows
plan: 01
subsystem: infra
tags: [github-actions, pypi, npm, trusted-publishing, oidc, uv, docker]

requires: []
provides:
  - publish-sdks.yml migrated from UV_PUBLISH_TOKEN to OIDC Trusted Publishing with pre-flight gates
  - publish-cli.yml migrated from UV_PUBLISH_TOKEN to OIDC Trusted Publishing with pre-flight gate
  - verify-published.yml new workflow with two Docker-based smoke jobs (python:3.13-slim, node:22-slim)
affects: [228-02, 228-03, 228-04]

tech-stack:
  added: []
  patterns:
    - "PyPI Trusted Publishing via uv publish --trusted-publishing automatic (OIDC, no long-lived token)"
    - "Pre-flight name-availability gate inline in workflow (pip3 index versions / npm view exit-code driven)"
    - "Clean-machine Docker smoke verification via docker run --rm inside GitHub Actions job"

key-files:
  created:
    - .github/workflows/verify-published.yml
  modified:
    - .github/workflows/publish-sdks.yml
    - .github/workflows/publish-cli.yml

key-decisions:
  - "Use uv publish --trusted-publishing automatic (not pypa/gh-action-pypi-publish) — minimal diff, already verified via uv --help"
  - "Pre-flight gate is informational (warning not exit 1) — allows re-publish path without blocking; hard-gate is a future one-line flip in else branch"
  - "TypeScript npm publish path unchanged (NODE_AUTH_TOKEN / secrets.NPM_TOKEN) — npm OIDC Trusted Publishing still beta"
  - "verify-published.yml uses createGeolensClient (runtime export from sdks/typescript/src/index.ts) not GeolensClient (type-only, would always print undefined)"

patterns-established:
  - "PyPI Trusted Publishing: drop env: UV_PUBLISH_TOKEN, add --trusted-publishing automatic, keep id-token: write permission"
  - "Pre-flight gate shape: if pip3 index versions <pkg> 2>&1 | grep -q 'No matching distribution'; then safe else ::warning::"
  - "Docker smoke verify: docker run --rm <image> sh -c '<install && import>'"

requirements-completed: [PUBLISH-01, PUBLISH-02, PUBLISH-03, PUBLISH-04]

duration: 8min
completed: 2026-05-02
---

# Phase 228 Plan 01: Workflow YAML Refactors + verify-published.yml Summary

**PyPI Trusted Publishing OIDC migration for both publish workflows + new Docker-based clean-machine smoke verification workflow**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-02T11:37:00Z
- **Completed:** 2026-05-02T11:45:04Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Migrated `publish-sdks.yml` Python publish step from `UV_PUBLISH_TOKEN` env injection to `uv publish --trusted-publishing automatic` (OIDC); TypeScript path unchanged
- Added pre-flight name-availability gates to both publish jobs in `publish-sdks.yml` (Python + TypeScript) and one gate in `publish-cli.yml`
- Migrated `publish-cli.yml` Python publish step same as above
- Created new `verify-published.yml` with two clean-machine Docker smoke jobs: `python:3.13-slim` (pip install geolens geolens-cli + smoke import) and `node:22-slim` (npm install @geolens/sdk + createGeolensClient export check)
- All three YAML files parse cleanly via `yaml.safe_load`

## Task Commits

1. **Task 1: Migrate publish-sdks.yml Python step to Trusted Publishing + add pre-flight gates** — `02116b29` (chore)
2. **Task 2: Migrate publish-cli.yml + create verify-published.yml** — `a98f41c9` (chore)

**Plan metadata:** (to be added in final commit)

## Files Created/Modified

- `.github/workflows/publish-sdks.yml` — header updated, Python publish step migrated to OIDC, pre-flight gates added for both Python and TypeScript jobs
- `.github/workflows/publish-cli.yml` — header updated, publish step migrated to OIDC, pre-flight gate added
- `.github/workflows/verify-published.yml` (NEW) — two Docker smoke jobs triggered by `workflow_dispatch` (optional `version` input) or `push` on `release/*` tags

## Decisions Made

- Chose `uv publish --trusted-publishing automatic` over `pypa/gh-action-pypi-publish@release/v1` — minimal line change, verified flag via `uv publish --help`, no additional action step required
- Pre-flight gate is informational (emits `::warning::` on re-publish, does not exit 1) — preserves first-publish safety signal while allowing re-publish; hard-gate can be enabled by changing `echo "::warning::..."` to `exit 1`
- TypeScript npm publish stays token-based (npm OIDC still beta as of research date 2026-05-02)
- `verify-published.yml` uses `createGeolensClient` (verified runtime export from `sdks/typescript/src/index.ts`) — not `GeolensClient` which is type-only and would silently pass without testing the actual function export

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification Results

```
# All three YAML files parse:
../.github/workflows/publish-sdks.yml: OK
../.github/workflows/publish-cli.yml: OK
../.github/workflows/verify-published.yml: OK

# publish-sdks.yml
uv publish trusted-publishing: 1  (Python job)
UV_PUBLISH_TOKEN: 0  (eliminated)
NODE_AUTH_TOKEN: 1  (TypeScript job preserved)
Pre-flight gates: 2  (Python + TypeScript)

# publish-cli.yml
uv publish trusted-publishing: 1
UV_PUBLISH_TOKEN: 0
Pre-flight gates: 1

# verify-published.yml
docker run --rm python:3.13-slim: 1
docker run --rm node:22-slim: 1
createGeolensClient: 1
typeof m.GeolensClient (false positive): 0
workflow_dispatch: 1
release/*: 1
id-token (must be 0 — verify has no OIDC): 0
```

## User Setup Required

Plan 02 (checkpoint) — human steps required before first hot publish:
1. Configure PyPI Trusted Publisher for `geolens` at https://pypi.org/manage/account/publishing/
2. Configure PyPI Trusted Publisher for `geolens-cli` at https://pypi.org/manage/account/publishing/
3. Create `@geolens` npm org at https://www.npmjs.com/org/create
4. Generate npm granular token (Bypass 2FA + Read/Write, @geolens scope) and add as `NPM_TOKEN` repo secret

## Next Phase Readiness

- Plan 02 (credential setup checkpoints) is fully unblocked — all YAML scaffolding is ready
- Plan 03 (workflow_dispatch publish triggers) is unblocked once Plan 02 human steps are complete
- Plan 04 (docs update) is independent and can run in parallel with Plans 02-03

---
*Phase: 228-run-cold-publish-workflows*
*Completed: 2026-05-02*
