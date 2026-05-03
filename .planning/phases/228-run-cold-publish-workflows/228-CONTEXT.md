# Phase 228: run-cold-publish-workflows - Context

**Gathered:** 2026-05-02
**Status:** Ready for planning
**Mode:** `--auto --chain` (recommended decisions auto-selected)

<domain>
## Phase Boundary

Convert the wired-but-cold publish workflows from "wired" to "shipped" by executing each at least once end-to-end and validating the published artifacts on a clean machine. After this phase:

- `secrets.PYPI_TOKEN` is **NOT** added (replaced by PyPI Trusted Publishing — see D-01); `secrets.NPM_TOKEN` IS added (npm OIDC trusted-publishing is still in beta as of 2026-05). The current repo secret inventory (verified via `gh secret list`) shows ONLY `GEOLENS_ENTERPRISE_TOKEN` — both `PYPI_TOKEN` and `NPM_TOKEN` are absent today, which is why PUBLISH-01 is unsatisfied.
- PyPI Trusted Publishing is configured for `geolens` (Python SDK, workflow `publish-sdks.yml`) and `geolens-cli` (CLI, workflow `publish-cli.yml`) via the PyPI web UI. Required fields: PyPI Project Name, GitHub repository owner, repository name, workflow filename, and environment name (none — repo-level OIDC). The workflows declare `permissions: id-token: write`, so no long-lived PyPI token is required.
- `publish-sdks.yml` runs end-to-end on `main` once via `workflow_dispatch` with `target=both, dry_run=false` after a preceding `dry_run=true` validation. `geolens@1.0.0` is installable from PyPI; `@geolens/sdk@1.0.0` is installable from npm.
- `publish-cli.yml` runs end-to-end on `main` once via `workflow_dispatch` with `dry_run=false` after a preceding `dry_run=true` validation. `geolens-cli@1.0.0` is installable from PyPI; `pip install geolens-cli && geolens --version` returns `1.0.0` on a fresh Python 3.11+ environment.
- A new "clean-machine install verification" job/step runs in a fresh Docker container (`python:3.13-slim` for Python; `node:22-slim` for npm) and asserts each install command from `docs/sdks.md` and `docs/cli.md` succeeds against the published artifacts (no local checkout context). This satisfies PUBLISH-04. The verification can be a separate one-shot workflow (`.github/workflows/verify-published.yml`) triggered after publish, or an inline post-publish job in the existing publish workflows. Plan picks; recommended: separate workflow so verification can be re-run independently of publishing.
- Phase VERIFICATION.md documents: (a) PyPI pending-publisher configuration screenshots/text, (b) `gh secret list` output showing `NPM_TOKEN` present + `PYPI_TOKEN` absent (confirming Trusted Publishing path), (c) successful workflow run URLs for `publish-sdks.yml` and `publish-cli.yml`, (d) clean-machine install command output for all three packages.
- `docs/sdks.md` (lines ~28–34) and `docs/cli.md` updated: replace the "Create a PyPI token" instructions with "PyPI Trusted Publishing — no token needed" guidance for Python projects; keep the npm token instructions as-is.
- A pre-flight package-name availability check is run BEFORE the first hot publish: `pip index versions geolens`, `pip index versions geolens-cli`, and `npm view @geolens/sdk version`. Each must return either "no versions" / `404` (name unclaimed — first publish will claim it) or no `1.0.0` release yet. If any target already returns `1.0.0`, STOP unless this is an intentional retry with `force_publish=true`.

**In scope:** configure PyPI Trusted Publishing for `geolens` and `geolens-cli` projects (web-UI step, documented in VERIFICATION.md); add `NPM_TOKEN` repo secret (manual, documented in VERIFICATION.md); update `publish-sdks.yml` Python job to use `uv publish --trusted-publishing automatic`; update `publish-cli.yml` similarly; pre-flight version checks; run `dry_run=true` once per workflow to validate build artifacts; run `dry_run=false` once per workflow to publish; create `.github/workflows/verify-published.yml` for the clean-machine install verification; update `docs/sdks.md` and `docs/cli.md` to reflect the new auth pattern; write `.planning/phases/228-run-cold-publish-workflows/228-VERIFICATION.md` capturing all four success criteria with workflow run URLs, install command output, and the secret/publisher inventory.

**Out of scope:** any change to the SDK / CLI source code or build configuration (`sdks/python/pyproject.toml`, `sdks/typescript/package.json`, `cli/pyproject.toml` are all set at `1.0.0` and stay there); a release-tag-driven publish (workflows stay `workflow_dispatch` only — release-tag automation is a future phase); npm OIDC migration (still beta — defer); SBOM/sigstore signing of artifacts (defer to Phase 999.15 which is the SBOM phase); a Homebrew/AUR/winget formula for the CLI; cross-platform CLI binaries (Python wheel only); deprecation/yank policy for prior versions (none exist yet); a "release notes" automation that ties git tags to PyPI release descriptions; security advisories or CVE handling for the published packages; account-level password policies or 2FA enforcement on the PyPI/npm accounts (assumed already configured by the maintainer).

</domain>

<decisions>
## Implementation Decisions

### Authentication strategy

- **D-00 — `@geolens` npm organization MUST be claimed BEFORE the first npm publish.** Confirmed via `https://registry.npmjs.org/-/org/geolens` → `{"code":"ResourceNotFound"}` (228-RESEARCH.md §npm Token Runbook Step 1). Without this, `npm publish @geolens/sdk` fails with a scope-not-found error. The maintainer creates the org at <https://www.npmjs.com/org/create> (org name: `geolens`, claims `@geolens` scope for the `geolens-io` account). This is a manual one-time prerequisite — must precede D-02 token creation since granular tokens scope-bind to the org. Acceptance: `npm view @geolens` returns the org metadata (not a 404) AND the maintainer's npm account is listed as an admin.

- **D-01 — PyPI Trusted Publishing (OIDC) for both `geolens` and `geolens-cli` projects.** No long-lived `PYPI_TOKEN` secret. Trusted Publishing eliminates token-leak risk, removes the rotation burden, and is PyPI's recommended pattern. The PyPI web-UI configuration is per-project: `geolens` points at `publish-sdks.yml`; `geolens-cli` points at `publish-cli.yml`. Acceptance: `gh secret list --repo geolens-io/geolens | grep PYPI_TOKEN` returns nothing AND manual workflow-dispatch live runs succeed AND PyPI shows the published `1.0.0` versions with provenance attestations.

- **D-02 — Granular access token (with "Bypass 2FA" enabled) `NPM_TOKEN` repo secret for npm.** npm's OIDC trusted-publishing is still beta as of 2026-05. **Important update from 228-RESEARCH.md:** npm permanently removed the "Automation" token type on **2025-12-09**; the modern replacement is a **granular access token** with "Bypass two-factor authentication" enabled (this is the box that makes it usable from CI). Token scope: the entire `@geolens` org (NOT package-specific — the package picker won't show `@geolens/sdk` until first publish, so org-scope is the correct workaround). Permissions: **Read and write**. Expiration: maximum (~90 days). Generate at <https://www.npmjs.com/settings/~/tokens> after the maintainer claims the `@geolens` org at <https://www.npmjs.com/org/create>. Add via `gh secret set NPM_TOKEN --body "$NPM_TOKEN" --repo geolens-io/geolens` (gh-CLI requires repo admin auth) or via the GitHub web UI. Document in `docs/sdks.md` that `NPM_TOKEN` rotates ~quarterly (90-day max lifetime); after first publish the token can be narrowed from `@geolens` scope to specifically `@geolens/sdk` on the next rotation. Acceptance: `gh secret list --repo geolens-io/geolens | grep NPM_TOKEN` returns one row dated 2026-05 or later AND a manual workflow-dispatch run of `publish-sdks.yml` (TypeScript target, dry_run=false) succeeds AND npm shows the published `@geolens/sdk@1.0.0` as `latest`.

- **D-03 — Workflow YAML changes for D-01 (Trusted Publishing).** Replace the `env: UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}` blocks at `publish-sdks.yml:60-61` and `publish-cli.yml:48-49` with `uv publish --trusted-publishing automatic` (uv 0.5+ supports this; the workflow uses uv 0.10.2 per `setup-uv@v6` line so it's safe). If `uv publish --trusted-publishing automatic` proves flaky in practice, the fallback is `pypa/gh-action-pypi-publish@release/v1` which is the official PyPA action with proven OIDC support. Plan picks; recommended: try `uv publish --trusted-publishing automatic` first since it preserves the single-tool-chain consistency. Either way, the `id-token: write` permission stays as-is (already declared).

### Publish sequencing

- **D-04 — Dry-run-first cadence for the inaugural publishes.** For each of the two workflows: (1) trigger `workflow_dispatch` with `dry_run=true` and confirm the build artifacts are produced (`uv build` for Python; `npm pack --dry-run` for TypeScript) and the workflow exits green; (2) trigger `workflow_dispatch` with `dry_run=false` to actually publish. Reason: PyPI and npm versions are IMMUTABLE — a botched first publish CANNOT be deleted (only "yanked" on PyPI; npm allows unpublish only within 72h and even then leaves a tombstone). Dry-run catches build-side regressions before the immutable side-effect. Acceptance: at least one `dry_run=true` Actions run is recorded for each workflow before the corresponding `dry_run=false` run.

- **D-05 — Pre-flight name-availability check.** Before the first hot publish, run a small bash script committed to `.github/scripts/preflight-publish.sh` (or inline in the workflow as a pre-step) that runs:
  ```bash
  pip index versions geolens 2>&1 | grep -q "1.0.0" && echo "geolens: 1.0.0 exists — investigate" || echo "geolens: no 1.0.0 yet"
  pip index versions geolens-cli 2>&1 | grep -q "1.0.0" && echo "geolens-cli: 1.0.0 exists — investigate" || echo "geolens-cli: no 1.0.0 yet"
  pip index versions geolens     2>&1 | grep -q "No matching" && echo "geolens: unclaimed" || echo "geolens: TAKEN — investigate"
  npm view @geolens/sdk version  2>&1 | grep -q "404" && echo "@geolens/sdk: unclaimed" || echo "@geolens/sdk: TAKEN — investigate"
  npm view geolens version       2>&1 | grep -q "404" && echo "geolens (npm): N/A — we don't publish here" || echo "geolens npm: present"  # informational only
  ```
  Fail the job (`exit 1`) if any target already contains the exact version being published and `force_publish` is not set.

- **D-06 — Versions stay at `1.0.0` from current `pyproject.toml` / `package.json`.** Do NOT bump versions for the first publish. Reason: those versions were set by the v13.0 → 1.0.0 reset (per project memory: "1.0.0 Public Release: shipped 2026-04-01 — backend/frontend versions reset from 13.x to 1.0.0"); they're the deliberate "first public release" version numbers. A pre-publish bump would muddy the provenance — `1.0.0` is the right number for the first public-tagged release. Future publishes will bump per semver; that's a separate operational concern.

### Clean-machine install verification (PUBLISH-04)

- **D-07 — Separate workflow `.github/workflows/verify-published.yml` for clean-machine smoke checks.** Two jobs: `verify-python` (runs `pip install geolens geolens-cli`, `geolens --version`, and `from geolens import GeolensClient`) and `verify-typescript` (runs `npm install @geolens/sdk` and imports it). Trigger: `workflow_dispatch` and release tags. Acceptance: `verify-published.yml` exists, has been run at least once, and both jobs exit 0.

- **D-08 — Clean-machine env minimums.** Python verification uses `python:3.13-slim` (matches the publish workflow's `actions/setup-python@v5: "3.13"` minor) — 3.13 is the highest in our `classifiers` for both `geolens` and `geolens-cli`, so verifying against the highest is the strongest signal. We do NOT verify against 3.10/3.11/3.12 in this phase (deferred — that's a matrix-build job and adds CI minutes); the `requires-python = ">=3.10"` (`geolens`) and `>=3.11"` (`geolens-cli`) constraints are trusted to be honored by PyPI's resolver. npm verification uses `node:22-slim` (matches `setup-node@v6: 22` in `publish-sdks.yml:69` and the package's `"engines": { "node": ">=18" }` declaration). Plan can later add a verification matrix if desired.

### Documentation updates

- **D-09 — Update `docs/sdks.md` and `docs/cli.md` to reflect the new auth pattern.** The sections to edit:
  - `docs/sdks.md` lines 30–34 (the "Create a PyPI token" instructions) — replace with "PyPI authentication is via Trusted Publishing (no token required). See `.github/workflows/publish-sdks.yml` for the OIDC configuration and PyPI's web UI for the pending-publisher setup."
  - `docs/sdks.md` line 32 (the "Create an npm token" instructions) — keep as-is, but rephrase to clarify that npm is token-based BECAUSE npm OIDC is still beta.
  - `docs/cli.md` (Publishing section, currently §"Publishing" not yet found via grep — locate by reading the file) — same Trusted Publishing update for the PyPI side; CLI doesn't publish to npm.
  - Add a brief "Trusted Publishing setup" subsection to `docs/sdks.md` walking through the PyPI web-UI fields with our specific values (Owner: `geolens-io`, Repository: `geolens`, Workflow: `publish-sdks.yml`, Environment name: `(none)`).

### CI billing / Actions minutes

- **D-10 — Acknowledge billing risk; do NOT add CI-minute mitigations.** Project memory ([geolens-io Actions billing](memory:project_geolens_io_actions_billing.md)) notes that geolens-io free-tier Actions minutes routinely exhaust, breaking push CI while PR CI keeps working. Phase 228 explicitly EXECUTES Actions workflows (the whole point of "shipping" them). Mitigations like "throttle to PR-only" are out of scope — the publish workflows are `workflow_dispatch`-only by design (manual trigger from a maintainer's keyboard) so they don't fire on every push. The `verify-published.yml` adds maybe 2-3 minutes per run; bounded. If the maintainer hits a billing wall mid-phase, the resolution is "wait for billing reset 2026-06-01" — that's an operational reality, not a phase decision. Acceptance: VERIFICATION.md notes the publish workflow run timestamps, billing state at that time, and any Actions-minute consumption observed.

### Claude's Discretion

- The exact phrasing of the new "Trusted Publishing setup" subsection in `docs/sdks.md` (planner picks the heading level and word count).
- Whether to use `uv publish --trusted-publishing automatic` (cleaner) or `pypa/gh-action-pypi-publish@release/v1` (more standard) for the OIDC flow (D-03 recommends uv-first; planner can switch if uv's flag proves unreliable in practice).
- Whether the pre-flight name-check (D-05) lives in a shell script under `.github/scripts/` (reusable) or inline in each publish workflow's first job (no extra file). Recommended: inline. Less indirection for a 4-line check.
- Whether the `verify-published.yml` workflow takes a `version` input (default: `latest`) so it can verify a specific past version, or always pulls `latest`. Recommended: take an input — costs nothing and makes the workflow more useful for downstream-break debugging.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and success criteria
- `.planning/ROADMAP.md` §"Phase 228: run-cold-publish-workflows" — goal, success criteria (4 items), source provenance (`oc-separation-audit-20260430-b.md` §6 / §7 P2), promotion-from-999.17 history.
- `.planning/REQUIREMENTS.md` §"Phase 228 — PUBLISH-01..04" — bound requirements (PUBLISH-01: PYPI_TOKEN/NPM_TOKEN present OR Trusted Publishing migrated; PUBLISH-02: publish-sdks.yml E2E green; PUBLISH-03: publish-cli.yml E2E green; PUBLISH-04: README install instructions validated against published artifacts).

### Existing workflow files
- `.github/workflows/publish-sdks.yml` — declares `permissions: id-token: write`; supports `workflow_dispatch` with `target`, `dry_run`, and `force_publish` inputs; Python publishing uses `uv publish --trusted-publishing automatic` for the `geolens` package; TypeScript publishing uses `NODE_AUTH_TOKEN` for npm; first-publish-ready (`--access public` flag set, `publishConfig.access=public` in package.json — RESEARCH Pitfall 10 from Phase 215).
- `.github/workflows/publish-cli.yml` — declares `permissions: id-token: write`; supports `workflow_dispatch` with `dry_run` and `force_publish` inputs; PyPI publishing uses `uv publish --trusted-publishing automatic` for the `geolens-cli` package.
- `.github/workflows/ci.yml` — touched here ONLY for reference (Phase 227 added the SAML guard); 228 does NOT modify ci.yml.

### Package metadata (sources of truth for what gets published)
- `sdks/python/pyproject.toml` — `name = "geolens"`, `version = "1.0.0"`, `requires-python = ">=3.10"`, `license = "Apache-2.0"`, `build-backend = "hatchling.build"`. Versions stay (D-06).
- `sdks/typescript/package.json` — `"name": "@geolens/sdk"`, `"version": "1.0.0"`, `"license": "Apache-2.0"`, `"engines": { "node": ">=18" }`, `"publishConfig": { "access": "public" }`. Versions stay.
- `cli/pyproject.toml` — `name = "geolens-cli"`, `version = "1.0.0"`, `requires-python = ">=3.11"`, `license = "Apache-2.0"`. Versions stay.

### Documentation to update
- `docs/sdks.md` — current "First-publish runbook" sits around lines 28–45 (per grep); replace token-creation steps with Trusted Publishing setup (D-09).
- `docs/cli.md` — has a "Publishing" section that needs the same Trusted Publishing update; locate by grepping for the section header in the file.
- `README.md` — verify (don't necessarily change) that the install instructions (`pip install geolens`, `npm install @geolens/sdk`, `pip install geolens-cli`) are present and accurate. README is the source for PUBLISH-04 verification.

### External documentation (read once during planning if you've never used these)
- PyPI Trusted Publishing docs: <https://docs.pypi.org/trusted-publishers/> — the web-UI flow for adding a "pending publisher".
- `uv publish --trusted-publishing` flag: <https://docs.astral.sh/uv/reference/cli/#uv-publish> (or `uv publish --help` from the CLI).
- npm token types: <https://docs.npmjs.com/creating-and-viewing-access-tokens> — "Automation" tokens are the recommended type for CI.
- `pypa/gh-action-pypi-publish` (fallback for D-03): <https://github.com/pypa/gh-action-pypi-publish>

### Source / provenance
- `docs-internal/audits/oc-separation-audit-20260430-b.md` §6 (WIRED — never run) and §7 P2 — the audit finding that promoted Phase 228 from backlog 999.17.

### Operational hazards (project memory)
- [geolens-io Actions billing](memory:project_geolens_io_actions_billing.md) — free-tier private-repo Actions minutes routinely exhaust; push CI fails (`runner_id: 0`, `steps: []`) while PR CI keeps working. Phase 228 uses `workflow_dispatch` (manual trigger), not push, so it's mostly insulated — but the `verify-published.yml` workflow could be configured to skip on push events to be extra safe.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`workflow_dispatch` with `dry_run` boolean input** — both publish workflows already have this. Reuse pattern for `verify-published.yml`.
- **`actions/setup-uv@v6` + `actions/setup-python@v5`** — standard Python toolchain steps already used in `ci.yml` and the publish workflows. Reuse verbatim.
- **`actions/setup-node@v6` with `registry-url: 'https://registry.npmjs.org'`** — the npm-publish-ready Node setup already in `publish-sdks.yml:68-72`. Reuse for `verify-published.yml` (Node side) but DROP `registry-url` (publish-side concern).
- **`uv build` / `npm run build` / `npm pack --dry-run`** — already wired in publish workflows; the dry-run cadence (D-04) just toggles `dry_run` input.

### Established Patterns
- **Manual-trigger publish workflows** (`workflow_dispatch` only, NOT `on: push` or release tag) — the project explicitly chose this pattern in Phase 215/216 to avoid accidental publishes. Phase 228 preserves it; release-tag automation is deferred.
- **Belt-and-braces npm scoped-publish** — `package.json` declares `publishConfig.access=public` AND the workflow passes `--access public` explicitly. RESEARCH Pitfall 10 from Phase 215 documents why both are needed for `@geolens/sdk` first-publish (npm's `402 Payment Required` foot-gun).
- **`id-token: write` permission already declared** in both publish workflows — Trusted Publishing migration is "drop the env block, add the trusted-publishing flag", not "rewire permissions".
- **uv-first toolchain** — every Python step in CI uses `uv` (build, sync, publish). Stay consistent in `verify-published.yml` Python job: `pip install geolens` is fine for the verification (mimics what a downstream user does), NOT `uv add` (that's project-management ergonomics, not a public-install smoke test).

### Integration Points
- **GitHub repo secrets surface**: `gh secret list --repo geolens-io/geolens` is the source-of-truth read; `gh secret set NAME --body $VALUE --repo geolens-io/geolens` is the write. Plan should NOT script secret creation — the maintainer manually adds `NPM_TOKEN` and configures Trusted Publishing in the PyPI web UI, then the plan's workflow runs verify the result. Documenting the manual steps in VERIFICATION.md is sufficient for audit trail.
- **PyPI / npm web UIs** are out-of-band — no automation possible (and shouldn't be — these are credential surfaces). Plan's tasks for D-01 and D-02 are "human runbook items" verified by side effects (token list, successful workflow runs, `pip install` smoke).
- **No production code or Alembic migration touched.** Phase is scoped entirely to `.github/workflows/`, `docs/sdks.md`, `docs/cli.md`, possibly `.github/scripts/preflight-publish.sh`, and `.planning/phases/228-*/`.

</code_context>

<specifics>
## Specific Ideas

- **Trusted Publishing is the modern path** — PyPI explicitly recommends OIDC over long-lived tokens since 2023. The `id-token: write` permission is already declared in both workflows (lines `publish-sdks.yml:25` and `publish-cli.yml:18`) with a comment literally saying "for PyPI Trusted Publishing (future migration)". Phase 228 is when "future" becomes "now."
- **npm token type matters** — use "Automation" tokens (work past 2FA) NOT "Publish" tokens (which require interactive 2FA on each publish — broken in CI). Document this explicitly in `docs/sdks.md` so future maintainers don't pick the wrong type when rotating.
- **Pre-flight check is hand-rollable** — no need for a fancy GitHub Action; a 4-line inline bash step suffices (D-05). If it ends up reused elsewhere, factor into `.github/scripts/preflight-publish.sh` later.
- **`verify-published.yml` is small and self-contained** — ~30 lines max. Two jobs, two `docker run` invocations each, exit-code-based pass/fail. Don't over-engineer — this is a smoke check, not an integration test.

</specifics>

<deferred>
## Deferred Ideas

- **Release-tag-driven publishes** (`on: push: tags: 'v*.*.*'`) — defer to a future phase. Phase 228 keeps `workflow_dispatch`-only to avoid accidental publishes during the inaugural setup. Future phase: convert to tag-driven once the team is comfortable with the manual flow.
- **npm OIDC trusted publishing** — still beta as of 2026-05; revisit once it's GA. When migrating, drop `NPM_TOKEN` and update `publish-sdks.yml` TypeScript job similarly to D-03.
- **SBOM / sigstore signing of artifacts** — defer to Phase 999.15 (`sbom-and-signed-image-distribution`) which is already in the backlog. PyPI's Trusted Publishing does emit attestations automatically, which is a partial SBOM signal — note in VERIFICATION.md.
- **Multi-Python-version verification matrix** (3.10, 3.11, 3.12, 3.13) — D-08 verifies only against 3.13. Future phase if downstream user reports surface 3.10/3.11/3.12 install regressions.
- **Cross-platform CLI binaries** (PyInstaller / Nuitka) — out of scope; CLI ships as a Python wheel only.
- **Homebrew / AUR / winget formula for `geolens` CLI** — out of scope; PyPI is the only distribution channel for now.
- **Yank/deprecation policy and tooling** — no prior versions exist; revisit when there's something to yank.
- **Release notes automation** (changelog → PyPI release description) — out of scope; handled by the existing `changelog` skill manually.
- **Security advisory pipeline (CVE intake / GHSA → PyPI / npm)** — separate concern; pull in only if we publish a vulnerable version that needs patch-release coordination.

</deferred>

---

*Phase: 228-run-cold-publish-workflows*
*Context gathered: 2026-05-02*
