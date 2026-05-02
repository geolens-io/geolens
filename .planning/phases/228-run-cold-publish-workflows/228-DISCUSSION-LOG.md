# Phase 228: run-cold-publish-workflows - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-02
**Phase:** 228-run-cold-publish-workflows
**Mode:** `--auto --chain` (Claude auto-selected recommended option per gray area; no interactive prompts)
**Areas discussed:** PyPI authentication strategy, npm authentication, publish sequencing, name-availability check, version strategy, clean-machine verification mechanism, doc updates, CI billing posture

---

## PyPI authentication strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Trusted Publishing (OIDC) | No long-lived token; PyPI verifies GitHub OIDC token at publish time. `id-token: write` already declared in workflows. | ✓ |
| Long-lived `PYPI_TOKEN` secret | Generate PyPI account-scoped or project-scoped token, store as repo secret. | |
| Hybrid (Trusted Publishing for new projects, token for legacy) | Mix-and-match. | |

**Rationale:** The `permissions: id-token: write` block is already in both publish workflows with a comment that literally says "for PyPI Trusted Publishing (future migration)" — the workflow architecture has been waiting for this since Phase 215. `gh secret list` confirms `PYPI_TOKEN` doesn't exist yet, so this is the lowest-friction time to migrate (skip create-then-rotate-then-delete). PyPI officially recommends Trusted Publishing as the primary auth pattern as of 2024+. Eliminates token-leak risk and rotation burden.

---

## npm authentication

| Option | Description | Selected |
|--------|-------------|----------|
| Classic `NPM_TOKEN` (Automation type) | Long-lived token, stored as repo secret. | ✓ |
| npm OIDC trusted publishing | Modern; mirrors PyPI Trusted Publishing. | |

**Rationale:** npm's OIDC trusted publishing is still beta as of 2026-05 — not all features are stable enough for production publish. Use Automation tokens (work past 2FA, recommended over Publish tokens which break in CI). Migrate to npm OIDC later when GA.

---

## Workflow YAML changes for Trusted Publishing

| Option | Description | Selected |
|--------|-------------|----------|
| `uv publish --trusted-publishing automatic` | uv 0.5+ flag; consistent with existing uv-first toolchain. | ✓ (recommended) |
| `pypa/gh-action-pypi-publish@release/v1` | Official PyPA action with proven OIDC support. | (fallback if uv proves flaky) |

**Rationale:** uv is already in use everywhere in CI (`uv build`, `uv sync`, `uv publish`). Staying single-tool-chain is cleaner. Fallback to PyPA action is named in CONTEXT.md if uv's `--trusted-publishing` flag misbehaves in practice.

---

## Publish sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Dry-run-first cadence (dry_run=true → dry_run=false per workflow) | Validates build artifacts before immutable side-effect | ✓ |
| Hot publish only (skip dry-run) | Faster but riskier | |

**Rationale:** PyPI and npm versions are IMMUTABLE — botched publish cannot be undone (only yanked). Dry-run catches build-side regressions. Cost: 2 workflow runs per package vs 1; negligible CI minutes.

---

## Pre-flight name-availability check

| Option | Description | Selected |
|--------|-------------|----------|
| Hard gate (fail if any package shows `>= 1.0.0` we don't recognize) | Blocks unauthorized publishes from outside the repo | ✓ |
| Informational only (just print, don't fail) | Less safe but lower friction | |
| Skip the check entirely | One-time concern; not worth automating | |

**Rationale:** Names ARE the supply-chain trust anchor. If `geolens-sdk` shows `1.0.0` already on PyPI before we publish, that's either a typosquatter or a prior un-tracked publish — either case warrants stopping. Workflow input `force=true` allows operator to override after investigation.

---

## Version strategy for first publish

| Option | Description | Selected |
|--------|-------------|----------|
| Use current `1.0.0` from pyproject.toml / package.json | The deliberate "first public release" version from the v13.0 → 1.0.0 reset | ✓ |
| Bump to 1.0.1 first | "Cleanest" first publish | |
| Bump to 0.1.0 (pre-1.0 semver) | Conservative for an inaugural publish | |

**Rationale:** Project memory notes the version reset to 1.0.0 was the public-release marker (shipped 2026-04-01). Bumping for "cleanliness" would muddy provenance. 1.0.0 is the right number for the first public publish; future publishes bump per semver.

---

## Clean-machine install verification (PUBLISH-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Separate `verify-published.yml` workflow with Docker jobs | Re-runnable, tight blast radius, idiomatic | ✓ |
| Inline post-publish job in existing workflows | Tighter coupling but less re-runnable | |
| Manual verification only (run on local machine) | Doesn't satisfy the "automated" implication of "validated against published artifacts" | |

**Rationale:** Separate workflow gives independent re-runnability for "did the package break for downstream users?" debugging. Two Docker jobs (Python 3.13-slim + Node 22-slim), three install commands, exit-code pass/fail. ~30 lines of YAML. Future-proofs for release-tag triggering.

| Option | Description | Selected |
|--------|-------------|----------|
| Verify against highest classifier (Python 3.13, Node 22) | Strongest signal at lowest CI cost | ✓ |
| Matrix verify (Python 3.10/3.11/3.12/3.13 × Node 18/20/22) | Comprehensive but burns CI minutes | |

**Rationale:** PyPI's resolver enforces `requires-python` constraints; trust it for now. Matrix can be added later if downstream users surface 3.10/3.11/3.12 issues.

---

## Documentation updates

| Option | Description | Selected |
|--------|-------------|----------|
| Update `docs/sdks.md` and `docs/cli.md` Publishing sections | Replace token-creation steps with Trusted Publishing setup | ✓ |
| Leave docs as-is, add new "Trusted Publishing" appendix | Less disruptive but creates stale primary docs | |
| Defer doc updates to a follow-up phase | Cheap shortcut | |

**Rationale:** Docs are read by the next maintainer; stale instructions cause real-world harm. Updating in-phase preserves accuracy. Add a brief "Trusted Publishing setup" subsection walking through PyPI web-UI fields with our specific values.

---

## CI billing / Actions minutes posture

| Option | Description | Selected |
|--------|-------------|----------|
| Acknowledge billing risk; no mitigations needed | Publish workflows are workflow_dispatch-only; verify-published is bounded | ✓ |
| Throttle verify-published to PR-only triggers | Defensive but reduces protection | |
| Add billing-state preflight (skip if quota near zero) | Over-engineered for the actual blast radius | |

**Rationale:** Per project memory, free-tier Actions minutes routinely exhaust on push events. Phase 228 uses workflow_dispatch (manual trigger), so it's already insulated from accidental burns. Verify-published adds 2-3 minutes per run; bounded. If the maintainer hits a billing wall mid-phase, the resolution is "wait for billing reset" — not a phase decision.

---

## Claude's Discretion

- Phrasing of the new "Trusted Publishing setup" subsection in `docs/sdks.md`
- Inline preflight check vs `.github/scripts/preflight-publish.sh` (recommended: inline)
- `verify-published.yml` `version` input (default `latest`) vs always-latest (recommended: take an input)
- Exact CLI command for the OIDC publish (`uv publish --trusted-publishing automatic` vs `pypa/gh-action-pypi-publish@release/v1`) — D-03 recommends uv-first

## Deferred Ideas

- Release-tag-driven publishes (`on: push: tags: 'v*'`) — future phase
- npm OIDC trusted publishing — wait for GA
- SBOM / sigstore signing — Phase 999.15
- Multi-Python-version verification matrix — future phase if regressions surface
- Cross-platform CLI binaries (PyInstaller/Nuitka) — out of scope
- Homebrew / AUR / winget formulas — out of scope
- Yank/deprecation policy + tooling — none to yank yet
- Release notes automation (changelog → PyPI description) — manual via `changelog` skill is fine
- Security advisory pipeline (CVE intake) — separate concern
