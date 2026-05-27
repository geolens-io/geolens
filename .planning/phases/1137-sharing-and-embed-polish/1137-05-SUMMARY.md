---
phase: 1137-sharing-and-embed-polish
plan: "05"
subsystem: ui
tags: [share, expiration, presets, pitfall-6, i18n, tdd]

requires:
  - phase: 1137-04
    provides: chip-based allowed-origins UI (configOrigins prop stable)

provides:
  - "Expiration preset Select (Never/1d/7d/30d/1y/Custom) replacing free-text date Input in ShareLinkSettings"
  - "handleApplyPreset(): T23:59:59.000Z UTC arithmetic for preset expiresAt computation"
  - "detectPreset(): ±1 day tolerance bucket detection from shareExpires ISO string"
  - "Pitfall #6 docstring on handleSaveExpiration + handleApplyPreset"
  - "8 new SHARE-04 + Pitfall #6 regression tests in SharePanel.test.tsx"
  - "6 new i18n keys in en/de/es/fr builder.json"

affects:
  - "Plan 06 (iframe preview): SharePanel expiration Select is complete; iframe pane adds below embed code section"
  - "Plan 07+ (future): expirationPreset state is local to ShareLinkSettings; no shared context impact"

tech-stack:
  added: []
  patterns:
    - "Radix Select in JSDOM testing: fireEvent.click for trigger + options (not userEvent.click)"
    - "vi.useRealTimers() in beforeEach to prevent fake-timer bleed between tests"
    - "setup() param extension pattern (updateShareTokenFn, shareExpires) to avoid post-render mock override race"
    - "detectPreset(): ±1 day tolerance window for mapping shareExpires to preset bucket"
    - "handleApplyPreset(): T23:59:59.000Z convention via datePart + literal suffix"

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
  - "fireEvent.click (not userEvent.click) for Radix Select in JSDOM — userEvent pointer dispatch does not trigger Radix onValueChange in test environment"
  - "No fake timers for expiresAt assertions — check T23:59:59.000Z suffix + approximate window instead (fake timers + waitFor + userEvent = flaky)"
  - "setup() extended with shareExpires param so mockedUseMapShareToken is not overwritten by setup() internals"
  - "detectPreset called in disclosure onClick (not useEffect on shareExpires) — keeps detection co-located with disclosure open lifecycle"
  - "Plain function stubs (not vi.fn) for Element.prototype polyfills — vi.clearAllMocks() in beforeEach would clear vi.fn implementations"

requirements-completed:
  - SHARE-04

duration: 1740s
completed: 2026-05-27
---

# Phase 1137 Plan 05: SharePanel Expiration Preset Select + Pitfall #6 Summary

**Expiration preset Select (6 options: Never/1d/7d/30d/1y/Custom date…) replaces free-text date Input in ShareLinkSettings — non-Custom presets fire immediately via handleApplyPreset (T23:59:59Z UTC); Pitfall #6 survival of rawShareToken/embedTokenRaw across preset selection pinned by docstrings + 8 regression tests**

## Performance

- **Duration:** ~29 min (1740s)
- **Started:** 2026-05-27T23:34:00Z
- **Completed:** 2026-05-27T23:50:26Z
- **Tasks:** 3 (TDD RED + GREEN + i18n)
- **Files modified:** 6

## Accomplishments

- Replaced free-text `<Input type="date">` + Save button in expiration block with a Radix `Select` (6 options)
- `detectPreset(shareExpires)` helper: null → `'never'`; ±1 day tolerance for preset bucket; otherwise `'custom'`
- `handleApplyPreset(preset)`: computes `expiresAt = datePart + 'T23:59:59.000Z'` for preset keys; `null` for `'never'`; fires `updateShareToken.mutateAsync` directly (no extra Save button)
- Custom path: `expirationPreset === 'custom'` reveals existing date Input + Save button (reuses `handleSaveExpiration` unchanged)
- Disclosure onClick calls `detectPreset(shareExpires)` to initialize `expirationPreset` on open
- Pitfall #6 docstring on `handleSaveExpiration`: "does NOT modify rawShareToken or embedTokenRaw"
- Pitfall #6 docstring on `handleApplyPreset`: same assertion + regression pin reference
- 8 new SHARE-04 + Pitfall #6 tests (TDD RED→GREEN cycle verified)
- 6 new i18n keys in all 4 locales; `test:i18n` 2/2

## Task Commits

1. **Task 1 (RED)** — `0105563d` — `test(1137-05): add failing SHARE-04 expiration preset + Pitfall #6 regression tests (RED)`
2. **Task 2 (GREEN)** — `e1d9e1d5` — `feat(1137-05): implement expiration preset Select + Pitfall #6 docstrings (GREEN)`
3. **Task 3 (i18n)** — `68b89b42` — `chore(1137-05): add SHARE-04 expiration preset i18n keys to all 4 locales`

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED — 8 tests fail | `0105563d` | PASS |
| GREEN — 25 tests pass | `e1d9e1d5` | PASS |

## Preset → expiresAt Arithmetic

| Option | value | expiresAt computation |
|--------|-------|-----------------------|
| Never | `'never'` | `null` (no expiration) |
| 1 day | `'1d'` | `new Date(now + 1×86400000).toISOString().split('T')[0] + 'T23:59:59.000Z'` |
| 7 days | `'7d'` | `new Date(now + 7×86400000).toISOString().split('T')[0] + 'T23:59:59.000Z'` |
| 30 days | `'30d'` | `new Date(now + 30×86400000).toISOString().split('T')[0] + 'T23:59:59.000Z'` |
| 1 year | `'1y'` | `new Date(now + 365×86400000).toISOString().split('T')[0] + 'T23:59:59.000Z'` |
| Custom date… | `'custom'` | Reveals date Input + Save; `handleSaveExpiration` fires on click |

## detectPreset Tolerance

`±1 day (86,400,000ms)` window for matching preset buckets. A `shareExpires` ISO string is compared against each preset's `now + N days` target date; if `|target - preset| < ONE_DAY_MS`, the preset key is returned. Otherwise `'custom'`. `null` → `'never'`.

## Pitfall #6 Docstring Locations

1. **`handleSaveExpiration`** (SharePanel.tsx:~167): "Pitfall #6 contract: this handler does NOT modify rawShareToken or embedTokenRaw state. Expiration is updated on the share token only via useUpdateShareToken — those raw tokens survive across dialog open/close cycles and across expiration changes per the 3ed5ceb3 separation."
2. **`handleApplyPreset`** (SharePanel.tsx:~196): "Pitfall #6 contract: does NOT modify rawShareToken or embedTokenRaw — those survive independently per the 3ed5ceb3 separation. Expiration is updated on the share token only via the useUpdateShareToken mutation."

## Files Created / Modified

| File | Change |
|------|--------|
| `frontend/src/components/builder/SharePanel.tsx` | Select import; expirationPreset state; detectPreset; handleApplyPreset; Pitfall #6 docstrings; expiration block replaced |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | 8 new SHARE-04 tests; fireEvent polyfills; setup() extended with shareExpires + updateShareTokenFn params |
| `frontend/src/i18n/locales/en/builder.json` | 6 new SHARE-04 keys |
| `frontend/src/i18n/locales/de/builder.json` | 6 new SHARE-04 keys |
| `frontend/src/i18n/locales/es/builder.json` | 6 new SHARE-04 keys |
| `frontend/src/i18n/locales/fr/builder.json` | 6 new SHARE-04 keys |

## Hard Invariant Verification

| Invariant | Result |
|-----------|--------|
| `sandbox="allow-scripts"` exactly 1 match | PASS (1 match — embed snippet unchanged) |
| `allow-same-origin` as attribute = 0 | PASS (2 comment-only occurrences, pre-existing) |
| `BuilderActionSource` = 0 | PASS |
| `SHARE-08 / og_image_uri` = 0 | PASS (DEFER respected) |
| `Pitfall #6` in SharePanel.tsx >= 2 | PASS (4 occurrences across 2 docstrings) |

## Test Summary

| Suite | Tests | Status |
|-------|-------|--------|
| SharePanel.test.tsx (existing 17) | 17/17 | PASS — no regression |
| SharePanel.test.tsx (new SHARE-04, 8) | 8/8 | PASS |
| test:i18n | 2/2 | PASS |
| typecheck | 0 errors | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Radix Select + userEvent interaction pattern in JSDOM**
- **Found during:** Task 2 (GREEN — 7 tests timing out)
- **Issue:** `userEvent.click` dispatches pointer events that Radix Select's JSDOM polyfill doesn't handle — Select dropdown never opened, `waitFor` timed out
- **Fix:** Switched to `fireEvent.click` for Select trigger + options (synchronous dispatch that Radix handles in JSDOM). Set polyfills as plain functions not `vi.fn()` to prevent `vi.clearAllMocks()` clearing them between tests
- **Files modified:** `SharePanel.test.tsx`
- **Commit:** `e1d9e1d5`

**2. [Rule 1 - Bug] Fake timer + userEvent + waitFor deadlock**
- **Found during:** Task 2 (GREEN — tests using `vi.useFakeTimers()` timed out)
- **Issue:** `vi.useFakeTimers()` + `await user.click()` + `waitFor()` interact badly — timer advancement doesn't happen automatically; `waitFor` retry loop hangs
- **Fix:** Removed fake timer usage from "7 days" test. Instead: capture `beforeClick = Date.now()`, click, then assert `T23:59:59.000Z` suffix + approximate window (±24h margin). Added `vi.useRealTimers()` in `beforeEach` to prevent bleed from any future test that activates fake timers
- **Files modified:** `SharePanel.test.tsx`
- **Commit:** `e1d9e1d5`

**3. [Rule 1 - Bug] Mock setup race: setup() overwrites mockedUseMapShareToken**
- **Found during:** Task 2 (GREEN — `test_select_never_preset_clears_expiration` and pre-populate tests failing)
- **Issue:** Tests set `mockedUseMapShareToken.mockReturnValue(...)` before calling `setup()`, but `setup()` internally calls `mockedUseMapShareToken.mockReturnValue(...)`, overwriting with `expires_at: null`. After the fix for `updateShareTokenFn`, the same issue applied to `shareExpires`.
- **Fix:** Extended `setup()` with `shareExpires?: string | null` parameter (mirrors the `updateEmbedTokenFn` precedent from Plan 04). `test_select_never_preset_clears_expiration` now passes `shareExpires: thirtyDaysFromNow` so Select opens at "30 days" → clicking "Never" changes value → fires `onValueChange`
- **Files modified:** `SharePanel.test.tsx`
- **Commit:** `e1d9e1d5`

## Known Stubs

None — expiration preset Select derives computed `expiresAt` from `Date.now()` arithmetic; no hardcoded stub values.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary crossings introduced. T-1137-05-01 (preset value tampering) and T-1137-05-02 (Pitfall #6 repudiation) from the plan's threat register are both implemented: TypeScript union type gates preset values; docstrings + 8 regression tests pin the Pitfall #6 contract.

## Hand-off to Plan 06

- `SharePanel.tsx` expiration block is complete; Plan 06 adds the iframe preview pane below the embed code section
- `inflightEmbedCreate` ref pattern (Pitfall #7) is Plan 06's responsibility
- `parseOrigins` still present at SharePanel.tsx for `maybeCreateEmbedToken` callers — Plan 06 audits and replaces
- `expirationPreset` state is local to `ShareLinkSettings`; no impact on Plan 06 surfaces

---
*Phase: 1137-sharing-and-embed-polish*
*Completed: 2026-05-27*
