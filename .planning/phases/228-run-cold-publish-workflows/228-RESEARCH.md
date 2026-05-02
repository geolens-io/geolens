# Phase 228: run-cold-publish-workflows - Research

**Researched:** 2026-05-02
**Domain:** PyPI Trusted Publishing (OIDC), npm granular tokens, GitHub Actions publish workflows, clean-machine install verification
**Confidence:** HIGH (all critical claims verified via live tool calls or official docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01** — PyPI Trusted Publishing (OIDC) for both `geolens-sdk` and `geolens`. No `PYPI_TOKEN` secret.
- **D-02** — Classic npm token for npm publish. NOTE: see critical finding below — "Automation" token type no longer exists; use granular token with Bypass 2FA + Read/Write.
- **D-03** — Replace `UV_PUBLISH_TOKEN` env block with `uv publish --trusted-publishing automatic`. Fallback: `pypa/gh-action-pypi-publish@release/v1`.
- **D-04** — Dry-run-first cadence: `dry_run=true` before `dry_run=false` for each workflow.
- **D-05** — Pre-flight name-availability hard gate before first publish.
- **D-06** — Versions stay at `1.0.0`.
- **D-07** — Separate `.github/workflows/verify-published.yml` with two Docker jobs.
- **D-08** — `python:3.13-slim` + `node:22-slim` for clean-machine verification.
- **D-09** — Update `docs/sdks.md` and `docs/cli.md` to reflect new auth patterns.
- **D-10** — Acknowledge billing risk; no mitigations needed.

### Claude's Discretion
- Phrasing of the "Trusted Publishing setup" subsection in `docs/sdks.md`.
- Whether to use `uv publish --trusted-publishing automatic` or `pypa/gh-action-pypi-publish@release/v1`.
- Whether pre-flight check (D-05) lives in `.github/scripts/preflight-publish.sh` or inline in each workflow.
- Whether `verify-published.yml` takes a `version` input.

### Deferred Ideas (OUT OF SCOPE)
- Release-tag-driven publishes
- npm OIDC trusted publishing
- SBOM / sigstore signing
- Multi-Python-version verification matrix
- Cross-platform CLI binaries (Homebrew, AUR, winget)
- Yank/deprecation policy
- Release notes automation
- Security advisory pipeline
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PUBLISH-01 | `PYPI_TOKEN`/`NPM_TOKEN` present OR Trusted Publishing migrated | D-01 (PyPI OIDC), D-02 (npm granular token). Both approaches verified via official docs. |
| PUBLISH-02 | `publish-sdks.yml` runs E2E, publishing `geolens-sdk` to PyPI and `@geolens/sdk` to npm | Workflow already wired. Changes: drop `UV_PUBLISH_TOKEN`, add `--trusted-publishing automatic`; npm uses `NODE_AUTH_TOKEN`. |
| PUBLISH-03 | `publish-cli.yml` runs E2E, publishing `geolens` CLI to PyPI | Same change as PUBLISH-02 Python side. `geolens` name is unclaimed on PyPI (verified). |
| PUBLISH-04 | README install instructions validated against published artifacts on a clean machine | `verify-published.yml` with Docker jobs. Both `python:3.13-slim` and `node:22-slim` confirmed available and ship pip/npm. |
</phase_requirements>

---

## Summary

Phase 228 converts two "wired but cold" GitHub Actions publish workflows into shipped, running CI/CD. The work splits into three categories: (1) out-of-band human runbook steps (PyPI pending publisher setup, npm token creation, `@geolens` org claim), (2) YAML changes to both publish workflows to migrate from `UV_PUBLISH_TOKEN` to OIDC, and (3) a new `verify-published.yml` workflow for clean-machine smoke tests.

All three PyPI package names (`geolens-sdk`, `geolens`) and the npm package (`@geolens/sdk`) are confirmed unclaimed on their respective registries as of 2026-05-02. The `@geolens` npm org does not exist yet — the maintainer must claim it at npmjs.com before first publish of `@geolens/sdk`. The `geolens` npm name is a non-issue (CLI is PyPI-only).

**Critical finding:** The npm "Automation" token type referenced in CONTEXT.md D-02 was removed from npm on December 9, 2025. The replacement is a **granular access token** with "Read and write" permissions and "Bypass 2FA" enabled. The token creation UI requires selecting the specific package or scope to grant access to, but since `@geolens/sdk` doesn't exist yet, the token must be scoped to the `@geolens` scope (not the individual package). Max token lifetime is 90 days — rotation is a maintenance obligation.

**Primary recommendation:** Proceed with the plan as designed. The YAML changes are minimal (one line per workflow). The main execution risk is the out-of-band human steps happening in the correct order before the first hot publish run.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PyPI publish (Python SDK, CLI) | CI/CD (GitHub Actions) | PyPI OIDC service | Publish is a CI concern; OIDC auth is delegated to GitHub's token service |
| npm publish (TypeScript SDK) | CI/CD (GitHub Actions) | npm registry | Token auth injected at publish step |
| Package name reservation | PyPI/npm registry (out-of-band) | — | Registry reserves names on first publish; no code change |
| Pending publisher registration | PyPI web UI (out-of-band) | — | Human action before OIDC can work |
| `@geolens` org claim | npm web UI (out-of-band) | — | Human action before first publish of `@geolens/sdk` |
| Clean-machine install verification | CI/CD (GitHub Actions Docker) | — | Isolated Docker jobs with no repo context |
| Documentation update | Source code (`docs/`) | — | Markdown edits only |

---

## Standard Stack

No new libraries introduced. This phase reuses what is already in both publish workflows.

### Existing Toolchain (reused verbatim)

| Tool/Action | Version | Purpose |
|-------------|---------|---------|
| `astral-sh/setup-uv@v6` | v6 | uv installation (uv 0.10.2) |
| `actions/setup-python@v5` | v5 | Python 3.13 environment |
| `actions/setup-node@v6` | v6 | Node 22 + npm registry config |
| `actions/checkout@v4` | v4 | Source checkout |
| `uv build` | (via uv 0.10.2) | Build wheel + sdist |
| `uv publish --trusted-publishing automatic` | uv 0.5+ | Publish to PyPI via OIDC |
| `npm publish --access public` | (via Node 22) | Publish to npm via `NODE_AUTH_TOKEN` |

### New Workflow

| File | Purpose |
|------|---------|
| `.github/workflows/verify-published.yml` | Clean-machine Docker smoke tests |

**No `npm install` step** in `verify-published.yml` — use `pip install` / `npm install` directly against the published registry artifacts, not from the repo.

---

## Architecture Patterns

### System Architecture Diagram

```
Maintainer keyboard
       │
       ├─ [1] PyPI web UI → Add pending publisher
       │        └── geolens-sdk → publish-sdks.yml
       │        └── geolens → publish-cli.yml
       │
       ├─ [2] npm web UI → Create @geolens org + granular token → gh secret set NPM_TOKEN
       │
       ├─ [3] gh Actions → publish-sdks.yml (workflow_dispatch, dry_run=true)
       │        └── Build artifacts only, exit 0 → confirm
       │
       ├─ [4] gh Actions → publish-sdks.yml (workflow_dispatch, dry_run=false)
       │        ├── python job: uv publish --trusted-publishing automatic → PyPI
       │        └── typescript job: npm publish --access public → npm (NODE_AUTH_TOKEN)
       │
       ├─ [5] gh Actions → publish-cli.yml (workflow_dispatch, dry_run=true → dry_run=false)
       │        └── uv publish --trusted-publishing automatic → PyPI (geolens)
       │
       └─ [6] gh Actions → verify-published.yml (workflow_dispatch)
                ├── verify-python job: docker run python:3.13-slim pip install geolens-sdk geolens
                └── verify-typescript job: docker run node:22-slim npm install @geolens/sdk
```

### Pre-flight Name-Availability Script

Run once locally before triggering the first `dry_run=false` run. Can be committed as `.github/scripts/preflight-publish.sh` or run ad hoc.

```bash
#!/usr/bin/env bash
set -e

check_pypi() {
  local pkg="$1"
  if pip3 index versions "$pkg" 2>&1 | grep -q "No matching distribution"; then
    echo "PyPI $pkg: UNCLAIMED — safe to publish 1.0.0"
  else
    echo "PyPI $pkg: TAKEN — investigate before publishing" >&2
    exit 1
  fi
}

check_npm() {
  local pkg="$1"
  if npm view "$pkg" version 2>/dev/null; then
    echo "npm $pkg: TAKEN — investigate" >&2
    exit 1
  else
    echo "npm $pkg: UNCLAIMED — safe to publish 1.0.0"
  fi
}

check_pypi geolens-sdk
check_pypi geolens
check_npm @geolens/sdk
```

**Verified exit codes (2026-05-02, local machine):**
- `pip3 index versions <missing>` → exits 1, stderr: `ERROR: No matching distribution found for <pkg>`
- `pip3 index versions <existing>` → exits 0, stdout includes version list
- `npm view <missing-scoped> version` → exits 1, stderr: `npm error 404 Not Found`
- `npm view <existing> version` → exits 0, stdout: version string

**Grep target for pip3:** `"No matching distribution"` — works in pip 24.x and pip 26.x (confirmed locally).

**npm:** Do NOT grep stderr for "404" — the exit code (1 vs 0) is the reliable signal.

### `uv publish --trusted-publishing automatic` — Exact Invocation

Verified via `uv publish --help` (uv 0.10.2 installed locally):

```yaml
- name: Publish to PyPI
  if: ${{ !inputs.dry_run }}
  working-directory: sdks/python   # or: cli
  run: uv publish --trusted-publishing automatic
```

**What `--trusted-publishing automatic` does:** Auto-detects whether OIDC credentials are available via `ACTIONS_ID_TOKEN_REQUEST_TOKEN` and `ACTIONS_ID_TOKEN_REQUEST_URL` environment variables. These are injected automatically by GitHub Actions when `permissions: id-token: write` is set on the job or workflow — no manual env injection required. In non-Actions environments (local dev), `automatic` falls through to credential-based auth. [VERIFIED: `uv publish --help` output]

**No `UV_PUBLISH_TOKEN` env var needed.** Remove the entire `env:` block from the publish steps.

### `pypa/gh-action-pypi-publish@release/v1` Fallback (D-03 alternate path)

If `uv publish --trusted-publishing automatic` proves unreliable, use:

```yaml
- name: Publish to PyPI
  if: ${{ !inputs.dry_run }}
  uses: pypa/gh-action-pypi-publish@release/v1
  with:
    packages-dir: sdks/python/dist/   # or: cli/dist/
    attestations: true
```

**No `password:` input.** The action reads `ACTIONS_ID_TOKEN_REQUEST_TOKEN` automatically when `permissions: id-token: write` is set. `attestations: true` is the default and produces Sigstore provenance records on PyPI. [VERIFIED: pypa/gh-action-pypi-publish README]

**Note:** The `pypa` action approach requires a separate build step before calling the action (run `uv build` first, then call the action pointing at `dist/`). The existing workflow already has the build step, so this is compatible.

### `verify-published.yml` Structure

```yaml
name: Verify Published Packages

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Package version to verify (default: latest)'
        required: false
        default: 'latest'
  push:
    tags:
      - 'release/*'

permissions:
  contents: read

jobs:
  verify-python:
    runs-on: ubuntu-latest
    steps:
      - name: Verify geolens-sdk and geolens on python:3.13-slim
        run: |
          docker run --rm python:3.13-slim sh -c "
            pip install --no-cache-dir geolens-sdk geolens &&
            geolens --version &&
            python -c 'from geolens_sdk import GeolensClient; print(GeolensClient)'
          "

  verify-typescript:
    runs-on: ubuntu-latest
    steps:
      - name: Verify @geolens/sdk on node:22-slim
        run: |
          docker run --rm node:22-slim sh -c "
            npm install --no-save @geolens/sdk &&
            node -e 'import(\"@geolens/sdk\").then(m => console.log(typeof m.GeolensClient))'
          "
```

**Confirmed:** `python:3.13-slim` ships pip; `node:22-slim` ships npm (v10.9.7 with Node 22.22.2). Both Docker images pulled and verified locally. [VERIFIED: local `docker run` calls]

**`--no-cache-dir`** is best practice for Docker (avoids filling the layer with pip cache). **`--no-save`** for npm prevents writing `package.json` to the Docker layer (irrelevant but clean).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OIDC token exchange with PyPI | Custom HTTP auth flow | `uv publish --trusted-publishing automatic` OR `pypa/gh-action-pypi-publish@release/v1` | GitHub injects `ACTIONS_ID_TOKEN_REQUEST_*` automatically; hand-rolling misses token refresh logic |
| npm scoped package access check | Custom registry API call | `npm view @pkg version` (exit code) | Exit code is the signal; stderr format varies |
| PyPI package existence check | `curl https://pypi.org/pypi/pkg/json` | `pip3 index versions pkg` (exit code + stderr) | pip3 handles all edge cases (proxies, auth, encoding); grep `"No matching distribution"` |
| Docker in-workflow install | `apt-get install python3` in runner | `docker run --rm python:3.13-slim` | Complete isolation, matches real user environment, no runner pollution |

---

## PyPI Trusted Publishing — Runbook Details

### Order of Operations (Critical)

PyPI "pending publishers" work BEFORE the package exists on PyPI. The pending publisher is configured via the PyPI web UI at **<https://pypi.org/manage/account/publishing/>** under "Add a new pending publisher." When the GitHub Actions OIDC workflow runs for the first time, PyPI converts the pending publisher to a normal publisher and creates the project simultaneously. [VERIFIED: docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/]

**DO NOT** publish a `0.0.1` placeholder first. The pending publisher approach handles the cold-start problem directly.

### Exact Form Fields — `geolens-sdk` (publish-sdks.yml)

Navigate to: `https://pypi.org/manage/account/publishing/` → scroll to "Add a new pending publisher" → select "GitHub Actions"

| Field | Value |
|-------|-------|
| PyPI project name | `geolens-sdk` |
| GitHub repository owner | `geolens-io` |
| GitHub repository name | `geolens` |
| Workflow filename | `publish-sdks.yml` |
| Environment name | *(leave blank — repo-level OIDC, no GitHub Environment needed)* |

### Exact Form Fields — `geolens` (publish-cli.yml)

| Field | Value |
|-------|-------|
| PyPI project name | `geolens` |
| GitHub repository owner | `geolens-io` |
| GitHub repository name | `geolens` |
| Workflow filename | `publish-cli.yml` |
| Environment name | *(leave blank)* |

**Caveat on Environment Name:** PyPI docs strongly recommend configuring a GitHub Environment with required reviewers for additional security. This phase leaves the environment blank (simpler, repo-level OIDC), consistent with the workflows already having no `environment:` key. This is acceptable for an initial "ship it" phase. [ASSUMED — no org-specific policy found in CLAUDE.md or project memory]

---

## npm Token Runbook (Post-December-2025 Reality)

**IMPORTANT:** The npm "Automation" token type was permanently removed on **December 9, 2025**. CONTEXT.md D-02 describes it by the old name. The replacement is a **granular access token** with specific settings. [VERIFIED: github.blog/changelog/2025-11-05]

### Step 1: Claim the `@geolens` npm organization

The `@geolens` scope does not exist on npm (confirmed via `https://registry.npmjs.org/-/org/geolens` → `{"code":"ResourceNotFound"}`). The maintainer must create it before the first publish.

1. Go to <https://www.npmjs.com/org/create>
2. Create organization: `geolens`
3. This claims the `@geolens` scope for the `geolens-io` account

Without this step, `npm publish @geolens/sdk` fails with a scope-not-found error.

### Step 2: Generate a Granular Access Token

Navigate to: <https://www.npmjs.com/settings/~/tokens> → "Generate New Token"

| Setting | Value |
|---------|-------|
| Token name | `geolens-sdk-ci-publish` |
| Permissions | **Read and write** |
| Bypass two-factor authentication | **Enabled** (checkbox — REQUIRED for non-interactive CI) |
| Packages and scopes | **@geolens** scope (the org scope, not a specific package — because `@geolens/sdk` doesn't exist yet at token creation time) |
| Expiration | Maximum (90 days from creation date) |

**Token scoping caveat:** When `@geolens/sdk` doesn't yet exist on npm, the token form's package picker won't show it. Granting the entire `@geolens` scope access is the correct workaround. After first publish, the token can be narrowed to the specific package on next rotation. [CITED: apostrophecms.com/blog/npm-cheat-sheet, npm/cli GitHub issue #8869]

**Token lifetime:** Max 90 days. Needs rotation calendar reminder. Document in `docs/sdks.md`.

### Step 3: Add NPM_TOKEN to GitHub repo secrets

```bash
# Via CLI (requires gh auth with repo admin permissions):
gh secret set NPM_TOKEN --body "$NPM_TOKEN" --repo geolens-io/geolens

# Or via GitHub web UI:
# Repository Settings → Secrets and variables → Actions → New repository secret
# Name: NPM_TOKEN, Value: <token>
```

**Verify:**
```bash
gh secret list --repo geolens-io/geolens
# Expected: NPM_TOKEN  <date>  and GEOLENS_ENTERPRISE_TOKEN  <date>
# NOT expected: PYPI_TOKEN (confirms Trusted Publishing path is active)
```

---

## Common Pitfalls

### Pitfall 1: Wrong order — workflow runs before pending publisher is configured
**What goes wrong:** `uv publish --trusted-publishing automatic` fails with `403 Forbidden` from PyPI ("invalid or missing OIDC token"). The OIDC handshake only works after the pending publisher entry is saved in PyPI's web UI.
**Why it happens:** The workflow has `permissions: id-token: write` which gives it a token, but PyPI only accepts that token if it trusts the workflow.
**How to avoid:** Configure BOTH pending publishers (geolens-sdk + geolens) in PyPI web UI BEFORE triggering the first `dry_run=false` run.
**Warning signs:** Workflow exits 1 at the publish step with HTTP 403; dry_run=true runs fine (build only).

### Pitfall 2: `@geolens` npm org not claimed before first publish
**What goes wrong:** `npm publish` fails with a scope-not-found or 402 error on the TypeScript publish step.
**Why it happens:** npm requires the scope's org to exist before any package under that scope can be published, even with `--access public` and `publishConfig.access`.
**How to avoid:** Create the `@geolens` org at <https://www.npmjs.com/org/create> as step zero, before generating the token and before any publish attempt.
**Warning signs:** `npm error 403` or `npm error 402 Payment Required` on publish step; `npm view @geolens/sdk` returns 404 even after publish.

### Pitfall 3: npm granular token scoped to package that doesn't exist yet
**What goes wrong:** The npm token form's "Packages and scopes" picker has no results when searching for `@geolens/sdk` because it hasn't been published yet. If the maintainer creates a token with no package scope at all, the publish will fail.
**Why it happens:** npm granular tokens must explicitly enumerate what they can access.
**How to avoid:** Scope the token to the `@geolens` scope (the entire org scope), not to the individual package. The dropdown allows selecting an org scope. After first publish, re-create the token scoped to `@geolens/sdk` specifically on next rotation.
**Warning signs:** `npm error 403 Forbidden` on publish despite valid token.

### Pitfall 4: `pip3 index versions` grep pattern mismatch
**What goes wrong:** The pre-flight script reports "TAKEN" for an unclaimed package (false positive), blocking the publish.
**Why it happens:** Different pip versions format the error differently.
**How to avoid:** Use `"No matching distribution"` as the grep target — confirmed stable across pip 24.x and pip 26.x (tested locally). Do NOT grep for `"404"`.
**Warning signs:** Pre-flight exits 1 even when packages are unclaimed.

### Pitfall 5: npm version input gives wrong ESM output
**What goes wrong:** `node -e 'import("@geolens/sdk").then(...)'` fails in the Docker verify job because ESM dynamic import in a shell one-liner needs proper quoting.
**Why it happens:** Shell quoting and escape handling between `sh -c "..."` and nested quotes.
**How to avoid:** Use the exact quoting pattern: `sh -c "node -e 'import(\"@geolens/sdk\").then(m => console.log(typeof m.GeolensClient))'"`. The inner double-quotes around the module name must be backslash-escaped.
**Warning signs:** `verify-typescript` job fails with SyntaxError at the node -e step.

### Pitfall 6: `uv publish` uploads sdist and wheel — avoid duplicate version error
**What goes wrong:** Re-running `uv publish` after a partial upload fails with "File already exists" from PyPI.
**Why it happens:** `uv publish` retries on failure, but PyPI rejects re-uploads of identical filenames even in the same publish run.
**How to avoid:** The first publish is unlikely to hit this; re-publish attempts after a partial failure need `--no-check-url` or manual dist/ cleanup. Document in VERIFICATION.md if it occurs.
**Warning signs:** `HTTP 400: File already exists` from PyPI publish step.

---

## Runtime State Inventory

Not applicable. This phase is greenfield from the publish/verification standpoint — no existing published versions to migrate or rename.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js / npm | verify-typescript job, npm publish | ✓ | Node v25.6.1, npm 11.9.0 (local dev) | — (CI uses setup-node@v6) |
| Docker | verify-published.yml local test | ✓ | Docker Server 29.4.0 | — (required for verify workflow) |
| `python:3.13-slim` Docker image | verify-python job | ✓ | Ships pip 26.1 | — |
| `node:22-slim` Docker image | verify-typescript job | ✓ | Ships npm 10.9.7 | — |
| `gh` CLI | Secret management | ✓ | 2.86.0 | GitHub web UI |
| `pip3` / `uv` | Pre-flight check | ✓ (pip3 confirmed) | pip3 24.x+ | `curl` + jq against PyPI JSON API |
| PyPI web UI | D-01 pending publisher setup | ✓ (web, out-of-band) | — | None — manual step required |
| npm web UI | D-02 org claim + token | ✓ (web, out-of-band) | — | None — manual step required |

**Missing with no fallback:**
- `@geolens` npm org does not exist yet — must be claimed by maintainer before publish.
- PyPI pending publishers for `geolens-sdk` and `geolens` must be configured before OIDC publish.

---

## Validation Architecture

`workflow.nyquist_validation` is absent from `.planning/config.json` — treat as enabled.

This phase has no unit test surface. Validation is entirely workflow-execution-based. The test map uses workflow run exit codes as the automation signal.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | GitHub Actions (workflow runs, not pytest/vitest) |
| Config file | `.github/workflows/publish-sdks.yml`, `publish-cli.yml`, `verify-published.yml` |
| Quick run command | `gh run list --workflow=verify-published.yml --limit=5` |
| Full suite command | Trigger `verify-published.yml` via `gh workflow run verify-published.yml` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PUBLISH-01 | `NPM_TOKEN` present, no `PYPI_TOKEN`, PyPI publishers configured | smoke | `gh secret list --repo geolens-io/geolens` | ✅ (gh CLI) |
| PUBLISH-02 | `publish-sdks.yml` exits 0 (both Python + TypeScript targets) | e2e | `gh run list --workflow=publish-sdks.yml --limit=3` | ✅ after Wave 0 |
| PUBLISH-03 | `publish-cli.yml` exits 0 | e2e | `gh run list --workflow=publish-cli.yml --limit=3` | ✅ after Wave 0 |
| PUBLISH-04 | `verify-published.yml` exits 0, both Docker jobs green | smoke/e2e | `gh workflow run verify-published.yml && gh run watch` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `gh secret list --repo geolens-io/geolens` to confirm secret inventory
- **Per wave merge:** Trigger `dry_run=true` run on affected workflow and confirm exit 0
- **Phase gate:** `verify-published.yml` green before marking PUBLISH-04 satisfied

### Wave 0 Gaps

- [ ] `.github/workflows/verify-published.yml` — covers PUBLISH-04 (does not exist yet)
- [ ] PyPI pending publishers for `geolens-sdk` and `geolens` — out-of-band human step (PUBLISH-01 prereq)
- [ ] `@geolens` npm org claim — out-of-band human step (PUBLISH-02 prereq)
- [ ] `NPM_TOKEN` repo secret — out-of-band human step (PUBLISH-01 prereq)

---

## Out-of-Band Checkpoints

The plan MUST include four `autonomous: false` tasks. These are human runbook items with no automation path.

### Checkpoint A: PyPI Pending Publisher — `geolens-sdk`
**What the maintainer does:**
1. Log in to <https://pypi.org>
2. Navigate to Account Settings → Publishing → "Add a new pending publisher"
3. Select GitHub Actions
4. Fill fields: PyPI project name=`geolens-sdk`, Owner=`geolens-io`, Repo=`geolens`, Workflow=`publish-sdks.yml`, Environment=*(blank)*
5. Click Add

**Verification:** The pending publisher appears in the list at <https://pypi.org/manage/account/publishing/>. Screenshot or text copy to VERIFICATION.md.

### Checkpoint B: PyPI Pending Publisher — `geolens`
**Same steps as A**, with: PyPI project name=`geolens`, Workflow=`publish-cli.yml`

**Verification:** Same — appears in pending publisher list.

### Checkpoint C: `@geolens` npm Org Claim + Token + Secret
**What the maintainer does:**
1. Go to <https://www.npmjs.com/org/create>, create org `geolens`
2. Go to <https://www.npmjs.com/settings/~/tokens> → "Generate New Token"
3. Settings: Name=`geolens-sdk-ci-publish`, Permissions=Read and write, Bypass 2FA=enabled, Packages=select `@geolens` scope, Expiration=90 days
4. Copy token
5. Run: `gh secret set NPM_TOKEN --body "$NPM_TOKEN" --repo geolens-io/geolens`
6. Set a calendar reminder for 90 days out

**Verification:** `gh secret list --repo geolens-io/geolens | grep NPM_TOKEN` shows one row with current date.

### Checkpoint D: Pre-flight Name-Availability Check
**What the maintainer does:** Run the pre-flight script (inline or from `.github/scripts/preflight-publish.sh`) locally and confirm all four checks pass (all packages unclaimed).

**Expected output (2026-05-02):**
```
PyPI geolens-sdk: UNCLAIMED — safe to publish 1.0.0
PyPI geolens: UNCLAIMED — safe to publish 1.0.0
npm @geolens/sdk: UNCLAIMED — safe to publish 1.0.0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `PYPI_TOKEN` long-lived secret | PyPI Trusted Publishing (OIDC) | 2023 (PyPI), 2024 recommended | No token rotation burden; provenance attestations auto-emitted |
| npm "Automation" token (classic) | npm granular token with Bypass 2FA + Read/Write | Dec 9, 2025 (classic removed) | 90-day max lifetime; must rotate; token must be scoped to `@geolens` org scope |
| `uv publish` with `UV_PUBLISH_TOKEN` env | `uv publish --trusted-publishing automatic` | uv 0.5+ | One-flag change; no credential in env |

**Deprecated:**
- npm classic tokens (including "Automation" type): permanently removed December 9, 2025. Any documentation referencing them is stale.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Leaving PyPI Environment name blank is acceptable for this org/project (no org policy requiring GitHub Environment gating) | PyPI Pending Publisher Runbook | If the org requires an Environment, the OIDC handshake will fail with 403 until an `environment:` key is added to the workflow jobs and the pending publisher is updated to match |
| A2 | The `@geolens/sdk` ESM dynamic import works in a `sh -c` one-liner with backslash-escaped inner quotes on `node:22-slim` | `verify-published.yml` Structure | If quoting fails, the verify job exits with SyntaxError; fix by writing a temp JS file instead |

---

## Open Questions

1. **npm token — org scope vs `@geolens/sdk` scope**
   - What we know: granular tokens can be scoped to `@geolens` (org scope) which covers all packages under the org, OR to a specific package. The package doesn't exist at token creation time, so only the org scope is available.
   - What's unclear: does scoping to the org scope incur any additional risk (could the token publish any `@geolens/*` package, not just `@geolens/sdk`)?
   - Recommendation: Accept org-scope token for first publish. Document in `docs/sdks.md` that the token should be narrowed to `@geolens/sdk` on next 90-day rotation once the package exists.

2. **`npm view @geolens/sdk` after first publish — does it return exit 0?**
   - What we know: before publish, it exits 1. After a successful first publish, it should exit 0 with the version string.
   - What's unclear: the pre-flight hard gate (D-05) will fail on subsequent publishes if left as-is. The plan should either gate on "version not found OR version matches expected" or convert to informational after first publish.
   - Recommendation: Keep the pre-flight check but update the logic after first publish to allow known versions (add a `--skip-preflight` or `force=true` workflow input).

---

## Security Domain

`security_enforcement` is not set in `.planning/config.json`. Treating as enabled.

This phase involves credential surfaces. The analysis is brief because it's a CI/CD-only phase with no application code changes.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (CI auth) | PyPI OIDC (no long-lived credential); npm granular token (90-day rotation) |
| V3 Session Management | no | — |
| V4 Access Control | yes | `id-token: write` scoped to workflows only; npm token scoped to `@geolens` only |
| V5 Input Validation | no | — |
| V6 Cryptography | no | — |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Leaked `NPM_TOKEN` secret | Tampering/Elevation | GitHub encrypted secrets; 90-day rotation; no `PYPI_TOKEN` risk (OIDC only) |
| Unauthorized publish via OIDC misconfiguration | Tampering | PyPI pending publisher scoped to specific workflow filenames |
| Package name squatting before first publish | Spoofing | Pre-flight check (D-05); both names confirmed unclaimed 2026-05-02 |
| npm token scoped too broadly | Elevation | Scope to `@geolens` org scope for now; narrow to `@geolens/sdk` on next rotation |

---

## Sources

### Primary (HIGH confidence)
- [VERIFIED: `uv publish --help` output] — `--trusted-publishing automatic` flag confirmed, possible values: `automatic`, `always`, `never`
- [VERIFIED: local `pip3 index versions geolens-sdk/geolens`] — both return exit 1, stderr "No matching distribution found" — packages unclaimed
- [VERIFIED: local `npm view @geolens/sdk version`] — exits 1, `npm error 404` — package unclaimed
- [VERIFIED: `gh secret list --repo geolens-io/geolens`] — only `GEOLENS_ENTERPRISE_TOKEN` present; both `PYPI_TOKEN` and `NPM_TOKEN` absent
- [VERIFIED: `curl https://registry.npmjs.org/-/org/geolens`] — `{"code":"ResourceNotFound"}` — org does not exist
- [VERIFIED: `docker run --rm python:3.13-slim` / `node:22-slim`] — both images pull successfully; node:22-slim ships npm 10.9.7
- [CITED: docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/] — pending publishers work before package exists; converted on first use
- [CITED: pypa/gh-action-pypi-publish README] — OIDC mode requires only `id-token: write`; no `password:` input; `attestations: true` default
- [CITED: github.blog/changelog/2025-11-05-npm-security-update] — npm classic tokens (including Automation type) removed December 9, 2025
- [CITED: github.com/orgs/community/discussions/179562] — granular tokens with Bypass 2FA + Read/Write replace classic Automation tokens

### Secondary (MEDIUM confidence)
- [CITED: apostrophecms.com/blog/npm-cheat-sheet] — scope token to org scope (not individual package) when package doesn't exist yet; max 90-day rotation
- [CITED: docs.npmjs.com/creating-and-viewing-access-tokens] — Bypass 2FA required for CI; checked "Read and write" + "Bypass 2FA" + scope selection

### Tertiary (LOW confidence)
- [ASSUMED: A1, A2] — see Assumptions Log

---

## Metadata

**Confidence breakdown:**
- PyPI Trusted Publishing mechanics: HIGH — verified via official docs and live tool output
- npm granular token mechanics: HIGH — verified via official changelog; flagged D-02 naming discrepancy (classic Automation type gone)
- `uv publish --trusted-publishing automatic`: HIGH — verified via `uv publish --help`
- Pre-flight exit codes and grep targets: HIGH — verified locally
- Docker image capabilities: HIGH — images pulled and commands run locally
- npm org claim prerequisite: HIGH — confirmed org does not exist via registry API

**Research date:** 2026-05-02
**Valid until:** 2026-08-01 (npm token policy could change; PyPI Trusted Publishing is stable)
