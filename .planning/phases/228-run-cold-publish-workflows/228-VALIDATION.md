---
phase: 228
slug: run-cold-publish-workflows
status: ready
nyquist_compliant: true
wave_0_complete: true
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

| Task ID | Plan | Wave | Requirement | Threat Ref | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|----------|-----------|-------------------|-------------|--------|
| 228-01-T1 | 01 | 1 | PUBLISH-01 (YAML prep) | T-228-01, T-228-02 | publish-{sdks,cli}.yml refactored: drop UV_PUBLISH_TOKEN env, add `--trusted-publishing automatic`, add pre-flight name-availability gate with `force_publish` override input | yaml-lint + grep | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/publish-sdks.yml')); yaml.safe_load(open('.github/workflows/publish-cli.yml'))"` exits 0; `grep -c "UV_PUBLISH_TOKEN" .github/workflows/publish-sdks.yml .github/workflows/publish-cli.yml` returns 0; `grep -c "trusted-publishing automatic" .github/workflows/publish-sdks.yml .github/workflows/publish-cli.yml` returns 2; `grep -c "force_publish" .github/workflows/publish-sdks.yml .github/workflows/publish-cli.yml` returns ≥2 | ✅ existing infra | ⬜ pending |
| 228-01-T2 | 01 | 1 | PUBLISH-04 (verify infra) | T-228-04 | verify-published.yml created with two Docker jobs (python:3.13-slim + node:22-slim); checks `createGeolensClient` (NOT `GeolensClient`) for TS runtime export | yaml-lint + grep | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/verify-published.yml'))"` exits 0; `grep -c "python:3.13-slim" .github/workflows/verify-published.yml` returns ≥1; `grep -c "node:22-slim" .github/workflows/verify-published.yml` returns ≥1; `grep -c "createGeolensClient" .github/workflows/verify-published.yml` returns ≥1; `grep -c "typeof m.GeolensClient" .github/workflows/verify-published.yml` returns 0 (no false-positive type-only check) | ❌ W0 (new file) | ⬜ pending |
| 228-02-T1 | 02 | 2 | PUBLISH-01 (credential setup) | T-228-01, T-228-02 | Combined out-of-band runbook: claim @geolens npm org → generate granular NPM_TOKEN with Bypass 2FA → `gh secret set NPM_TOKEN` → configure 2 PyPI pending publishers | shell-assert (post-checkpoint) | `gh secret list --repo geolens-io/geolens \| awk '{print $1}'` includes `NPM_TOKEN` AND excludes `PYPI_TOKEN`; `curl -fs https://registry.npmjs.org/-/org/geolens` returns 200 OK with org metadata (not `ResourceNotFound`); manual screenshot of PyPI publishing settings page documenting both pending publishers in 228-VERIFICATION.md | ✅ gh + curl | ⬜ pending (autonomous: false) |
| 228-03-T1 | 03 | 3 | PUBLISH-02 | T-228-02, T-228-03 | publish-sdks.yml E2E run completed (dry_run=true → dry_run=false sequence); geolens-sdk@1.0.0 on PyPI; @geolens/sdk@1.0.0 on npm | network-assert | `pip index versions geolens-sdk \| grep -c "1.0.0"` returns ≥1; `npm view @geolens/sdk version` outputs exactly `1.0.0`; `gh run list --workflow=publish-sdks.yml --repo geolens-io/geolens --limit 2 --json conclusion --jq '.[].conclusion'` returns `success` for both runs | ✅ pip + npm + gh CLIs | ⬜ pending (autonomous: false) |
| 228-03-T2 | 03 | 3 | PUBLISH-03 | T-228-02, T-228-03 | publish-cli.yml E2E run completed (dry_run=true → dry_run=false sequence); geolens@1.0.0 on PyPI | network-assert | `pip index versions geolens \| grep -c "1.0.0"` returns ≥1; `gh run list --workflow=publish-cli.yml --repo geolens-io/geolens --limit 2 --json conclusion --jq '.[].conclusion'` returns `success` for both runs | ✅ pip + gh CLIs | ⬜ pending (autonomous: false) |
| 228-04-T1 | 04 | 4 | PUBLISH-04 | T-228-04 | verify-published.yml workflow_dispatch run completes; both verify-python and verify-typescript jobs exit 0 against `latest` versions | network + docker assert | `gh workflow run verify-published.yml --repo geolens-io/geolens` then `gh run list --workflow=verify-published.yml --limit 1 --json conclusion --jq '.[0].conclusion'` returns `success` | ✅ gh CLI + Docker (in CI) | ⬜ pending |
| 228-04-T2 | 04 | 4 | PUBLISH-01 (docs), PUBLISH-04 (docs) | — | docs/sdks.md + docs/cli.md Publishing sections rewritten: Trusted Publishing replaces PYPI_TOKEN setup; npm Granular Token (Bypass 2FA) replaces deprecated Automation Token reference | grep + manual review | `grep -c "PYPI_TOKEN" docs/sdks.md docs/cli.md` returns 0 (or only inside historical/changelog context); `grep -c "Trusted Publishing" docs/sdks.md docs/cli.md` returns ≥2; `grep -c "Granular" docs/sdks.md` returns ≥1; `grep -c "Bypass 2FA\\|Bypass two-factor" docs/sdks.md` returns ≥1 | ✅ grep | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Wave 0 note:** `verify-published.yml` is a NEW workflow file created inline in Plan 01 / Task 02 (Wave 1). Plan 04 / Task 1 (Wave 4) is the FIRST consumer. Sampling continuity holds: every wave between creation and consumption has independent automated verifies, and the file's correctness is validated by `python3 -c "import yaml; yaml.safe_load(...)"` in Plan 01 Task 02 before any wave depends on it.

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

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (verified — 7/7 tasks: 4 auto + 3 checkpoint with `<how-to-verify>`)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (Waves 1, 2, 3, 4 each have automated assertions)
- [x] Wave 0 covers all MISSING references (`verify-published.yml` created in 01-T2 before its first consumer in 04-T1)
- [x] No watch-mode flags (irrelevant — CI workflow phase)
- [x] Feedback latency < 5 min per workflow run (publish ~3min, verify ~2min)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-02 — per-task map populated post-planning; all 7 task acceptance criteria mapped to verifiable commands.
