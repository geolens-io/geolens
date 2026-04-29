---
phase: 215-sdks-from-openapi
plan: 02
subsystem: infra
tags: [openapi, sdk, python, typescript, openapi-python-client, hey-api, makefile, drift-gate, openapi-3.1, defs-flatten]

# Dependency graph
requires:
  - phase: 215-01
    provides: scaffolded sdks/python and sdks/typescript directories with pinned generator config (openapi-python-client@0.28.3, @hey-api/openapi-ts@0.96.1, @hey-api/client-fetch@0.13.1) and lockstep version baseline 1.0.0
provides:
  - Makefile sdks/sdks-check/sdks-test/publish-sdks-py/publish-sdks-ts targets (one-shot regeneration + drift gate at the tooling level)
  - scripts/sync_sdk_versions.py (deterministic SDK version pin to backend/openapi.json info.version)
  - scripts/flatten_openapi_defs.py (OpenAPI 3.1 inline $defs flattener — generator-only intermediate at /tmp/openapi-flat.json)
  - sdks/python/geolens_sdk/ (622 generated Python files, 87,078 LOC, 20 API tag-modules, 385 model dataclasses)
  - sdks/typescript/src/client/ (16 generated TypeScript files, 23,471 LOC)
  - sdks/typescript/package-lock.json (committed lockfile for CI determinism)
  - sdks/python/geolens_sdk/py.typed (PEP 561 marker created via Makefile touch)
affects:
  - 215-03 (auth wrappers will be added alongside generated code; cp-stash pattern in Makefile already protects them across regeneration)
  - 215-04 (round-trip test imports from the generated Python + TypeScript packages)
  - 215-05 (docs/sdks.md must document the flatten preprocessor as part of the generation pipeline)
  - 218-future (Phase 218 audit should review flatten_openapi_defs.py invariants — the synthetic-name promotion logic protects against schema drift but adds one more moving part to the SDK pipeline)

# Tech tracking
tech-stack:
  added:
    - sha1-based deterministic synthetic naming (InlineDef_<base>_<sha1[:8]>) for promoted inline schemas
    - cp-stash Makefile idiom (RESEARCH §Pitfall 6 Option 1) protecting hand-written wrappers from --overwrite
  patterns:
    - "Generator-only intermediate file: backend/openapi.json snapshot is the contract source-of-truth (committed, immutable from this pipeline's POV); /tmp/openapi-flat.json is a transient intermediate consumed only by SDK generators. Preserves ROADMAP SC#3."
    - "Hash-comparison guard before flattening: every inline $defs.X must either match top-level components.schemas.X byte-for-byte OR be promoted under a deterministic synthetic name with rewritten title. Silent flattening is unsafe; the script sys.exit(1) on collisions."
    - "Makefile pipeline ordering: dump_openapi → flatten → cp-stash → generators → cp-restore → version-sync. Adding the flatten step between snapshot and generators isolates the workaround to the SDK pipeline without polluting the OpenAPI snapshot consumed by other tooling (CI openapi-check, frontend types, etc.)."

key-files:
  created:
    - scripts/sync_sdk_versions.py
    - scripts/flatten_openapi_defs.py
    - sdks/python/geolens_sdk/__init__.py
    - sdks/python/geolens_sdk/client.py
    - sdks/python/geolens_sdk/errors.py
    - sdks/python/geolens_sdk/types.py
    - sdks/python/geolens_sdk/py.typed
    - sdks/python/geolens_sdk/api/ (20 tag-subdirs, ~213 endpoint modules)
    - sdks/python/geolens_sdk/models/ (385 attrs-based dataclasses)
    - sdks/typescript/src/client/sdk.gen.ts
    - sdks/typescript/src/client/types.gen.ts
    - sdks/typescript/src/client/client.gen.ts
    - sdks/typescript/src/client/index.ts
    - sdks/typescript/src/client/core/ (8 runtime helper modules)
    - sdks/typescript/src/client/client/ (5 transport modules)
    - sdks/typescript/package-lock.json
  modified:
    - Makefile (+5 SDK targets; +.PHONY entries)
    - sdks/typescript/openapi-ts.config.ts (dropped deprecated `format: 'prettier'` key — prettier not in devDeps and the format option is being removed)

key-decisions:
  - "Implemented D-08: scripts/sync_sdk_versions.py reads backend/openapi.json info.version and writes verbatim to all three SDK metadata files (pyproject.toml, .openapi-python-client.yaml, package.json). Idempotent — second run is a no-op."
  - "Implemented D-12: Makefile sdks target mirrors openapi/openapi-check shape; sdks-check runs `make sdks` then `git diff --exit-code -- sdks/`."
  - "Implemented D-13: drift gate excludes hand-written files (auth.py, auth.ts, index.ts, READMEs, LICENSE) via :! pathspecs."
  - "RESEARCH-EXTENSION (mid-flight): added scripts/flatten_openapi_defs.py preprocessor to handle FastAPI/pydantic v2's OpenAPI 3.1 inline $defs emission. The committed backend/openapi.json snapshot stays untouched; the flatten script writes /tmp/openapi-flat.json that the SDK generators consume. This was an unanticipated finding — neither the Phase 215 RESEARCH document's Pitfall 1/2 nor the Phase 215 CONTEXT D-12 Makefile recipe accounted for it. See `Reconciliation Notes` below."
  - "Synthetic-promotion title rewrite: when an inline $defs schema differs from (or is missing from) top-level components.schemas, the flatten script promotes it under InlineDef_<base>_<sha1[:8]> AND rewrites its inner `title` to match. openapi-python-client derives class names from `title` rather than the schema key, so without the title rewrite the synthetic and original schemas would collapse to the same Python class and fail with `Attempted to generate duplicate models with name X`."
  - "py.typed (PEP 561 marker) created via Makefile `touch` step — openapi-python-client with `--meta none` doesn't emit it. Without this file, downstream typecheckers ignore the inline annotations."

patterns-established:
  - "OpenAPI 3.1 inline $defs flattening: any FastAPI+pydantic v2 backend that emits OpenAPI 3.1 will hit this. The flatten script is a reusable preprocessor — applicable to any consumer of the snapshot that struggles with nested $defs (frontend codegen, contract testing tools, etc.)."
  - "Generator-only intermediates: when a generator's quirk requires schema massaging, write a separate intermediate consumed only by the generator. NEVER mutate the canonical snapshot."
  - "Hash-comparison flatten guard: any tool that 'simplifies' a schema must verify byte-equality against the canonical definition before discarding the local copy, or promote under a deterministic synthetic name with collision-detection. Silent rewrites mask schema drift."

requirements-completed:
  - OCSDK-03
  - OCSDK-04

# Metrics
duration: 12m 10s
completed: 2026-04-27
---

# Phase 215 Plan 02: Makefile sdks targets + flatten preprocessor + first regen baseline Summary

**`make sdks` regenerates Python (622 files, 87k LOC) and TypeScript (16 files, 23k LOC) SDKs end-to-end from `backend/openapi.json`, bridged through a new `flatten_openapi_defs.py` preprocessor that resolves OpenAPI 3.1 inline `$defs` references — drift gate (`make sdks-check`) verified clean against committed baseline.**

## Performance

- **Duration:** 12m 10s
- **Started:** 2026-04-27T19:19:23Z
- **Completed:** 2026-04-27T19:31:33Z
- **Tasks:** 2
- **Files committed:** 643 in Task 2 commit (5 hand-written + 638 generated/lockfile/Makefile edits) + 1 in Task 1 commit (sync_sdk_versions.py)
- **Generated code volume:** 110,549 LOC across 638 files (Python 87,078 / TypeScript 23,471)

## Accomplishments

- `make sdks` is end-to-end functional: refreshes openapi.json → flattens $defs → cp-stash auth wrappers → runs both generators → restores wrappers → syncs versions
- `make sdks-check` is GREEN — verified by running it against the committed baseline, exit code 0
- All 4 version sources synchronized: `backend/openapi.json info.version === sdks/python/pyproject.toml [project].version === sdks/python/.openapi-python-client.yaml package_version_override === sdks/typescript/package.json .version === "1.0.0"`
- Python SDK has all 20 FastAPI tag-modules including the previously-broken `features/` and `ogc_features/` (which the original generator silently dropped due to `#/$defs/X` references)
- TypeScript SDK generated cleanly — no parser crashes
- `package-lock.json` committed (CI determinism + supply-chain mitigation per RESEARCH §Threat T-215-supplychain)
- `node_modules/` correctly NOT committed (gitignored at SDK package level from Plan 01)
- `auth.py`/`auth.ts`/`index.ts` correctly absent — Plan 03 will add them; cp-stash protection already wired

## Task Commits

Each task committed atomically:

1. **Task 1: Create scripts/sync_sdk_versions.py** — `76bc6e17` (feat)
2. **Task 2: Wire Makefile targets + first regeneration (with flatten preprocessor inserted mid-flight)** — `20d10a9b` (feat)

**Plan metadata commit:** pending (final commit captures this SUMMARY.md + STATE.md + ROADMAP.md updates)

## Files Created/Modified

### Created

- `scripts/sync_sdk_versions.py` — Deterministic version-sync script. Reads `backend/openapi.json info.version`, writes verbatim to `sdks/python/pyproject.toml [project].version`, `sdks/python/.openapi-python-client.yaml package_version_override`, and `sdks/typescript/package.json .version`. Idempotent. No timestamps, hashes, or environment-derived suffixes (RESEARCH §Pitfall 9).
- `scripts/flatten_openapi_defs.py` — OpenAPI 3.1 inline `$defs` preprocessor. Reads source spec, rewrites every `#/$defs/X` reference to `#/components/schemas/X`. Identical inline copies fold into the existing top-level entry. Non-matching inline copies (different shape OR missing from top-level) are promoted under deterministic `InlineDef_<base>_<sha1[:8]>` names with their inner `title` rewritten to match. Hash-collision guard exits non-zero rather than silently overwrite. Output to a generator-only intermediate (default `/tmp/openapi-flat.json`); the canonical `backend/openapi.json` snapshot is never modified.
- `sdks/python/geolens_sdk/__init__.py`, `client.py`, `errors.py`, `types.py`, `py.typed` — generated package skeleton + PEP 561 marker
- `sdks/python/geolens_sdk/api/` — 20 tag-subdirectories (admin, admin_embed_tokens, auth, config_ops, datasets, datasets_data, datasets_export, datasets_metadata, datasets_reupload, datasets_vrt, default, embed_tokens, features, maps, ogc_features, records, search, stac, stac_import, tiles)
- `sdks/python/geolens_sdk/models/` — 385 attrs-based dataclasses
- `sdks/typescript/src/client/sdk.gen.ts`, `types.gen.ts`, `client.gen.ts`, `index.ts` — generated SDK functions, types, transport
- `sdks/typescript/src/client/core/` — 8 runtime helper modules (queryKeySerializer, bodySerializer, types, auth, utils, pathSerializer, serverSentEvents, params)
- `sdks/typescript/src/client/client/` — 5 transport modules (client, types, utils, plus index)
- `sdks/typescript/package-lock.json` — npm lockfile (CI determinism)
- `.planning/phases/215-sdks-from-openapi/215-02-SUMMARY.md` — this file

### Modified

- `Makefile` — Added 5 SDK targets (sdks, sdks-check, sdks-test, publish-sdks-py, publish-sdks-ts) and added them to `.PHONY`. The `sdks` target's pipeline:
  1. `dump_openapi.py` (refresh snapshot)
  2. `flatten_openapi_defs.py --input backend/openapi.json --output /tmp/openapi-flat.json`
  3. cp-stash auth.py / auth.ts / index.ts to /tmp (no-op on first run)
  4. `uvx openapi-python-client@0.28.3 generate --path /tmp/openapi-flat.json ...`
  5. `touch sdks/python/geolens_sdk/py.typed` (PEP 561 marker)
  6. `cd sdks/typescript && npm install --silent && npx --yes @hey-api/openapi-ts@0.96.1 -i /tmp/openapi-flat.json`
  7. cp-restore auth.py / auth.ts / index.ts (no-op on first run)
  8. `sync_sdk_versions.py`
  Inline comments explain each step; future maintainers can read why the flatten step exists without leaving the file.
- `sdks/typescript/openapi-ts.config.ts` — Dropped deprecated `format: 'prettier'` key from `output`. Generator now emits readable code without invoking a postprocess formatter (prettier wasn't in devDeps; the deprecation warning + crash were both telling us to drop it).

## Decisions Made

See key-decisions in frontmatter. Highlights:

- **Synthetic-name title rewrite was non-obvious.** First attempt promoted inline schemas under `InlineDef_<base>_<hash>` and assumed that was sufficient. openapi-python-client's class-name derivation looks at the schema's inner `title` field, not the schema key, so two schemas with the same `title: "GeoJSONFeature"` collapsed to the same Python class. Fix: also rewrite the inner `title` to match the synthetic key. The flatten script's `_resolve_defs_entry()` now does this in Pass 1, and `_walk()` Pass 2 preserves the rewrite even after recursing.
- **PEP 561 marker via Makefile `touch`** rather than committing a 0-byte tracked file. Reasoning: the file is empty and content-stable; touching during regeneration ensures it always exists after `make sdks` and removes the maintenance burden of "remember to recommit if the wheel ever overwrites."
- **Generator-only intermediate path** is `/tmp/openapi-flat.json`. This is OS-temp territory; alternatives (a tracked `sdks/.intermediate/openapi-flat.json` file, an in-memory pipe) all add complexity without benefit. The Makefile pipeline always regenerates the intermediate before invoking generators, so consumers never see stale state.

## Reconciliation Notes

### Research extension: OpenAPI 3.1 inline `$defs` flattening (NEW finding, not in 215-RESEARCH.md)

**What we found mid-execution:** The first `make sdks` run hit a hard crash from `@hey-api/openapi-ts@0.96.1` and silent endpoint omissions from `openapi-python-client@0.28.3`. The root cause was OpenAPI 3.1 inline `$defs` blocks emitted by FastAPI/pydantic v2:

- Top-level: `components.schemas.OGCLink` (canonical, used elsewhere via `#/components/schemas/OGCLink`)
- Inline at endpoint schemas: `paths./collections/{dataset_id}/items.get.responses.200.content.application/geo+json.schema.$defs.OGCLink` (with `$ref: "#/$defs/OGCLink"` resolving to the inline copy)

`@hey-api/json-schema-ref-parser` crashed with `TypeError: Cannot read properties of null (reading 'OGCLink')` because its bundler doesn't traverse `$defs`. `openapi-python-client` warned and silently omitted the affected endpoints.

**Audit of the source spec:**

| Inline schema name | Inline `$defs` count | Status vs top-level |
|---|---|---|
| `OGCLink` | 2 | Identical to top-level — safe to fold |
| `GeoJSONGeometry` | 6 | Identical to top-level — safe to fold |
| `GeoJSONFeature` | 1 | DIFFERS from top-level (different `properties.geometry` shape: inline uses `$ref`, top-level uses `additionalProperties: true`) — must promote |
| `Link` | 1 | MISSING from top-level entirely — must promote |

10 inline `$ref`s rewritten total; 7 inline `$defs` blocks discarded; 2 schemas promoted (`InlineDef_GeoJSONFeature_afaebacb`, `InlineDef_Link_900f1c94`).

**What 215-RESEARCH.md missed:** Pitfall 1 (attrs vs pydantic) and Pitfall 2 (verbose operationId names) are both real but unrelated. RESEARCH §"Verified pattern: openapi-python-client config + invocation" assumed the standard invocation against `backend/openapi.json` would work — it nearly did, but the OpenAPI 3.1 nested `$defs` shape from pydantic v2 was not considered. Future SDK-from-FastAPI phases should bake the flatten step into the recipe upfront.

**Recommendation for Phase 218 audit:** Review `scripts/flatten_openapi_defs.py` for:
1. Soundness of the synthetic-name collision detection (sha1 has no known practical collisions for our scale, but the script asserts byte-equality before reusing a name)
2. Whether the title-rewrite logic should generalize to other generator-quirk fields (`description`, `xml.name`, etc.) if downstream phases hit similar issues
3. Whether to upstream the flatten step into `dump_openapi.py` (currently a strict NO — the snapshot must stay as FastAPI emits it for `openapi-check` correctness; the flatten step is generator-specific massaging)

### Other reconciliation: openapi-ts.config.ts `format` key removal

The Plan 01 SUMMARY shows the config was created with `format: 'prettier'`. That key is deprecated in `@hey-api/openapi-ts@0.96.1` (warning printed) AND crashed because prettier wasn't in devDeps. Removing it produces clean output; downstream consumers can run their own formatter on import if they care about style.

## Verification

Plan-level verification block:

```text
test -f scripts/sync_sdk_versions.py                                          PASS
test -f scripts/flatten_openapi_defs.py                                       PASS
grep -E '^(sdks|sdks-check|sdks-test|publish-sdks-py|publish-sdks-ts):' Makefile | wc -l == 5  PASS
test -f sdks/python/geolens_sdk/__init__.py                                   PASS
test -f sdks/python/geolens_sdk/client.py                                     PASS
test -f sdks/python/geolens_sdk/py.typed                                      PASS
test -d sdks/python/geolens_sdk/api                                           PASS
test -d sdks/python/geolens_sdk/models                                        PASS
test -f sdks/typescript/src/client/sdk.gen.ts                                 PASS
test -f sdks/typescript/src/client/types.gen.ts                               PASS
test -f sdks/typescript/package-lock.json                                     PASS
test ! -f sdks/python/geolens_sdk/auth.py                                     PASS
test ! -f sdks/typescript/src/auth.ts                                         PASS
grep -q 'class AuthenticatedClient' sdks/python/geolens_sdk/client.py         PASS
git status --short -- sdks/typescript/node_modules/ (empty)                   PASS
make sdks-check (exit 0)                                                      PASS
All 4 version sources match (1.0.0)                                           PASS
```

End-to-end idempotency: `make sdks-check` exit code 0 against committed baseline confirms Pitfall 9 closed at the system level.

## Deviations from Plan

The plan was executed as written for Task 1. Task 2 hit a generator-quirk wall that required a planner checkpoint (Rule 4 architectural decision); the planner approved Option A (flatten preprocessor) and execution resumed with three additional inline fixes (Rules 1, 2).

### Architectural decision (Rule 4 — checkpoint resolved by planner)

**1. [Rule 4 - Architectural] OpenAPI 3.1 inline `$defs` blocking both generators**

- **Found during:** Task 2 first `make sdks` run
- **Issue:** `@hey-api/openapi-ts@0.96.1` crashed (`TypeError: Cannot read properties of null (reading 'OGCLink')`); `openapi-python-client@0.28.3` silently omitted 8 OGC/features endpoints. Root cause: FastAPI+pydantic v2 emits OpenAPI 3.1 with nested `$defs` blocks inside endpoint schemas; both generators choke on `#/$defs/X` references.
- **Why architectural:** Adding a new file (`flatten_openapi_defs.py`) and modifying the Makefile pipeline shape (insert preprocessor between snapshot and generators) was outside the plan's described action blocks. Three viable paths existed (preprocessor, force OpenAPI 3.0 emission, switch TS generator) — needed planner judgment.
- **Resolution:** Planner approved Option A (preprocessor). Constraint: must NOT modify the committed `backend/openapi.json` snapshot — preserved by writing to `/tmp/openapi-flat.json` and pointing both generators at the intermediate via CLI flag.
- **Files added/modified:** scripts/flatten_openapi_defs.py (new), Makefile (sdks target updated to invoke flatten step)
- **Committed in:** `20d10a9b` (Task 2 commit)

### Auto-fixed issues (Rules 1-3)

**2. [Rule 1 - Bug] Synthetic-name title-collision in Python generator**

- **Found during:** Task 2 second `make sdks` run (after flatten preprocessor added)
- **Issue:** Initial flatten implementation promoted inline schemas under `InlineDef_<base>_<hash>` names. `openapi-python-client@0.28.3` derives class names from the schema's inner `title` field, not the schema key, so `InlineDef_GeoJSONFeature_<hash>` (whose inner `title` was still `"GeoJSONFeature"`) collided with the top-level `GeoJSONFeature` class. Generator errored: `Attempted to generate duplicate models with name "GeoJSONFeature"`.
- **Fix:** `_resolve_defs_entry()` now overwrites the inner `title` to match the synthetic key. `_walk()` Pass 2 preserves the title rewrite even after recursing into the schema body.
- **Files modified:** scripts/flatten_openapi_defs.py
- **Verification:** Re-ran `make sdks` — Python generator emitted all 213 endpoints across 20 tag-modules with no duplicate-name errors.
- **Committed in:** `20d10a9b` (Task 2 commit)

**3. [Rule 3 - Blocking] `format: 'prettier'` in openapi-ts.config.ts crashed TS generator**

- **Found during:** Task 2 first `make sdks` run (TS generator stage, after the flatten preprocessor was added)
- **Issue:** `@hey-api/openapi-ts@0.96.1` printed `\`format\` is deprecated` warning then crashed with `Post-processor "Prettier" failed to run: spawnSync prettier ENOENT`. Plan 01 had pre-configured the post-process step but didn't add prettier to devDeps. The deprecated key would have failed in a future minor version anyway.
- **Fix:** Removed `format: 'prettier'` from `output` block in `sdks/typescript/openapi-ts.config.ts`. Added a comment explaining the choice and noting that drift-gate equality doesn't depend on formatting policy.
- **Files modified:** sdks/typescript/openapi-ts.config.ts
- **Verification:** `make sdks` produced 16 TS files with `[Job 1] Done!` — no postprocessor errors.
- **Committed in:** `20d10a9b` (Task 2 commit)

**4. [Rule 2 - Missing critical] PEP 561 `py.typed` marker absent**

- **Found during:** Task 2 verification (`test -f sdks/python/geolens_sdk/py.typed` failed)
- **Issue:** Plan 02 acceptance criteria require `sdks/python/geolens_sdk/py.typed` (PEP 561 marker so typecheckers consume the inline annotations). `openapi-python-client@0.28.3` with `--meta none` doesn't emit it. Without this marker, mypy/pyright on consumers' machines treats the SDK as untyped.
- **Fix:** Added `touch sdks/python/geolens_sdk/py.typed` step in the Makefile `sdks` target after the Python generator runs. Idempotent (touch updates mtime but doesn't change content; git diff sees no change for a 0-byte file).
- **Files modified:** Makefile
- **Verification:** `test -f sdks/python/geolens_sdk/py.typed` passes; file is tracked (committed); `make sdks` re-runs continue to pass `make sdks-check` (idempotency preserved).
- **Committed in:** `20d10a9b` (Task 2 commit)

---

**Total deviations:** 1 architectural (Rule 4 — planner-approved) + 3 auto-fixed (1 bug, 1 blocking, 1 missing-critical)
**Impact on plan:** Plan's outcome shape preserved (drift gate works, both generators produce baseline output, version pins are deterministic). Pipeline gained one extra step (flatten preprocessor) — fully documented in Makefile inline comments and SUMMARY's research-extension note. No scope creep into Plan 03/04/05.

## Issues Encountered

- **Two regeneration cycles wasted before the title-collision fix landed.** The initial synthetic-name design was incomplete (didn't account for `title`-driven class-name derivation). Caught by the next `make sdks` run, which still failed loudly. Net cost: ~3 minutes of regen time.
- **Ruff cache fluctuation between runs.** `.ruff_cache/0.15.12/<hash>` content changes every time the post-hooks run — but `.ruff_cache/` is gitignored at the SDK package level (Plan 01), so `git diff --exit-code -- sdks/` doesn't see it. Drift gate is still safe. Documented for future-me.

## User Setup Required

None — the v13.1 SDK pipeline runs entirely on tooling already installed (uv 0.10.3, node v25.6.1, npm 11.9.0). The first publish (Plan 04+ deferred manual action per CONTEXT D-16) requires user-managed `UV_PUBLISH_TOKEN` / `NPM_TOKEN` GitHub secrets, but that's out of scope for Plan 02.

## Next Phase Readiness

**Ready for Plan 03 (auth wrappers):**
- `sdks/python/geolens_sdk/client.py` exports `Client` and `AuthenticatedClient` — Plan 03's hand-written `auth.py` can wrap them.
- `sdks/typescript/src/client/client.gen.ts` exports the fetch-flavored client — Plan 03's hand-written `auth.ts` can configure it.
- Makefile `sdks` target's cp-stash pattern (lines 53-55, 64-66) already protects `auth.py`, `auth.ts`, `index.ts` across regeneration. Plan 03 just needs to add the wrapper files; the next `make sdks` will preserve them automatically.
- Drift gate `:!` exemptions (Makefile lines 72-74) already exclude the wrapper files, so Plan 03's hand-written code won't trip the drift check.

**Ready for Plan 04 (round-trip test + CI):**
- Generated Python SDK exposes `geolens_sdk.api.search.search_datasets_endpoint_search_datasets__get`, `geolens_sdk.api.datasets.get_single_dataset_datasets__dataset_id__get`, etc. — round-trip test can import these.
- TypeScript SDK exposes `searchDatasetsEndpointSearchDatasetsGet` and friends from `sdks/typescript/src/client/sdk.gen.ts` — round-trip can import these.
- `make sdks-test` Makefile target is wired (currently a stub that runs the round-trip test Plan 04 will create).
- `make sdks-check` is the CI gate; Plan 04 just needs to invoke it from `.github/workflows/`.

**Ready for Plan 05 (docs/sdks.md):**
- The Makefile's inline comments are the closest thing to authoritative pipeline docs. Plan 05 should lift them into `docs/sdks.md` so external consumers don't need to read the Makefile.
- The flatten preprocessor's existence and rationale are subtle — `docs/sdks.md` MUST mention it (not just "we run two generators") so future contributors don't re-discover the OpenAPI 3.1 inline `$defs` problem from scratch.

**No blockers** for downstream plans. The 8 previously-omitted endpoints (OGC features + GeoJSON CRUD) are now present in the Python SDK; ROADMAP SC#1 round-trip test will be able to exercise the full advertised surface.

## Threat Flags

None — no new attack surface introduced. All threat-register items from PLAN-02 are mitigated as designed:

- T-215-02-01 (Tampering — generator supply chain): mitigated. Pinned versions in Makefile; `package-lock.json` committed; `uvx` ephemeral environments.
- T-215-02-02 (Tampering — drift gate bypass via nondeterminism): mitigated. `make sdks-check` exits 0 immediately after `make sdks`; sync script has zero nondeterministic inputs.
- T-215-02-03 (Tampering — auth wrapper deletion via --overwrite): mitigated by cp-stash pattern. Plan 03 will validate empirically when `auth.py`/`auth.ts` exist.
- T-215-02-04 (Information disclosure — node_modules committed): mitigated. `node_modules/` not staged; `.gitignore` rule from Plan 01 holds.
- T-215-02-05 (Information disclosure — tokens leaked in published artifact): not exercised in this plan (no publish). `package.json` `files` whitelist + `pyproject.toml` packages list both restrict tarball contents.
- T-215-02-06 (Tampering — version-sync writes stale value on malformed openapi.json): mitigated. Script `sys.exit(1)` if `openapi.json` missing or `info.version` absent.
- T-215-02-07 (EoP — uvx/npx as root): accepted (out of Phase 215 scope).

**New mitigations contributed:**

- Flatten preprocessor's hash-comparison guard (sys.exit(1) on inline-vs-top-level shape mismatch when neither matching nor synthetic-named) prevents silent schema drift from ever reaching the SDK generators. Adds one new safety boundary at the OpenAPI-snapshot → SDK-generator interface.

## Self-Check: PASSED

- `scripts/sync_sdk_versions.py` — FOUND
- `scripts/flatten_openapi_defs.py` — FOUND
- `sdks/python/geolens_sdk/client.py` — FOUND
- `sdks/python/geolens_sdk/py.typed` — FOUND
- `sdks/typescript/src/client/sdk.gen.ts` — FOUND
- `sdks/typescript/package-lock.json` — FOUND
- `.planning/phases/215-sdks-from-openapi/215-02-SUMMARY.md` — FOUND
- Commit `76bc6e17` (Task 1) — FOUND
- Commit `20d10a9b` (Task 2) — FOUND

---
*Phase: 215-sdks-from-openapi*
*Completed: 2026-04-27*
