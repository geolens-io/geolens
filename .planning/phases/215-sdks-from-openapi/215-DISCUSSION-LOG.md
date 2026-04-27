# Phase 215: sdks-from-openapi - Discussion Log

> **Audit trail only.** Auto-mode invocation; Claude judgment for all gray areas.

**Date:** 2026-04-27
**Phase:** 215-sdks-from-openapi
**Mode:** `--auto --chain` (no user prompts; recommended option selected for each gray area)

---

## Auto-Selected Decisions

[auto] All 6 gray areas selected.

### Gray area 1 — Generator selection (Python)
[auto] Q: "Which Python OpenAPI generator?"
- ✓ openapi-python-client — modern, async-first, pydantic v2 native, no JVM
- openapi-generator (Java) — most mature but JVM dependency
- Custom (handwritten httpx wrapper) — most control but recurring maintenance
**Selected:** openapi-python-client (recommended default)

### Gray area 2 — Generator selection (TypeScript)
[auto] Q: "Which TypeScript OpenAPI generator?"
- ✓ @hey-api/openapi-ts — modern, fast, customizable, ESM/TS5 native
- openapi-typescript-codegen — older, less actively maintained
- swagger-typescript-api — fast but template syntax is less flexible
**Selected:** @hey-api/openapi-ts (recommended default)

### Gray area 3 — Package layout
[auto] Q: "Where do the SDK packages live?"
- ✓ In-repo monorepo (`sdks/python/`, `sdks/typescript/`) — single source of truth, atomic commits
- Separate repos (`geolens-sdk-python`, `geolens-sdk-ts`) — repo isolation hygiene
- One repo for both languages, separate from `geolens` repo
**Selected:** In-repo monorepo (recommended default)

### Gray area 4 — Versioning strategy
[auto] Q: "How are SDK versions tied to backend?"
- ✓ Lockstep with backend (SDK version = `openapi.json` info.version)
- Independent semver (SDK versioned separately)
- Hybrid (lockstep major.minor; SDK patches independent)
**Selected:** Lockstep (recommended default — SDK is a derived artifact)

### Gray area 5 — Auth helper layering
[auto] Q: "How do consumers configure Bearer token + API key?"
- ✓ Thin hand-written wrapper (`auth.py`/`auth.ts`) on top of generated client
- Generator config injects auth into generated code
- Consumer wires auth themselves (no helper)
**Selected:** Thin hand-written wrapper (recommended — keeps generator-output regen-clean; wrapper exempt from drift gate via `:!` pathspec)

### Gray area 6 — Drift gate mechanism
[auto] Q: "How does CI catch SDK drift?"
- ✓ `make sdks-check` regenerates and runs `git diff --exit-code sdks/`
- Periodic regen (`make sdks` runs in pre-commit hook)
- Hash file (`sdks/.openapi-hash`) compared to backend snapshot's hash
**Selected:** make sdks-check + git diff (recommended — mirrors existing `make openapi-check` pattern)

---

## Critical Note — Manual User Action Required

**Actual publication to PyPI / npm is OUT OF SCOPE for autonomous execution.** Phase 215 ships:
- `make publish-sdks-py` and `make publish-sdks-ts` recipes
- `.github/workflows/publish-sdks.yml` (manual `workflow_dispatch` trigger)
- Documentation in `docs/sdks.md` describing the publish process

**The user must, before first publish:**
1. Create a PyPI account + API token (`PYPI_TOKEN`); add to GitHub repo secrets.
2. Create an npm account + access token (`NPM_TOKEN`); claim the `@geolens` org on npm; add token to GitHub repo secrets.
3. Manually trigger the `publish-sdks.yml` workflow OR run `make publish-sdks-py` / `make publish-sdks-ts` locally.

This is captured in CONTEXT.md `<deferred>` and explicitly called out in the phase verification gate (Plan 04+ checks). ROADMAP SC#1 / SC#2 say "`pip install geolens-sdk`" works — that requires the user's manual publish action; the verification gate confirms the package BUILDS correctly (`uv build sdks/python/`) but the published-state assertion is deferred.

---

## Claude's Discretion (planner picks)

Captured in CONTEXT.md `<decisions>` § "Claude's Discretion":
- 4-5 plan decomposition (planner may collapse)
- TypeScript fetch vs axios variant (default fetch; switch only if Node 18 issue surfaces)
- Whether to commit generated code (yes; default)
- Bun vs npm for TypeScript (npm; project uses npm in frontend)
- Whether to actually publish during phase (no; user action only)

## Deferred Ideas

Captured in CONTEXT.md `<deferred>`:
- Actual v1.0.0 PyPI/npm publication
- `geolens.yaml` manifest spec (OCSDK-05, P2)
- SDK documentation site (pdoc/typedoc)
- OpenAPI 3.1 polymorphism handling (rare)
- Backwards-compat pinning across backend versions (lockstep only)
- CI auto-publish on tag push (manual trigger only for v13.1)
- Frontend migration to use generated TS SDK
