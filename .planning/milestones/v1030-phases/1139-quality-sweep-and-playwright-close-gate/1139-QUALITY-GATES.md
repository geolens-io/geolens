# 1139 Quality Gates

**Run date:** 2026-05-28
**Branch:** codex/builder-polish-walkthrough
**Purpose:** QA-03 — deterministic headless close-gate for v1030 milestone.

---

## Results Table

| Gate | Command | Exit Code | Verdict | Notes |
|------|---------|-----------|---------|-------|
| typecheck | `cd frontend && npm run typecheck` | 0 | PASS | `tsc -b --noEmit` — zero errors |
| vitest (full) | `cd frontend && npm run test -- --run` | 0 | PASS | 2486/2486 tests passed, 235/235 files |
| lint | `cd frontend && npm run lint` | 0 | PASS | 0 errors, 1 intentional warning (use-filtered-feature-count.ts:74 — documented partial dep) |
| e2e:smoke:builder | `npm run e2e:smoke:builder` (repo root) | 0 | PASS | 26/26 — builder.spec / builder-styling.spec / builder-v1-5.spec all green |
| test:i18n | `cd frontend && npm run test:i18n` | 0 | PASS | 2/2 resource parity tests passed |
| check:i18n:changed | `cd frontend && npm run check:i18n:changed` | 0 | PASS | "No locale file changes detected." |

**i18n 2/2:** both `test:i18n` and `check:i18n:changed` exit 0.

---

## Pre-Existing Failure Allowlist

Two pre-existing failures (reproduce on baseline `736cffca`) are excluded from `e2e:smoke:builder` by design:
- `e2e/accessibility.spec.ts:151` (axe `aria-required-children` + `nested-interactive`)
- `e2e/builder-unified-stack.spec.ts:193` (drag-reorder picks basemap-group; `disabled.droppable` contract)

Neither spec is in the `e2e:smoke:builder` subset (`builder.spec.ts`, `builder-styling.spec.ts`, `builder-v1-5.spec.ts`). Neither appeared in the smoke run. No allowlist entries were needed for this run.

---

## Failure Classification

### Auto-fixed Issues (Rule 1 — Bug / Rule 2 — Missing Critical)

Three categories of lint failures and one category of test failures were found from v1030 work and fixed inline per deviation Rule 1:

**Lint Fixes (commit `fdb0848d`):**

1. **`ChatPanel.tsx:878,886` — `jsx-a11y/no-redundant-roles`**
   - `<ul role="list">` and `<li role="listitem">` have redundant explicit roles.
   - Fix: removed `role="list"` and `role="listitem"` attributes.
   - Source: Phase 1135 AI staging chip list introduced during confirm-before-apply work.

2. **`RasterEditor.test.tsx:34` — `jsx-a11y/no-redundant-roles`**
   - `<input type="range" role="slider">` has a redundant explicit role.
   - Fix: removed `role="slider"` from the test mock element.
   - Source: Phase 1136 RasterEditor tests.

3. **`FeaturePopup.tsx:267` — `@next/next/no-img-element` rule definition not found**
   - eslint-disable comment referenced a Next.js rule that does not exist in this Vite/React project config.
   - Fix: removed the invalid disable comment (the `<img>` element has no rule to suppress in this project).
   - Source: Phase 1138 popup URL/media handling work.

4. **`FeaturePopup.tsx:292` — `jsx-a11y/media-has-caption`**
   - `<video>` element without a `<track>` element for captions.
   - Fix: added `{/* eslint-disable-next-line jsx-a11y/media-has-caption */}` with a comment explaining user-sourced URL context.
   - Source: Phase 1138 popup video rendering.

5. **`SharePanel.tsx:661`, `SharePanel.test.tsx:569,592` — unused eslint-disable directives**
   - `react-hooks/exhaustive-deps` and `@typescript-eslint/no-explicit-any` suppression comments no longer needed.
   - Fix: removed the three stale disable comments.
   - Source: Phase 1137 share panel and embed token work.

**Test Mock Fixes (commit `fdb0848d`):**

6. **`ViewerMap.basemap-config.test.tsx` — missing `useBranding` export in mock**
   - 12 tests failed with: `[vitest] No "useBranding" export is defined on the "@/hooks/use-settings" mock`
   - `ViewerMap.tsx` gained `useBranding()` in Phase 1137 (SHARE-07), but the existing basemap-config test mock was not updated.
   - Fix: added `useBranding: () => ({ data: undefined })` to the `vi.mock('@/hooks/use-settings')` factory.

7. **`ViewerMap.branding.test.tsx:93` — incorrect mock value for branding test case (1)**
   - Test case (1) mocked `useBranding` with `{ data: undefined }` but expected the branding overlay to render.
   - The `showBranding` condition in `ViewerMap.tsx` requires `branding !== undefined` (anti-flash guard for enterprise users: gate shows overlay only after branding has loaded).
   - `data: undefined` = loading state → `showBranding = false` → overlay suppressed.
   - Fix: changed mock to `{ data: { show_badge: true } }` to represent a fully-loaded community edition state.

**Remaining Warning (intentional, not a failure):**

- `use-filtered-feature-count.ts:74` — `react-hooks/exhaustive-deps` warns on missing `layer` dep.
  - This is intentional: the comment documents that watching only `layer?.id` + `layer?.filter` (not the full `layer` object) prevents 60fps `queryRenderedFeatures` storm during slider drags.
  - Exits 0. Retained as a warning (not suppressed with a disable comment) to remain visible for future reviewers.

---

## QA-03 verdict: GREEN

All six checks exit 0. All failures were from v1030 in-flight work (introduced during Phases 1135-1138) and fixed inline per deviation Rule 1. No pre-existing allowlist entries needed. No new regressions.
