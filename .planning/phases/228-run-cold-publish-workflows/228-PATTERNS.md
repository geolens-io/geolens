# Phase 228: run-cold-publish-workflows - Pattern Map

**Mapped:** 2026-05-02
**Files analyzed:** 5 (3 workflow YAML, 2 docs Markdown; VERIFICATION.md is verifier output)
**Analogs found:** 5 / 5 in-repo, with 3 distinct external patterns explicitly called out as "no in-repo analog"

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `.github/workflows/publish-sdks.yml` (modify) | CI workflow (publish) | event-driven (workflow_dispatch) | self (`:55-60` Python step is in-place edit; `:62-95` TypeScript half is unchanged reference) | exact (in-place refactor) |
| `.github/workflows/publish-cli.yml` (modify) | CI workflow (publish) | event-driven (workflow_dispatch) | self (`:44-49` is in-place edit); structural twin of `publish-sdks.yml` Python job | exact (in-place refactor) |
| `.github/workflows/verify-published.yml` (NEW) | CI workflow (verify) | event-driven (workflow_dispatch + push tag) | `publish-sdks.yml` (workflow shell, inputs, jobs split) + `ci.yml:310-327` (multi-step inline shell) | role-match |
| `docs/sdks.md` (modify lines ~180-223) | docs (runbook) | static text | self (`:180-223` "Publishing" section); same shape exists in `docs/cli.md:181-192` | exact (in-place edit) |
| `docs/cli.md` (modify lines ~181-192) | docs (runbook) | static text | self + `docs/sdks.md` (cross-doc convention) | exact (in-place edit) |

---

## Pattern Assignments

### `.github/workflows/publish-sdks.yml` (CI workflow, in-place refactor)

**Analog:** Self — surgical edit to the Python publish step. Keep TypeScript half unchanged (per D-02, npm stays token-based).

**Existing structure to preserve verbatim** (`publish-sdks.yml:7-29`):
```yaml
name: Publish SDKs

on:
  workflow_dispatch:
    inputs:
      target:
        description: 'Which SDK to publish'
        required: true
        type: choice
        options: [python, typescript, both]
        default: 'both'
      dry_run:
        description: 'Build only, do not publish'
        required: false
        type: boolean
        default: false

permissions:
  contents: read
  id-token: write  # for PyPI Trusted Publishing (future migration)
```

**Lines to delete** (`publish-sdks.yml:55-60` — current Python publish step):
```yaml
      - name: Publish to PyPI
        if: ${{ !inputs.dry_run }}
        working-directory: sdks/python
        env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
        run: uv publish
```

**Lines to write in their place** (Trusted Publishing migration; D-01, D-03):
```yaml
      - name: Publish to PyPI
        if: ${{ !inputs.dry_run }}
        working-directory: sdks/python
        run: uv publish --trusted-publishing automatic
```
*(Drop entire `env:` block; `--trusted-publishing automatic` reads `ACTIONS_ID_TOKEN_REQUEST_TOKEN` from the env GitHub injects when `id-token: write` is set — no manual injection.)*

**Update the header comment** (`publish-sdks.yml:1-6` — outdated PYPI_TOKEN reference):
```yaml
# Manual-trigger publish workflow for the GeoLens SDKs.
# Phase 228 ships the cold-start credentials:
#   1. PyPI Trusted Publishing configured for `geolens-sdk` at https://pypi.org/manage/account/publishing/
#   2. npm granular token (Bypass 2FA + Read/Write) in repo secret NPM_TOKEN
#   3. The @geolens npm org claimed by the maintainer (one-time)
# See docs/sdks.md (§Publishing) for the full first-publish runbook.
```

**TypeScript half** (`publish-sdks.yml:62-95`) — DO NOT modify (npm OIDC still beta per RESEARCH §State of the Art).

**Pre-flight name-check insertion point** (D-05): add a new step at the top of `publish-python` (after `actions/checkout@v4` at `:37`) and at the top of `publish-typescript` (after `actions/setup-node@v6` at `:69-74`). Inline shell, no `.github/scripts/` file (per CONTEXT.md "Claude's Discretion"):
```yaml
      - name: Pre-flight name-availability gate
        if: ${{ !inputs.dry_run }}
        run: |
          set -e
          if pip3 index versions geolens-sdk 2>&1 | grep -q "No matching distribution"; then
            echo "PyPI geolens-sdk: unclaimed (safe)"
          else
            CURRENT=$(pip3 index versions geolens-sdk 2>&1 | head -1)
            echo "::warning::PyPI geolens-sdk already published: $CURRENT — proceeding (re-publish path)"
          fi
```
Same shape as `ci.yml:310-327` (multi-step inline `run: |` + bash `if`/`then`/`fi` + `exit 1` on failure).

---

### `.github/workflows/publish-cli.yml` (CI workflow, in-place refactor)

**Analog:** Self — same single-line surgical edit pattern as `publish-sdks.yml` Python half.

**Lines to delete** (`publish-cli.yml:44-49`):
```yaml
      - name: Publish to PyPI
        if: ${{ !inputs.dry_run }}
        working-directory: cli
        env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
        run: uv publish
```

**Lines to write in their place**:
```yaml
      - name: Publish to PyPI
        if: ${{ !inputs.dry_run }}
        working-directory: cli
        run: uv publish --trusted-publishing automatic
```

**Pre-flight insertion** — same shape as above, but check `geolens` (PyPI name for CLI). Insert after `actions/checkout@v4` at `:26`.

**Header comment update** (`publish-cli.yml:1-5`) — match the Trusted Publishing language used in `publish-sdks.yml` post-edit.

---

### `.github/workflows/verify-published.yml` (NEW)

**Analog (workflow shell):** `publish-sdks.yml` — copy `name:` / `on: workflow_dispatch:` / `permissions:` / two-job split pattern.

**Analog (input declaration):** `publish-sdks.yml:11-25` — `workflow_dispatch.inputs` with description + type + default.

**Analog (multi-step shell):** `ci.yml:310-327` — long inline `run: |` block with bash logic; same indentation and quote-escaping conventions.

**Imports/header** (copy verbatim shape from `publish-sdks.yml:7-29`, with the `target` choice replaced by an optional `version` string and `id-token` permission dropped — verify-only, no OIDC needed):
```yaml
# Clean-machine smoke verification of published GeoLens packages.
# Phase 228 ships this alongside the first hot publish.
# See docs/sdks.md (§Publishing) for context.
name: Verify Published Packages

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Package version to verify (default: latest)'
        required: false
        type: string
        default: 'latest'
  push:
    tags:
      - 'release/*'

permissions:
  contents: read
```

**Job pattern (copy from `publish-sdks.yml` jobs split):**
```yaml
jobs:
  verify-python:
    name: Verify Python packages on python:3.13-slim
    runs-on: ubuntu-latest
    steps:
      - name: pip install + smoke import
        run: |
          docker run --rm python:3.13-slim sh -c "
            pip install --no-cache-dir geolens-sdk geolens &&
            geolens --version &&
            python -c 'from geolens_sdk import GeolensClient; print(GeolensClient)'
          "

  verify-typescript:
    name: Verify TypeScript package on node:22-slim
    runs-on: ubuntu-latest
    steps:
      - name: npm install + smoke import
        run: |
          docker run --rm node:22-slim sh -c "
            npm install --no-save @geolens/sdk &&
            node -e 'import(\"@geolens/sdk\").then(m => console.log(typeof m.GeolensClient))'
          "
```

**Drop `actions/setup-node@v6` `registry-url` parameter** — that's a publish-side concern only (per CONTEXT.md hint). Actually drop `setup-node` entirely from `verify-typescript` — Docker brings its own node.

**External pattern (no in-repo analog):** `docker run --rm <image> sh -c "..."` — first time we use a fresh Docker image inside a CI job to smoke-check published artifacts. RESEARCH.md §`verify-published.yml` Structure verified `python:3.13-slim` ships pip 26.1 and `node:22-slim` ships npm 10.9.7 against live Docker pulls.

**Quote-escaping watch (RESEARCH Pitfall 5):** the inner double-quotes around `"@geolens/sdk"` inside `sh -c "node -e '...'"` MUST be backslash-escaped — the pattern above is correct. Don't reformat or YAML-pretty-print this section.

---

### `docs/sdks.md` (modify lines ~180-223 "Publishing" section)

**Analog:** Self (lines 180-223 already has the runbook; this is a token-strategy update).

**Block to replace** (`docs/sdks.md:182-223` — the "First-publish prerequisites" + "Publishing locally" subsections):
- Line 188: "Create a PyPI token scoped to the `geolens-sdk` project..." — replace with Trusted Publishing setup pointing at PyPI web UI.
- Line 190: "Create an npm token..." — keep but update token type to "granular access token with Read/Write + Bypass 2FA" (D-02; classic Automation tokens removed Dec 2025 per RESEARCH §State of the Art).
- Lines 211-214 ("Publishing locally" Python section with `UV_PUBLISH_TOKEN`) — replace with `uv publish --trusted-publishing automatic` (or note that local publish requires falling back to `UV_PUBLISH_USERNAME`/`UV_PUBLISH_PASSWORD` since OIDC needs Actions context).

**Add a new subsection** (placed between the "First-publish prerequisites" list and "Publishing via the GitHub Actions workflow" — D-09):
- Heading: `### PyPI Trusted Publishing setup`
- Body: web-UI walkthrough with the four field values from RESEARCH.md §"Exact Form Fields" (PyPI project name = `geolens-sdk`, Owner = `geolens-io`, Repository = `geolens`, Workflow = `publish-sdks.yml`, Environment = blank). Same field table for `geolens` (CLI) under `### PyPI Trusted Publishing setup` in `docs/cli.md`.

**Conventions to follow** (from `docs/sdks.md` existing style):
- Heading levels: `## Publishing` is H2; subsections use H3 (`### Publishing via the GitHub Actions workflow` at line 192).
- Code blocks: triple-backtick with language tag (`bash`, `yaml`).
- Cross-references: angle-bracket URLs `<https://pypi.org/...>` (matches `docs/sdks.md:186`, `:188`, `:190`).
- Inline code for filenames and tokens: backticks (`PYPI_TOKEN`, `@geolens/sdk`).

---

### `docs/cli.md` (modify lines ~181-192 "Publishing" section)

**Analog:** Self + `docs/sdks.md` "Publishing" section (same convention across both docs).

**Block to replace** (`docs/cli.md:181-192`):
- Line 186: "Create a PyPI API token..." — replace with Trusted Publishing reference + cross-link to `docs/sdks.md` PyPI Trusted Publishing setup subsection.
- Line 187: "Add the token as repo secret `PYPI_TOKEN`" — delete; no `PYPI_TOKEN` exists or is needed.
- Line 192 ("After the first publish, future migration to PyPI Trusted Publishing is wired into ...") — replace with "Trusted Publishing is active as of Phase 228 (2026-05); the `id-token: write` permission on `publish-cli.yml:18` performs the OIDC handshake automatically."

**No npm content in `docs/cli.md`** — CLI is PyPI-only.

---

## Shared Patterns

### Workflow `permissions: id-token: write` (DO NOT TOUCH)
**Source:** `publish-sdks.yml:27-29`, `publish-cli.yml:17-19`
**Apply to:** Both publish workflows (already declared)
**Note:** Phase 228 explicitly does NOT modify this block — Trusted Publishing migration is "drop the env block, keep the permission." `verify-published.yml` declares only `contents: read` (no OIDC needed for verify).

### Workflow `working-directory:` per-step pattern
**Source:** `publish-sdks.yml:48`, `:52`, `:57`, `publish-cli.yml:37`, `:41`, `:46`
**Apply to:** All edited publish steps; preserve the working-directory line when modifying the run command.

### Multi-step inline bash (`run: |` with `if`/`then`/`fi` + `exit 1`)
**Source:** `ci.yml:310-327` (Set up database extensions); `ci.yml:342-356` (SAML fixture guard, Phase 227 precedent)
**Apply to:** Pre-flight name-availability gate (D-05) in both `publish-sdks.yml` and `publish-cli.yml`.

### `if: ${{ !inputs.dry_run }}` gate
**Source:** `publish-sdks.yml:56`, `:89`, `publish-cli.yml:45`
**Apply to:** Both the existing publish steps (preserve gate after refactor) AND the new pre-flight gate (per the pattern excerpt above — only run pre-flight when actually publishing).

### Header comment block style
**Source:** `publish-sdks.yml:1-6`, `publish-cli.yml:1-5`
**Apply to:** Updated header comments (post-Trusted-Publishing migration) and new `verify-published.yml` header.

---

## No Analog Found (External Patterns)

These patterns are first-of-their-kind in this repo. Use the cited external source verbatim.

| File | Pattern | External Source | Why No In-Repo Analog |
|------|---------|-----------------|----------------------|
| `publish-sdks.yml`, `publish-cli.yml` | `uv publish --trusted-publishing automatic` | `uv publish --help` output (RESEARCH.md §`uv publish --trusted-publishing automatic`); fallback `pypa/gh-action-pypi-publish@release/v1` | First uv-trusted-publishing invocation; existing repo only ever used `UV_PUBLISH_TOKEN` env injection. |
| `publish-sdks.yml`, `publish-cli.yml` | `pip index versions <pkg>` / `npm view <pkg> version` exit-code-driven gate | RESEARCH.md §"Pre-flight Name-Availability Script"; verified locally with pip 26.1 and npm 10.9.7 | First time we gate a workflow on registry name availability — no precedent in `ci.yml` or other workflows. |
| `verify-published.yml` | `docker run --rm <image> sh -c "<cmd>"` clean-machine smoke | RESEARCH.md §`verify-published.yml` Structure (verified Docker images locally) | First time we run a fresh Docker image inside a GitHub Actions job for verification. `ci.yml` uses runner-native tools, not Docker-in-Actions. |

---

## Metadata

**Analog search scope:** `.github/workflows/` (5 files), `docs/sdks.md`, `docs/cli.md`
**Files scanned:** 7
**Pattern extraction date:** 2026-05-02
**Cross-cutting note:** Phase 227's `ci.yml:342-356` (SAML fixture guard) is the most recent precedent for adding a new step to an existing workflow job — same insertion mechanics apply when adding the pre-flight gate to `publish-sdks.yml` / `publish-cli.yml`.
