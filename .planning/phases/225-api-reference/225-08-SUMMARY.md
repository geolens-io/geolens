---
phase: 225-api-reference
plan: 08
subsystem: infra
tags: [starlight, links-validator, astro, build, ci]

# Dependency graph
requires:
  - phase: 225-api-reference
    plan: 03
    provides: starlight-openapi plugin registration and plugins[] array
  - phase: 225-api-reference
    plan: 04
    provides: auth.mdx with forward-refs to /guides/admin/** (probe target)
provides:
  - starlight-links-validator@0.23.0 pinned and registered as Starlight plugin
  - exclude allowlist tolerating Phase 226/227 forward-refs (/guides/admin/**, /guides/user/**, /guides/quickstart/**)
  - npm run build fails on broken internal links (gate live, proven by negative test)
affects: [225-09, 226, 227, 228]

# Tech tracking
tech-stack:
  added: [starlight-links-validator@0.23.0]
  patterns:
    - Validator registered as Starlight plugin (NOT top-level Astro integration) so it runs after all plugins emit routes
    - exclude globs scoped to specific phase paths, commented with phase number — Phase 226/227 must remove matching entries when landing content
    - starlight-openapi generated routes (/guides/api/operations/**) are not in Starlight page registry — do not link to them from hand-authored MDX; use sidebar for navigation

key-files:
  created: []
  modified:
    - getgeolens.com/docs/package.json
    - getgeolens.com/docs/package-lock.json
    - getgeolens.com/docs/astro.config.mjs
    - getgeolens.com/docs/src/content/docs/guides/api/index.mdx
    - getgeolens.com/docs/src/content/docs/index.mdx

key-decisions:
  - "starlightLinksValidator placed AFTER starlightOpenAPI in plugins[] so the validator sees all routes the openapi plugin emits before validation runs"
  - "exclude: 3 scoped globs only — /guides/admin/**, /guides/user/**, /guides/quickstart/** — no blanket /guides/** exclude so the gate validates all current API content"
  - "starlight-openapi generated routes not added to exclude; instead, hand-authored MDX was fixed to not link to /guides/api/operations/ paths (they aren't in Starlight's page registry)"
  - "Probe format: plain MDX link [text](/path) not HTML comment (<!-- -->) — MDX does not support HTML comments; use {/* */} or omit comment"

patterns-established:
  - "Phase-labeled exclude globs: each entry carries a // Phase NNN comment so maintainers know when to remove it"
  - "No links from hand-authored MDX to starlight-openapi generated /operations/ routes; sidebar is the navigation entry point for tag pages"

requirements-completed: [CI-01]

# Metrics
duration: 15min
completed: 2026-04-25
---

# Phase 225 Plan 08: Links Validator Summary

**starlight-links-validator@0.23.0 installed as Starlight plugin with phase-scoped exclude allowlist; gate proven live by negative test (probe link broke build, restore gave clean build)**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-25T08:13:00Z
- **Completed:** 2026-04-25T08:17:15Z
- **Tasks:** 3 (Task 3 is verification-only, no commit)
- **Files modified:** 5 (across getgeolens.com repo)

## Accomplishments

- starlight-links-validator@0.23.0 installed with exact pin (no caret/tilde)
- Registered as Starlight plugin in `plugins[]` alongside starlightOpenAPI
- exclude allowlist: `/guides/admin/**` (Phase 227), `/guides/user/**` (Phase 227), `/guides/quickstart/**` (Phase 226)
- Negative test confirmed gate is live: probe link `/guides/__GSD_LINK_PROBE_NEVER_EXISTS__` caused build to fail with validator error; auth.mdx restored cleanly
- Final `npm run build` exits 0 with 237 pages built

## Negative Test Outcome

Probe injected:
```
[__GSD_LINK_PROBE__](/guides/__GSD_LINK_PROBE_NEVER_EXISTS__)
```

Validator error during probe build:
```
╭─ guides/api/auth.mdx
·
120 | /guides/__GSD_LINK_PROBE_NEVER_EXISTS__
·                                          ╰── invalid link

╭─                               ─╮
· Found 1 invalid link in 1 file. ·
╰─                               ─╯
[AstroUserError] Links validation failed.
```

Build exit code: non-zero (as expected). Gate is live.

auth.mdx was restored via `git checkout HEAD -- src/content/docs/guides/api/auth.mdx` — zero bytes changed against Plan 04 commit.

## Task Commits

1. **Task 1: Install starlight-links-validator@0.23.0** — `d8961fb` (chore)
2. **Task 2: Register plugin + Rule 1 auto-fixes** — `3eb8051` (feat)
3. **Task 3: Negative test** — no commit (verification-only, probe removed before commit)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `getgeolens.com/docs/package.json` — starlight-links-validator: "0.23.0" added
- `getgeolens.com/docs/package-lock.json` — 9 packages added for validator
- `getgeolens.com/docs/astro.config.mjs` — import + starlightLinksValidator({exclude:[...]}) added to plugins[]
- `getgeolens.com/docs/src/content/docs/index.mdx` — /guides/install → /guides/quickstart/ (Rule 1 fix)
- `getgeolens.com/docs/src/content/docs/guides/api/index.mdx` — removed broken /guides/api/operations/tags/ link from Endpoints by Tag card (Rule 1 fix)

## Decisions Made

- starlightLinksValidator placed AFTER starlightOpenAPI in plugins[] — ensures validator sees all routes emitted by the openapi plugin
- No `/guides/api/operations/**` exclude added — instead, hand-authored MDX was fixed to not link to starlight-openapi generated routes (they aren't in Starlight's page registry)
- 3 exclude globs only, each scoped to a specific phase — no blanket `/guides/**` that would silence the gate

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed broken /guides/install link in index.mdx**
- **Found during:** Task 2 (first build run with validator active)
- **Issue:** `index.mdx` linked to `/guides/install` which doesn't exist; quickstart content will live at `/guides/quickstart/`
- **Fix:** Changed link to `/guides/quickstart/` (covered by the Phase 226 exclude glob)
- **Files modified:** `docs/src/content/docs/index.mdx`
- **Verification:** Build passed after fix
- **Committed in:** `3eb8051` (Task 2 commit)

**2. [Rule 1 - Bug] Removed broken /guides/api/operations/tags/ link from guides/api/index.mdx**
- **Found during:** Task 2 (first build run)
- **Issue:** The "Endpoints by Tag" Card linked to `/guides/api/operations/tags/` — no index page exists at that path. Tag pages (e.g., `/guides/api/operations/tags/datasets`) ARE built by starlight-openapi but are NOT registered in Starlight's page manifest, so the validator cannot validate them.
- **Fix:** Removed the hyperlink from the card; added sidebar navigation note. No `/guides/api/operations/**` exclude added (would silently bypass all operation link validation).
- **Files modified:** `docs/src/content/docs/guides/api/index.mdx`
- **Verification:** Build passed after fix, validator found no further issues
- **Committed in:** `3eb8051` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs — broken links in prior-plan content)
**Impact on plan:** Both fixes required to achieve clean build with validator active. No scope creep.

**Note for MDX probe format:** HTML comments (`<!-- -->`) are NOT valid MDX. When writing probes in MDX files, use plain links `[text](/path)` or JSX comments `{/* */}`. The plan's suggested probe format with HTML comment was auto-adapted.

## Phase 226 / 227 Maintainer Notes

When landing Phase 226 (Quickstart) and Phase 227 (Admin/User guides), remove the corresponding exclude glob in `astro.config.mjs`:

| Phase | Content path | Exclude glob to remove |
|-------|-------------|------------------------|
| 226 | `/guides/quickstart/**` | `'/guides/quickstart/**', // Phase 226` |
| 227 | `/guides/admin/**` | `'/guides/admin/**', // Phase 227` |
| 227 | `/guides/user/**` | `'/guides/user/**', // Phase 227` |

Removing the glob in the same PR that adds the content causes the validator to START checking those links — which is the desired Phase 227/226 behavior.

## Issues Encountered

- First build attempt revealed 2 pre-existing broken links in prior-plan content (Plans 05 and 06). Both were Rule 1 auto-fixes — see Deviations above.
- starlight-openapi generated routes are not in Starlight's page registry. Links to `/guides/api/operations/**` from hand-authored MDX will always fail the validator. The correct pattern is: use the sidebar for operation/tag navigation; don't hard-link to generated routes from MDX.

## Next Phase Readiness

- Phase 225-09 (route middleware / canonical URL fix) can proceed — astro.config.mjs is structured and ready for `routeMiddleware:` addition
- Phase 226 (Quickstart) and Phase 227 (Admin/User) must remove their respective exclude globs when landing content
- Phase 228 (robots.txt flip) should verify exclude list is empty before flipping robots meta tag

---
*Phase: 225-api-reference*
*Completed: 2026-04-25*
