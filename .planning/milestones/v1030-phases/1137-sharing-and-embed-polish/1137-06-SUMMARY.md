---
phase: 1137-sharing-and-embed-polish
plan: "06"
subsystem: ui
tags: [share, iframe-preview, pitfall-7, sec-07, tdd]

requires:
  - phase: 1137-05
    provides: expiration preset Select (SharePanel.tsx stable after Plans 04+05)

provides:
  - "EmbedPreviewPane subcomponent: collapsible iframe preview with 8s timeout fallback"
  - "inflightEmbedCreate ref guard (Pitfall #7): two concurrent maybeCreateEmbedToken -> exactly 1 POST"
  - "7 new SHARE-03 + Pitfall #7 regression tests in SharePanel.test.tsx"
  - "6 new i18n keys in en/de/es/fr builder.json (iframePreviewTitle/Toggle/ErrorTitle/ErrorBody/Reload/SandboxNote)"

affects:
  - "Plan 07 (MCP smoke): SharePanel.tsx is now feature-complete for Phase 1137"

tech-stack:
  added: []
  patterns:
    - "EmbedPreviewPane: subcomponent-inside-file pattern for keeping ShareDialog readable"
    - "inflightEmbedCreate ref: single-flight Promise guard for concurrent mutation dedupe (mirrors ChatPanel.tsx inflightRef)"
    - "8-second onLoad timeout: useEffect timer reset on each reloadKey increment"
    - "Opacity-swap loading pattern: iframe opacity-0 until onLoad, then opacity-100 (no layout shift)"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/SharePanel.tsx
    - frontend/src/components/builder/__tests__/SharePanel.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "EmbedPreviewPane requires embedTokenRaw (not just rawShareToken) — preview src needs et= param; gate is rawShareToken && embedTokenRaw"
  - "inflightEmbedCreate ref wraps createEmbedToken.mutateAsync promise directly; concurrent callers await the same promise, secondary callers swallow thrown error silently"
  - "iframeSandboxNote left English-identical in all 4 locales — technical security note, brand-style untranslated"
  - "Tests use hasNonPublic:true for iframe pane tests — embedTokenRaw set during handleGetShareLink only when has_non_public is true"

requirements-completed:
  - SHARE-03

duration: 342s
completed: 2026-05-27
---

# Phase 1137 Plan 06: SharePanel iframe Preview Pane + inflightEmbedCreate Race Ref Summary

**Collapsible embed-preview iframe pane (sandbox="allow-scripts" only, SEC-07) + inflightEmbedCreate ref deduplicate concurrent embed-token mutations (Pitfall #7)**

## Performance

- **Duration:** ~6 min (342s)
- **Started:** 2026-05-27T23:53:11Z
- **Completed:** 2026-05-27T23:59:53Z
- **Tasks:** 4 (TDD RED + Pitfall #7 GREEN + SHARE-03 GREEN + i18n)
- **Files modified:** 6

## Accomplishments

- `EmbedPreviewPane` subcomponent added to `SharePanel.tsx`:
  - Collapsible disclosure toggle (ChevronRight rotating to rotate-90, base 400 weight, `text-muted-foreground`)
  - Iframe with `sandbox="allow-scripts"` ONLY (SEC-07 / M-70 hard invariant), `loading="lazy"`, `title` from i18n
  - Loading state: Loader2 spinner overlay until `onLoad` fires
  - Error state: 8-second `useEffect` timeout → AlertCircle + "Preview unavailable" + solution path + Reload button (increments `reloadKey`)
  - Security indicator footer: Shield icon + `sandbox="allow-scripts" only — SEC-07 contract`
  - Gate: `hasShareToken && rawShareToken && embedTokenRaw` (preview needs `et=` param in src)
- `inflightEmbedCreate` ref declared in `ShareDialog`:
  - `useRef<Promise<{ raw_token: string }> | null>(null)`
  - Wraps `createEmbedToken.mutateAsync` call: concurrent callers await the same in-flight promise
  - `finally` block clears ref on both success and failure
  - JSDoc documents Pitfall #7 contract + mirror to ChatPanel.tsx inflightRef (v1010.2)
- 7 new regression tests (TDD RED→GREEN verified)
- 6 new i18n keys in all 4 locales; test:i18n 2/2 PASS

## Task Commits

1. **Task 1 (RED)** — `fd346ae3` — `test(1137-06): add failing SHARE-03 iframe-pane + Pitfall #7 race tests (RED)`
2. **Task 2 (GREEN — Pitfall #7)** — `127eee84` — `feat(1137-06): implement inflightEmbedCreate ref guard (Pitfall #7 GREEN)`
3. **Task 3 (GREEN — SHARE-03)** — `997395ff` — `feat(1137-06): add SHARE-03 embed-preview iframe pane (GREEN)`
4. **Task 4 (i18n)** — `8eeea584` — `chore(1137-06): add SHARE-03 iframe preview i18n keys to all 4 locales`

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED — 7 tests fail | `fd346ae3` | PASS |
| GREEN — 32 tests pass | `997395ff` | PASS |

## Pitfall #7 — inflightEmbedCreate Contract

```
inflightEmbedCreate ref location: SharePanel.tsx (inside ShareDialog component)
Declaration: const inflightEmbedCreate = useRef<Promise<{ raw_token: string }> | null>(null);
```

**Guard logic:** `maybeCreateEmbedToken()` checks `inflightEmbedCreate.current` before creating a new promise. If non-null, the caller awaits the existing promise and returns — no second `mutateAsync` fires. The `finally` block clears the ref on both success and failure.

**Docstring text (abbreviated):**
> Pitfall #7 contract: deduplicates concurrent invocations via inflightEmbedCreate ref. Two callers racing through this function share the same in-flight promise instead of firing parallel createEmbedToken mutations that would both succeed and orphan one of the resulting tokens in the DB. Mirror of ChatPanel.tsx inflightRef pattern lifted in v1010.2.

## HARD INVARIANT Verification

| Invariant | Grep result | Status |
|-----------|-------------|--------|
| `sandbox="allow-scripts"` occurrences | 4 total (line 71 snippet fn, line 563 SEC-07 comment, line 568 JSX attr, line 596 i18n defaultValue) | PASS — 2 functional, 2 comment/string |
| `allow-same-origin` occurrences | 3 total (all comment-only: lines 44-45 docstring, line 563 NEVER comment) | PASS — 0 attribute uses |
| `data-testid="share-preview-iframe"` | 1 | PASS |
| `BuilderActionSource` = 0 | 0 | PASS |
| `SHARE-08 / og_image_uri` = 0 | 0 | PASS (DEFER respected) |

## 8-Second Timeout Rationale

Browsers do not reliably fire `onerror` on cross-origin sandboxed iframes for HTTP errors. The `onLoad` event fires even for error pages (the iframe page loaded — it just rendered an error). Rather than relying on `onerror`, the implementation uses `useEffect` with a `setTimeout(8000)` that fires `setErrored(true)` if `onLoad` has not fired. Clicking "Reload" increments `reloadKey` (forcing iframe re-mount) and resets the timer.

## i18n Keys Added

| Key | en | de | es | fr |
|-----|-----|-----|-----|-----|
| `share.iframePreviewTitle` | "Map embed preview" | "Karten-Einbettungsvorschau" | "Vista previa del mapa incrustado" | "Aperçu de la carte intégrée" |
| `share.iframePreviewToggle` | "Preview" | "Vorschau" | "Vista previa" | "Aperçu" |
| `share.iframeErrorTitle` | "Preview unavailable" | "Vorschau nicht verfügbar" | "Vista previa no disponible" | "Aperçu indisponible" |
| `share.iframeErrorBody` | "Check that the embed token is valid..." | translated | translated | translated |
| `share.iframeReload` | "Reload" | "Neu laden" | "Recargar" | "Recharger" |
| `share.iframeSandboxNote` | `sandbox="allow-scripts" only — SEC-07 contract` | (English — technical) | (English — technical) | (English — technical) |

## Files Created / Modified

| File | Change |
|------|--------|
| `frontend/src/components/builder/SharePanel.tsx` | `AlertCircle` import; `useRef` import; `inflightEmbedCreate` ref; `maybeCreateEmbedToken` rewritten with Pitfall #7 guard + JSDoc; `EmbedPreviewPane` subcomponent added; render in embed code section |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | `createEmbedTokenFn` param in `setup()`; `generateShareLinkAndWait` helper; 7 new tests in 2 describe blocks |
| `frontend/src/i18n/locales/en/builder.json` | 6 new SHARE-03 keys |
| `frontend/src/i18n/locales/de/builder.json` | 6 new SHARE-03 keys |
| `frontend/src/i18n/locales/es/builder.json` | 6 new SHARE-03 keys |
| `frontend/src/i18n/locales/fr/builder.json` | 6 new SHARE-03 keys |

## Test Summary

| Suite | Tests | Status |
|-------|-------|--------|
| SharePanel.test.tsx (existing 25) | 25/25 | PASS — no regression |
| SharePanel.test.tsx (new SHARE-03, 6) | 6/6 | PASS |
| SharePanel.test.tsx (new Pitfall #7, 1) | 1/1 | PASS |
| test:i18n | 2/2 | PASS |
| typecheck | 0 errors | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test setup: Preview pane not visible with hasNonPublic:false**
- **Found during:** Task 3 (GREEN — 5 SHARE-03 tests failing "Unable to find button with name /preview/i")
- **Issue:** The `EmbedPreviewPane` is gated on `embedTokenRaw` being non-null. `embedTokenRaw` is only set when `has_non_public: true` (since `maybeCreateEmbedToken` is called only when `check.has_non_public`). Tests with `hasNonPublic: false` never set `embedTokenRaw`, so the preview toggle never appeared in the DOM.
- **Fix:** Changed 4 SHARE-03 tests from `hasNonPublic: false` to `hasNonPublic: true`. The pane requires `embedTokenRaw` (it needs `et=` in the src), so this is the correct test setup.
- **Files modified:** `SharePanel.test.tsx`
- **Commit:** `997395ff`

**2. [Rule 1 - Bug] TypeScript cast on createEmbedToken in mutationResult()**
- **Found during:** Task 3 typecheck
- **Issue:** `createEmbedToken` union type (`vi.fn() | (...args: any[]) => any`) not assignable to `Mock<Procedure>` in `mutationResult()` call
- **Fix:** Added `as any` cast at `mockedUseCreateEmbedToken.mockReturnValue(mutationResult(createEmbedToken as any))`
- **Files modified:** `SharePanel.test.tsx`
- **Commit:** `997395ff`

## Known Stubs

None — iframe `src` derives from `rawShareToken` and `embedTokenRaw` state (live token values), not hardcoded stubs.

## Threat Flags

None — T-1137-06-01 through T-1137-06-05 from the plan's threat register are all mitigated:
- T-01: `sandbox="allow-scripts"` hardcoded in JSX + inline SEC-07 comment + regression pin
- T-02: No `allow-same-origin` — iframe runs in opaque origin
- T-03: `embedTokenRaw` in URL accepted (existing snippet shape, not amplified)
- T-04: `inflightEmbedCreate` ref + Pitfall #7 regression pin
- T-05: 8-second timeout + Reload affordance

## Hand-off to Plan 07

- `SharePanel.tsx` is now feature-complete for Phase 1137 (Plans 04+05+06 delivered SHARE-02/04/06/03)
- Plan 07 is the orchestrator-driven Playwright MCP smoke checklist for the full Phase 1137 surface
- No outstanding deferrals from Plan 06

---
*Phase: 1137-sharing-and-embed-polish*
*Completed: 2026-05-27*
