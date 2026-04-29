---
phase: 215-sdks-from-openapi
plan: 01
subsystem: infra
tags: [openapi, sdk, python, typescript, openapi-python-client, hey-api, packaging, apache-2.0]

# Dependency graph
requires:
  - phase: 214-identity-protocol-extract
    provides: stable backend/openapi.json snapshot the SDK generators consume in Plan 02
provides:
  - sdks/python/ scaffold (pyproject.toml, .openapi-python-client.yaml, LICENSE, README, .gitignore)
  - sdks/typescript/ scaffold (package.json, tsconfig.json, openapi-ts.config.ts, LICENSE, README, .gitignore)
  - Pinned generator versions (openapi-python-client@0.28.3, @hey-api/openapi-ts@0.96.1, @hey-api/client-fetch@0.13.1)
  - Apache-2.0 license declarations + verbatim LICENSE copies in both SDK packages
  - npm publish hygiene wired (publishConfig.access=public, files whitelist dist+LICENSE+README.md, prepublishOnly script)
affects:
  - 215-02 (first generator run writes into these scaffold dirs)
  - 215-03 (auth wrappers added alongside generated code)
  - 215-04 (round-trip test imports from these packages)
  - 215-05 (docs/sdks.md references generator config + version-pin policy)
  - 216-geolens-cli-mvp (CLI depends on geolens-sdk python package metadata declared here)

# Tech tracking
tech-stack:
  added:
    - openapi-python-client (0.28.3, generator config only — runs via uvx, not installed)
    - "@hey-api/openapi-ts (0.96.1, generator dev dep)"
    - "@hey-api/client-fetch (0.13.1, generator runtime dep)"
    - hatchling (Python build backend declared in pyproject)
    - typescript ^5.6.0 (TS SDK build dev dep)
  patterns:
    - In-repo monorepo SDK layout (sdks/python, sdks/typescript) per CONTEXT.md D-04
    - Hand-maintained metadata files exempted from drift gate (Plan 02 will add the gate)
    - Pinned generator versions (no caret on @hey-api/* deps) for reproducible regeneration
    - Apache-2.0 license declared via project metadata + verbatim LICENSE file copy from repo root
    - npm publish whitelist (`files: ["dist", "LICENSE", "README.md"]`) restricts published artifact contents

key-files:
  created:
    - sdks/python/pyproject.toml
    - sdks/python/.openapi-python-client.yaml
    - sdks/python/LICENSE
    - sdks/python/README.md
    - sdks/python/.gitignore
    - sdks/typescript/package.json
    - sdks/typescript/tsconfig.json
    - sdks/typescript/openapi-ts.config.ts
    - sdks/typescript/LICENSE
    - sdks/typescript/README.md
    - sdks/typescript/.gitignore
  modified: []

key-decisions:
  - "Implemented D-04: in-repo monorepo SDK layout at sdks/python and sdks/typescript"
  - "Implemented D-05: package names geolens-sdk (PyPI) and @geolens/sdk (npm scoped)"
  - "Implemented D-06: both SDKs declare Apache-2.0 with verbatim LICENSE copy from repo root"
  - "Implemented D-07: lockstep version baseline 1.0.0 (Plan 02 sync_sdk_versions.py keeps in lockstep with backend/openapi.json info.version)"
  - "Pinned @hey-api/* deps without caret; typescript stays on ^5.6.0 because tsc minor patches are safe"
  - "Reconciled CONTEXT.md D-01 misstatement: generated Python code uses attrs (not pydantic v2) per openapi-python-client 0.28.x golden-record"

patterns-established:
  - "Generator config lives at sdks/{python|typescript}/{.openapi-python-client.yaml|openapi-ts.config.ts}; Makefile (Plan 02) reads these"
  - "package.json publishConfig.access=public is required for first publish of a scoped public npm package"
  - "Build artifacts (dist/, build/, *.egg-info/, node_modules/, *.tgz) gitignored at SDK package level — repo root .gitignore stays untouched"
  - "Generator output destinations (sdks/python/geolens_sdk/, sdks/typescript/src/) are NOT created at scaffold time; Plan 02's first generator run creates them"

requirements-completed: []
# Plan 01 is pure scaffolding. The requirements listed in the plan frontmatter
# (OCSDK-01, OCSDK-02, OCSDK-04) are NOT yet satisfied — they require generated
# SDK code (Plan 02), auth wrappers (Plan 03), round-trip success (Plan 04), and
# docs/sdks.md (Plan 05). Marked Pending in REQUIREMENTS.md until those plans
# complete. Plan 01 contributes scaffolding (Apache-2.0 declarations, package
# metadata, pinned generator config, publish hygiene) that those later plans
# build on.

# Metrics
duration: 1m 43s
completed: 2026-04-27
---

# Phase 215 Plan 01: Scaffold sdks/python and sdks/typescript Summary

**In-repo monorepo SDK directories scaffolded with pinned generator config (openapi-python-client@0.28.3 + @hey-api/openapi-ts@0.96.1 + @hey-api/client-fetch@0.13.1), Apache-2.0 licenses, npm publish hygiene, and gitignored build artifacts — ready for first generator run in Plan 02.**

## Performance

- **Duration:** 1m 43s
- **Started:** 2026-04-27T19:12:27Z
- **Completed:** 2026-04-27T19:14:10Z
- **Tasks:** 2
- **Files modified:** 11 created (5 Python + 6 TypeScript)

## Accomplishments

- `sdks/python/` scaffolded: hatchling build, geolens-sdk metadata, Apache-2.0, runtime deps `httpx >=0.23.0,<0.29.0` + `attrs >=22.2.0` + `python-dateutil >=2.8.0,<3.0.0`
- `sdks/typescript/` scaffolded: ESM package, Node >=18 engines, scoped `@geolens/sdk`, Apache-2.0, dev/runtime deps pinned to `0.96.1` / `0.13.1`
- Both SDK packages carry verbatim Apache-2.0 LICENSE files (`diff -q` clean against repo root LICENSE)
- Generator configs in place: `.openapi-python-client.yaml` (project_name_override, package_name_override, literal_enums, generate_all_tags, ruff post_hooks) and `openapi-ts.config.ts` (input `../../backend/openapi.json`, output `src/client`, plugins `@hey-api/typescript` + `@hey-api/sdk` + `@hey-api/client-fetch`)
- npm publish surface defined: `publishConfig.access=public`, `files: ["dist", "LICENSE", "README.md"]`, `prepublishOnly: npm run build`
- No generated code present yet — generator output dirs (`sdks/python/geolens_sdk/`, `sdks/typescript/src/`) intentionally absent

## Task Commits

Each task committed atomically:

1. **Task 1: Scaffold sdks/python with pyproject + generator config** — `059501a8` (feat)
2. **Task 2: Scaffold sdks/typescript with package.json + generator config** — `7136f504` (feat)

**Plan metadata commit:** pending (final commit captures this SUMMARY.md + STATE.md + ROADMAP.md updates)

## Files Created/Modified

### Created

- `sdks/python/pyproject.toml` — hatchling build, geolens-sdk metadata, Apache-2.0, runtime deps
- `sdks/python/.openapi-python-client.yaml` — generator config (project_name_override, package_name_override, package_version_override 1.0.0, literal_enums, generate_all_tags, ruff post_hooks)
- `sdks/python/LICENSE` — verbatim Apache-2.0 from repo root
- `sdks/python/README.md` — drift-exempt quickstart
- `sdks/python/.gitignore` — dist/, build/, *.egg-info/, __pycache__/, *.pyc, .pytest_cache/, .ruff_cache/
- `sdks/typescript/package.json` — @geolens/sdk metadata, ESM, Node >=18, pinned @hey-api/* deps, publishConfig.access=public, files whitelist
- `sdks/typescript/tsconfig.json` — ES2022 target, NodeNext module, declaration + sourceMap, outDir dist, rootDir src, strict
- `sdks/typescript/openapi-ts.config.ts` — defineConfig with input `../../backend/openapi.json`, output `src/client` + prettier format, three @hey-api plugins
- `sdks/typescript/LICENSE` — verbatim Apache-2.0 from repo root
- `sdks/typescript/README.md` — drift-exempt quickstart
- `sdks/typescript/.gitignore` — node_modules/, dist/, *.tgz, .DS_Store

### Modified

- None (pure scaffolding plan; STATE.md / ROADMAP.md / REQUIREMENTS.md updates land in the metadata commit below)

## Decisions Made

- **D-04 in-repo monorepo SDK layout** — `sdks/python/` and `sdks/typescript/` as self-contained packages
- **D-05 package names** — `geolens-sdk` (PyPI, importable as `geolens_sdk`) + `@geolens/sdk` (npm, scoped)
- **D-06 Apache-2.0 license** — declared in metadata + verbatim LICENSE copy in each SDK package
- **D-07 lockstep version baseline 1.0.0** — both SDKs ship at 1.0.0 to match backend; sync_sdk_versions.py (Plan 02) keeps them in lockstep on every regeneration
- **Pinned @hey-api/* deps** — no caret (`@hey-api/openapi-ts: 0.96.1`, `@hey-api/client-fetch: 0.13.1`) for reproducible regeneration; `typescript: ^5.6.0` is fine because tsc minor patches are safe
- **`literal_enums: true` + `generate_all_tags: true`** in Python generator config — cleaner enum output and endpoints accessible under all assigned FastAPI tags (matches backend's tag-per-router pattern)
- **Simpler `openapi-ts.config.ts` without `runtimeConfigPath`** — auth wrapper in Plan 03 sits alongside generated code rather than being injected at codegen time; avoids chicken-and-egg of the runtime config path not yet existing during the first regeneration
- **`hatchling` build backend** for Python SDK — minimal, modern, matches the slim metadata-only nature of this package

## Reconciliation Notes

- **CONTEXT.md D-01 misstatement** — D-01 calls the generator "pydantic v2 native". This is wrong. `openapi-python-client@0.28.x` emits `attrs`-based dataclasses with `to_dict()` / `from_dict(d)` methods. The generator uses pydantic *internally* to parse the OpenAPI spec, but generated client code carries no pydantic runtime dependency. Verified against `openapi-python-client/end_to_end_tests/golden-record/pyproject.toml` (RESEARCH.md §Pitfall referenced). The `pyproject.toml` written here therefore declares `attrs >=22.2.0` (not pydantic) as a runtime dep. Plan 02 will see `attrs` imports in generated models — that is correct, not a deviation.

## Verification

Plan-level verification block from PLAN.md ran clean. Selected checks:

```text
test -d sdks/python && test -d sdks/typescript                                                  PASS
test -f sdks/python/{pyproject.toml,.openapi-python-client.yaml,LICENSE,README.md,.gitignore}   PASS
test -f sdks/typescript/{package.json,tsconfig.json,openapi-ts.config.ts,LICENSE,README.md,.gitignore}  PASS
grep -q 'project_name_override: geolens-sdk' sdks/python/.openapi-python-client.yaml            PASS
grep -q '"@hey-api/openapi-ts": "0.96.1"' sdks/typescript/package.json                          PASS
grep -q '"@hey-api/client-fetch": "0.13.1"' sdks/typescript/package.json                        PASS
diff -q LICENSE sdks/python/LICENSE                                                             PASS
diff -q LICENSE sdks/typescript/LICENSE                                                         PASS
test ! -d sdks/python/geolens_sdk                                                               PASS
test ! -d sdks/typescript/src                                                                   PASS
node -e 'check name=@geolens/sdk, license=Apache-2.0, type=module, engines.node=>=18, ...'      PASS
```

## Deviations from Plan

None — plan executed exactly as written.

(Plan 01 was a pure scaffolding plan with deterministic file contents fully specified in the action blocks. No bugs, missing functionality, blockers, or architectural ambiguity surfaced.)

**Total deviations:** 0
**Impact on plan:** N/A

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required at scaffold time. The first publish (Plan 04+ deferred manual action per CONTEXT.md D-16) requires user-managed `PYPI_TOKEN` / `NPM_TOKEN` GitHub secrets, but that's documented as deferred and is out of scope for Plan 01.

## Next Phase Readiness

**Ready for Plan 02 (`make sdks` baseline regeneration):**
- `sdks/python/.openapi-python-client.yaml` is in place — `uvx openapi-python-client@0.28.3 generate --path backend/openapi.json --output-path sdks/python/ --overwrite --config sdks/python/.openapi-python-client.yaml` will populate `sdks/python/geolens_sdk/`
- `sdks/typescript/openapi-ts.config.ts` is in place — `cd sdks/typescript && npx --yes @hey-api/openapi-ts@0.96.1` will populate `sdks/typescript/src/client/`
- Both `pyproject.toml` and `package.json` declare lockstep version `1.0.0` matching the current backend; Plan 02's `sync_sdk_versions.py` will rewrite this on each regeneration to track `backend/openapi.json` `info.version`
- Generated subdirs (`sdks/python/geolens_sdk/`, `sdks/typescript/src/`) intentionally absent — Plan 02 creates them via the generators

**No blockers** for Plan 02. The `@geolens` npm scope claim is a deferred user action (CONTEXT.md D-16 publish workflow); it does NOT block development since Plan 02 only generates code, doesn't publish it.

## Self-Check: PASSED

- `sdks/python/pyproject.toml` — FOUND
- `sdks/python/.openapi-python-client.yaml` — FOUND
- `sdks/python/LICENSE` — FOUND
- `sdks/python/README.md` — FOUND
- `sdks/python/.gitignore` — FOUND
- `sdks/typescript/package.json` — FOUND
- `sdks/typescript/tsconfig.json` — FOUND
- `sdks/typescript/openapi-ts.config.ts` — FOUND
- `sdks/typescript/LICENSE` — FOUND
- `sdks/typescript/README.md` — FOUND
- `sdks/typescript/.gitignore` — FOUND
- Commit `059501a8` (Task 1) — FOUND
- Commit `7136f504` (Task 2) — FOUND

---
*Phase: 215-sdks-from-openapi*
*Completed: 2026-04-27*
