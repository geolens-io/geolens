---
phase: 1138-easy-win-sweep
plan: "02"
subsystem: ui
tags: [popup, rich-text, media, url-detection, youtube, xss, i18n, builder]

requires:
  - phase: 1138-easy-win-sweep
    provides: plan 01 (Cmd+S gate) — no direct dep, same phase

provides:
  - popup-rich-text.ts: pure helper with detectUrls, splitTextWithUrls, classifyUrl, normalizeYouTubeEmbed
  - FeaturePopup ValueDisplay: image/video/YouTube/plain-URL media rendering + inline URL linkification
  - PopupConfigEditor: popup.mediaHint paragraph + {column} token doc confirmation

affects: [FeaturePopup, PopupConfigEditor, popup-rich-text]

tech-stack:
  added: []
  patterns:
    - "XSS-gated URL regex (http/https only) + React JSX text-node as secondary gate — never dangerouslySetInnerHTML"
    - "splitTextWithUrls returns RichSegment[] — structured data, never raw HTML"
    - "Media-only on standalone URL values; embedded-URL text gets inline anchor only (no media blowup in paragraphs)"
    - "YouTube iframe gets allow-same-origin (required by YT player) — intentionally laxer than share-embed sandbox; documented in code comment"

key-files:
  created:
    - frontend/src/lib/popup-rich-text.ts
    - frontend/src/lib/__tests__/popup-rich-text.test.ts
  modified:
    - frontend/src/components/map/FeaturePopup.tsx
    - frontend/src/components/map/__tests__/FeaturePopup.test.tsx
    - frontend/src/components/builder/PopupConfigEditor.tsx
    - frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "Empty text segments filtered from splitTextWithUrls output (empty leading/trailing segments omitted for cleaner rendering)"
  - "Media rendering only for standalone URL values; text-with-embedded-URLs gets anchor-only (no inline media embeds in paragraphs)"
  - "YouTube iframe sandbox includes allow-same-origin per T-1138-04 threat model (YT player requires it); differs from share-embed sandbox by design"
  - "popup.expressionHelp key left unchanged — existing wording is sufficient for {column} token doc per plan spec"

patterns-established:
  - "popup-rich-text.ts: pure module (no React, no DOM); safe to test without jsdom"
  - "RichSegment[] array as structured intermediate; renderer maps to JSX nodes, never string HTML"

requirements-completed:
  - EASY-11

duration: 5min
completed: 2026-05-27
---

# Phase 1138 Plan 02: Popup Rich-Text / Media Rendering Summary

**URL auto-linkify + image/video/YouTube media preview in FeaturePopup via XSS-gated popup-rich-text helper, with mediaHint paragraph in PopupConfigEditor and i18n parity across 4 locales.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-28T01:11:14Z
- **Completed:** 2026-05-28T01:15:52Z
- **Tasks:** 3 (all TDD)
- **Files modified:** 9

## Accomplishments

- New `popup-rich-text.ts` pure helper: `detectUrls` (XSS-gated regex), `splitTextWithUrls` (structured RichSegment[]), `classifyUrl` (image/video/youtube/other + srcUrl), `normalizeYouTubeEmbed` (canonical embed URL extraction)
- `FeaturePopup` ValueDisplay: standalone image URLs → `<img loading=lazy>` + fallback anchor; video → `<video controls preload=metadata>`; YouTube → `<iframe sandbox=allow-scripts+allow-same-origin+allow-presentation loading=lazy>`; plain URLs → existing anchor; text-with-embedded-URLs → inline text+anchor segments
- `PopupConfigEditor` new `<p>` with `t('popup.mediaHint')` below Visible Fields label; 4-locale parity maintained; `expressionHelp` unchanged
- 56 total tests green (36 popup-rich-text + 10 FeaturePopup + 10 PopupConfigEditor); typecheck 0; i18n parity 2/2

## Task Commits

1. **Task 1: popup-rich-text helper module** - `2a9e3b05` (feat)
2. **Task 2: FeaturePopup ValueDisplay media rendering** - `a1d4474c` (feat)
3. **Task 3: PopupConfigEditor mediaHint + i18n** - `ac72a616` (feat)

## Files Created/Modified

- `frontend/src/lib/popup-rich-text.ts` — Pure URL detection/classification helpers (113 lines)
- `frontend/src/lib/__tests__/popup-rich-text.test.ts` — 36 unit tests including XSS rejection pins
- `frontend/src/components/map/FeaturePopup.tsx` — ValueDisplay extended with media rendering branches
- `frontend/src/components/map/__tests__/FeaturePopup.test.tsx` — 6 new EASY-11 tests (image/video/YT/plain/embedded/XSS)
- `frontend/src/components/builder/PopupConfigEditor.tsx` — mediaHint paragraph added
- `frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx` — 2 new EASY-11 tests
- `frontend/src/i18n/locales/en/builder.json` — popup.mediaHint added
- `frontend/src/i18n/locales/de/builder.json` — popup.mediaHint added
- `frontend/src/i18n/locales/es/builder.json` — popup.mediaHint added
- `frontend/src/i18n/locales/fr/builder.json` — popup.mediaHint added

## Sample: YouTube ID Extraction

```
normalizeYouTubeEmbed('https://www.youtube.com/watch?v=ABCDEFGHIJK&list=PLxxx')
→ 'https://www.youtube.com/embed/ABCDEFGHIJK'
```

## i18n Parity Script Output

```
> vitest run src/i18n/resources.test.ts
Test Files  1 passed (1)
     Tests  2 passed (2)
Exit code: 0
```

## Security / Hardening Invariants

| Check | Result |
|-------|--------|
| `dangerouslySetInnerHTML` in FeaturePopup.tsx | 0 (none) |
| `dangerouslySetInnerHTML` in popup-rich-text.ts | 0 (only in docstring comment) |
| Pitfall #9: `map.setPaintProperty` / `map.setLayoutProperty` | 0 (none) |
| `git diff builder-action-contract.ts` | 0 lines (unchanged) |
| XSS test coverage (`javascript:` / `data:` / `vbscript:`) | 12 occurrences in test file |
| `EASY-11` tag in popup-rich-text.test.ts | 36 test cases |
| `EASY-11` tag in FeaturePopup.test.tsx | 8 occurrences |
| `popup.mediaHint` in 4/4 locale files | Yes |

## Decisions Made

- Empty text segments filtered from `splitTextWithUrls` output — cleaner rendering, no empty spans
- Media rendering only on standalone URL values; text-with-embedded-URLs gets inline anchors only (avoids embedding a 128px video in the middle of a sentence)
- YouTube iframe `allow-same-origin` included (T-1138-04): YT player's own JS requires it; documented asymmetry vs share-embed sandbox in code comment
- `popup.expressionHelp` wording left unchanged — "Use {column_name} placeholders. Example: {city}, {state}" already documents the `{column}` token spec

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test spec said "5 segments" for multiple URLs but trailing empty text segment is filtered**
- **Found during:** Task 1 (RED → GREEN iteration)
- **Issue:** Test expected `{ kind: 'text', value: '' }` as 5th segment; implementation correctly filters empty trailing text
- **Fix:** Updated test to assert 4 segments (correct behavior: no empty trailing segment when string ends at URL)
- **Files modified:** `frontend/src/lib/__tests__/popup-rich-text.test.ts`
- **Committed in:** `2a9e3b05` (part of Task 1 commit)

**2. [Rule 1 - Bug] TypeScript error: unused `user` variable in PopupConfigEditor test**
- **Found during:** Task 3 typecheck gate
- **Fix:** Removed `userEvent.setup()` from test that didn't need it (uses `rerender` not `userEvent`)
- **Files modified:** `frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx`
- **Committed in:** `ac72a616` (part of Task 3 commit)

---

**Total deviations:** 2 auto-fixed (Rule 1: bug in test expectations + TypeScript cleanup)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered

None — plan executed smoothly. All TDD cycles completed within 2 iterations each.

## Known Stubs

None — all functionality is wired end-to-end. FeaturePopup reads actual property values; no hardcoded mock data flows to the UI.

## Threat Flags

No new threat surfaces beyond those in the plan's `<threat_model>`. The 4 threats (T-1138-03 through T-1138-06) are all mitigated as documented:
- T-1138-03: XSS gate via http/https-only regex + React JSX secondary gate (36 test pins)
- T-1138-04: YouTube iframe sandbox documented in FeaturePopup.tsx code comment
- T-1138-05: accepted (user-controlled data)
- T-1138-06: `preload=metadata` + `loading=lazy` + no autoplay

## Next Phase Readiness

- EASY-11 closed
- Plan 03 (next in 1138-easy-win-sweep) ready to execute independently

---

*Phase: 1138-easy-win-sweep*
*Completed: 2026-05-27*

## Self-Check: PASSED

Files confirmed present:
- FOUND: frontend/src/lib/popup-rich-text.ts
- FOUND: frontend/src/lib/__tests__/popup-rich-text.test.ts
- FOUND: frontend/src/components/map/FeaturePopup.tsx
- FOUND: frontend/src/components/builder/PopupConfigEditor.tsx

Commits confirmed:
- 2a9e3b05: feat(1138-02): add popup-rich-text helper with URL detection and media classification
- a1d4474c: feat(1138-02): wire popup-rich-text into FeaturePopup ValueDisplay with media rendering
- ac72a616: feat(1138-02): add popup.mediaHint to PopupConfigEditor + i18n parity (en/de/es/fr)
