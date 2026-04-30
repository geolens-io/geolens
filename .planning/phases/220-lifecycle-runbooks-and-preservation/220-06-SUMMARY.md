---
phase: 220-lifecycle-runbooks-and-preservation
plan: 06
status: complete
completed: 2026-04-30
user_setup:
  - service: github_actions
    why: "CI lifecycle test requires private-repo checkout of geolens-enterprise"
    env_vars:
      - name: GEOLENS_ENTERPRISE_TOKEN
        source: "GitHub → Settings → Developer settings → Personal access tokens (fine-grained); scope content:read on ishiland/geolens-enterprise"
    dashboard_config:
      - task: "Add GEOLENS_ENTERPRISE_TOKEN as a repository secret"
        location: "GitHub repo Settings → Secrets and variables → Actions → New repository secret"
---

# Plan 220-06 — ci-overlay-install — SUMMARY

## What shipped

Amended `.github/workflows/ci.yml` `backend-test` job with three coordinated changes (Strategy A — smaller diff; first checkout left untouched, overlay landed at `$GITHUB_WORKSPACE/geolens-enterprise`):

1. **New step "Checkout geolens-enterprise (skip on fork PRs without secret)"** inserted immediately after the existing `actions/checkout@v4` step. Gated by `if: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN != '' }}` so fork PRs and unconfigured environments skip cleanly without failure.
2. **New step "Install enterprise overlay (if available)"** inserted after `uv sync --locked --dev`. Runs `uv add --editable ../geolens-enterprise` when the checkout landed; sets `OVERLAY_INSTALLED=1|0` in `$GITHUB_ENV` for the pytest step to read.
3. **Replaced "Run tests with coverage"** with a conditional `if [ "${OVERLAY_INSTALLED:-0}" = "1" ]` block that runs pytest with `-m 'not perf'` (overlay path) or `-m 'not perf and not lifecycle'` (fork-PR path). Coverage flags preserved verbatim, fail-under threshold unchanged at `58.5`.

Total diff: 27 insertions, 1 deletion (28 line changes < 60 budget).

## Verification (all passed)

- `repository: ishiland/geolens-enterprise` ✓
- `GEOLENS_ENTERPRISE_TOKEN` appears 3 times (≥2 expected: gate + token + log message) ✓
- `secrets.GEOLENS_ENTERPRISE_TOKEN != ''` (fork-PR gating idiom) ✓
- `uv add --editable ../geolens-enterprise` ✓
- `OVERLAY_INSTALLED` appears 3 times (set in install step + read in pytest step + log line) ✓
- Both pytest invocations present: `not perf` AND `not perf and not lifecycle` ✓
- YAML parses cleanly (`uv run --with pyyaml python3 -c "import yaml; yaml.safe_load(...)"` exits 0) ✓
- Diff scope: 28 lines < 60-line budget ✓
- First `actions/checkout@v4` step unchanged (no `path:` added — Strategy A) ✓
- `Upload backend coverage report` step unchanged ✓
- No other job (frontend-lint, frontend-test) modified ✓

## Decision compliance

- D-06: CI installs geolens-enterprise before backend test job.
- Claude's Discretion option (a): fork-PR gating via `secrets.X != ''`, no failure surfaces for OSS contributors.
- RESEARCH.md Pitfall 6: `secrets.X != ''` evaluation is correct for both unset-secret and fork-PR cases.
- A1 (secret name): `GEOLENS_ENTERPRISE_TOKEN`.
- Strategy A (path-restructure): smaller diff, first checkout left at `$GITHUB_WORKSPACE`.

## User-side prerequisite

Before this PR's CI run will exercise the lifecycle test on push to main, the repo owner must add a `GEOLENS_ENTERPRISE_TOKEN` GitHub Actions repository secret:

- Path: GitHub repo → Settings → Secrets and variables → Actions → New repository secret.
- Token type: fine-grained PAT.
- Scope: `Contents: Read` on `ishiland/geolens-enterprise`.
- Suggested rotation: ~1 year.

Without the secret, the workflow cleanly skips the lifecycle marker (no failure). With the secret, lifecycle tests run as part of the normal pytest invocation.

## Deviations

None.

## Self-Check: PASSED
