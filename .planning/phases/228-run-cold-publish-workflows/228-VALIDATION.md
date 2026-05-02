---
phase: 228
slug: run-cold-publish-workflows
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-02
---

# Phase 228 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | GitHub Actions (workflow_dispatch runs) + bash assertions + `pip` / `npm` / `gh` CLIs |
| **Config files** | `.github/workflows/publish-sdks.yml`, `.github/workflows/publish-cli.yml`, `.github/workflows/verify-published.yml` (NEW) |
| **Quick run command** | `gh workflow run publish-sdks.yml -f target=both -f dry_run=true --repo geolens-io/geolens` (dry-run validation) |
| **Full hot-publish** | Same workflows with `dry_run=false` (after dry-run is green) |
| **Smoke check** | `gh workflow run verify-published.yml --repo geolens-io/geolens` (Docker-based clean-machine install) |
| **Estimated runtime** | ~3 min per dry-run; ~3-5 min per hot publish; ~2 min for verify-published |

---

## Sampling Rate

- **After every task commit (config-only tasks):** Run `actionlint .github/workflows/*.yml` (if installed) or `python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/publish-sdks.yml','.github/workflows/publish-cli.yml','.github/workflows/verify-published.yml']]"` to verify YAML.
- **After workflow YAML changes:** Run a `dry_run=true` workflow_dispatch to validate the workflow still parses and the build succeeds.
- **After Trusted Publishing setup (manual checkpoint):** Re-run the dry-run to confirm OIDC handshake works (or fails loudly if pending publisher misconfigured).
- **Before phase verify:** All three workflows must have at least one successful run on `main`; `verify-published.yml` must show `pip install` + `npm install` smoke checks exit 0.
- **Max feedback latency:** ~3 min per workflow run (network-bound by registry round-trips).

---

## Per-Task Verification Map

> Populated post-planning. Skeleton below maps the 4 phase requirements to verifiable commands.

| Task ID | Plan | Wave | Requirement | Threat Ref | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|----------|-----------|-------------------|-------------|--------|
| 228-XX-YY | XX | N | PUBLISH-01 | T-228-01 | Trusted Publishing configured + NPM_TOKEN present | shell-assert | `gh secret list --repo geolens-io/geolens \| grep NPM_TOKEN` returns 1 line; `gh secret list --repo geolens-io/geolens \| grep PYPI_TOKEN` returns 0 lines (Trusted Publishing path); curl PyPI publishing settings page (manual visual verify in VERIFICATION.md) | ✅ gh CLI | ⬜ pending |
| 228-XX-YY | XX | N | PUBLISH-02 | T-228-02 | publish-sdks.yml E2E green; geolens-sdk@1.0.0 on PyPI; @geolens/sdk@1.0.0 on npm | network-assert | `pip index versions geolens-sdk \| grep "1.0.0"` returns match; `npm view @geolens/sdk version` returns `1.0.0`; workflow run URL recorded in VERIFICATION.md | ✅ pip + npm CLIs | ⬜ pending |
| 228-XX-YY | XX | N | PUBLISH-03 | T-228-02 | publish-cli.yml E2E green; geolens@1.0.0 on PyPI | network-assert | `pip index versions geolens \| grep "1.0.0"` returns match; workflow run URL recorded in VERIFICATION.md | ✅ pip CLI | ⬜ pending |
| 228-XX-YY | XX | N | PUBLISH-04 | T-228-03 | Clean-machine install of all 3 packages succeeds | docker + assert | `gh workflow run verify-published.yml --repo geolens-io/geolens` then check completion exit 0; OR locally: `docker run --rm python:3.13-slim sh -c "pip install geolens-sdk geolens && geolens --version"` and `docker run --rm node:22-slim sh -c "npm install @geolens/sdk"` | ❌ W0 (new workflow file) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `.github/workflows/verify-published.yml` — NEW workflow file (Plan creates this; D-07 from CONTEXT.md). Two jobs: `verify-python` (Docker `python:3.13-slim`, runs `pip install geolens-sdk geolens && geolens --version && python -c "from geolens_sdk import GeolensClient"`) and `verify-typescript` (Docker `node:22-slim`, runs `npm install @geolens/sdk && node -e "import('@geolens/sdk').then(m => console.log(typeof m.GeolensClient))"`). Triggered by `workflow_dispatch` (with optional `version` input defaulting to `latest`). Both jobs must exit 0 for PUBLISH-04 verification.
- [ ] `actionlint` is NOT in the project toolchain today (verified). Optional: install `actionlint` via Homebrew or use `python3 -c "import yaml"` for YAML structural validation. Plan picks; minimum bar is YAML parses.
- [ ] No existing test infrastructure to install — pytest is unrelated to this CI/CD phase.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `@geolens` npm org claimed | PUBLISH-01 prerequisite (D-00) | Out-of-band; requires npm web UI + maintainer's account | (a) Visit <https://www.npmjs.com/org/geolens>; (b) Confirm org page renders (not 404); (c) Confirm maintainer account is listed as admin; (d) Document org-creation date in VERIFICATION.md. |
| PyPI Trusted Publishing for `geolens-sdk` configured | PUBLISH-01 (D-01) | Out-of-band; requires PyPI web UI | (a) Visit <https://pypi.org/manage/account/publishing/>; (b) Confirm a "pending publisher" entry for `geolens-sdk` exists with Owner=`geolens-io`, Repo=`geolens`, Workflow=`publish-sdks.yml`, Environment=`(none)`; (c) Document setup screenshot/text in VERIFICATION.md. |
| PyPI Trusted Publishing for `geolens` (CLI) configured | PUBLISH-01 (D-01) | Out-of-band; PyPI web UI | (a) Same URL; (b) Confirm pending publisher entry for `geolens` with Workflow=`publish-cli.yml`; (c) Document in VERIFICATION.md. |
| `NPM_TOKEN` granular token generated with Bypass 2FA enabled | PUBLISH-01 (D-02) | Out-of-band; npm web UI | (a) Visit <https://www.npmjs.com/settings/~/tokens>; (b) Generate granular access token: name `geolens-sdk-ci-publish`, permissions Read+Write, scope `@geolens` org, Bypass 2FA enabled, max expiration; (c) Run `gh secret set NPM_TOKEN --body "$TOKEN" --repo geolens-io/geolens`; (d) Verify with `gh secret list`; (e) Document creation date + expiration in VERIFICATION.md. |
| README install instructions match published artifacts | PUBLISH-04 | Best validated end-to-end on a clean machine | (a) On a machine without the GeoLens checkout (or in a clean Docker container), run each install command from `README.md` / `docs/sdks.md` / `docs/cli.md`: `pip install geolens-sdk`, `npm install @geolens/sdk`, `pip install geolens`; (b) Each must succeed; (c) Document in VERIFICATION.md. The `verify-published.yml` workflow automates the Docker form of this but the README-instruction-validation is the human's check. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (planner fills per-task)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`verify-published.yml` is the only NEW file with automated checks)
- [ ] No watch-mode flags (irrelevant — this is a CI workflow phase)
- [ ] Feedback latency < 5 min per workflow run
- [ ] `nyquist_compliant: true` set in frontmatter (after planner fills the task table)

**Approval:** pending — planner to populate per-task map.
