---
phase: 1137-sharing-and-embed-polish
plan: "04"
subsystem: ui
tags: [share, chip-input, normalization, optimistic-ui, i18n]

requires:
  - phase: 1137-01
    provides: normalizeOrigin/dedupeOrigins/WildcardOriginError from url-normalize.ts
  - phase: 1137-02
    provides: backend 422 "Wildcard origin not allowed" shape for round-trip pin

provides:
  - "Chip-based allowed-origins UI in ShareLinkSettings (chip list + input row + inline error + hint)"
  - "handleAddOrigin: normalizeOrigin + dedup + optimistic add + PATCH + rollback + WildcardOriginError inline error"
  - "handleRemoveOrigin: optimistic remove + PATCH + rollback + toast on failure"
  - "Backend 422 Wildcard 422 surfaces same inline error as frontend WildcardOriginError (round-trip pin)"
  - "7 new SHARE-02/SHARE-06 regression tests in SharePanel.test.tsx"
  - "8 new i18n keys in en/de/es/fr builder.json"

affects:
  - "Plan 05 (expiration presets): SharePanel.tsx now has chip block isolated; expiration block unchanged"
  - "Plan 06 (iframe preview): parseOrigins still present for maybeCreateEmbedToken paths"

tech-stack:
  added: []
  patterns:
    - "Optimistic UI add/remove with typed rollback (WildcardOriginError inline vs. generic toast)"
    - "configDomains: string | null -> configOrigins: string[] prop boundary — eliminates join/split round-trip"
    - "useEffect sync: origins state mirrors configOrigins on prop identity change"
    - "defaultValue in t() calls so keys resolve correctly before locale files are populated"

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
  - "Prop renamed configDomains (string | null) -> configOrigins (string[]) — parent computes activeEmbedToken?.allowed_origins ?? []"
  - "handleAddOrigin catches WildcardOriginError -> inline error; non-wildcard non-422 -> rollback + toast"
  - "handleRemoveOrigin sends null when list becomes empty (matches existing pattern at SharePanel.tsx:149)"
  - "parseOrigins kept (not removed) — still used at maybeCreateEmbedToken/handleRegenerateShareLink/handleRegenerateEmbedToken; Plan 06 audits those paths"
  - "domainsValue + handleSaveDomains removed — replaced entirely by origins/originInput/originError + handleAddOrigin/handleRemoveOrigin"
  - "setup() in tests extended with allowedOrigins and updateEmbedTokenFn to avoid post-render mock override race"

requirements-completed:
  - SHARE-02
  - SHARE-06

duration: 629s
completed: 2026-05-27
---

# Phase 1137 Plan 04: SharePanel Chip-Based Allowed-Origins UI Summary

**Chip-based allowed-origins input replaces legacy comma-separated Input in ShareLinkSettings — each chip uses Plan 01 normalizeOrigin, optimistic add/remove, inline WildcardOriginError, backend 422 round-trip pin**

## Performance

- **Duration:** ~10 min (629s)
- **Started:** 2026-05-27T23:20:37Z
- **Completed:** 2026-05-27T23:31:26Z
- **Tasks:** 3 (TDD RED + GREEN + i18n)
- **Files modified:** 6

## Accomplishments

- Replaced `domainsValue` + comma-separated `Input` + "Save" button with chip list (`role="list"`) + text input + `+` button + inline error + hint text
- `handleAddOrigin`: trim → `normalizeOrigin` → dedup check → optimistic setOrigins → PATCH → rollback on failure; `WildcardOriginError` sets inline error; 422/Wildcard API error sets same inline error; other errors roll back + `toast.error`
- `handleRemoveOrigin`: optimistic remove → PATCH with `null` when list empty → rollback on failure
- Prop boundary changed: `configDomains: string | null` → `configOrigins: string[]` at `ShareLinkSettings`; parent `ShareDialog` computes `activeEmbedToken?.allowed_origins ?? []`
- 7 new SHARE-02 regression tests (TDD RED→GREEN cycle verified)
- 8 new i18n keys in all 4 locales; `test:i18n` 2/2

## Task Commits

1. **Task 1 (RED)** — `557f1e9d` — `test(1137-04): add failing SHARE-02 chip-input regression tests (RED)`
2. **Task 2 (GREEN)** — `f15c85fe` — `feat(1137-04): replace comma input with chip-based allowed-origins UI (GREEN)`
3. **Task 3 (i18n)** — `577cd869` — `chore(1137-04): add SHARE-02/SHARE-06 i18n keys to all 4 locales`

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED — 7 tests fail | `557f1e9d` | PASS |
| GREEN — 17 tests pass | `f15c85fe` | PASS |

## Files Created / Modified

| File | Change |
|------|--------|
| `frontend/src/components/builder/SharePanel.tsx` | Chip UI replacing comma input; prop renamed; domainsValue/handleSaveDomains removed; normalizeOrigin imported |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | 7 new SHARE-02 tests; setup() extended with allowedOrigins + updateEmbedTokenFn params |
| `frontend/src/i18n/locales/en/builder.json` | 8 new keys |
| `frontend/src/i18n/locales/de/builder.json` | 8 new keys |
| `frontend/src/i18n/locales/es/builder.json` | 8 new keys |
| `frontend/src/i18n/locales/fr/builder.json` | 8 new keys |

## Hard Invariant Verification

| Invariant | Result |
|-----------|--------|
| `sandbox="allow-scripts"` exactly 1 match | PASS (1 match — embed snippet unchanged) |
| `allow-same-origin` = 0 *attribute* uses | PASS (2 comment-only occurrences are pre-existing negative-control docs) |
| `BuilderActionSource` not introduced | PASS (0 matches) |
| `SHARE-08 / og_image_uri` not introduced | PASS (0 matches) |
| `import normalizeOrigin` = 1 line | PASS |
| `handleSaveDomains` = 0 matches | PASS (removed) |

## Test Summary

| Suite | Tests | Status |
|-------|-------|--------|
| SharePanel.test.tsx (existing 10) | 10/10 | PASS — no regression |
| SharePanel.test.tsx (new SHARE-02, 7) | 7/7 | PASS |
| url-normalize.test.ts (existing 22) | 22/22 | PASS |
| test:i18n | 2/2 | PASS |
| typecheck | 0 errors | PASS |

## Removed Code

- `domainsValue: string` state variable
- `handleSaveDomains()` async function (replaced by `handleAddOrigin` + `handleRemoveOrigin`)
- Comma-separated `Input` + "Save" `Button` in `showDomainRestrict` block
- `setDomainsValue(window.location.origin)` on switch turn-on (chip flow initializes from prop)

## Kept Code (Deferred)

- `parseOrigins()` helper at SharePanel.tsx:24-31 — still used by `maybeCreateEmbedToken`, `handleRegenerateShareLink`, `handleRegenerateEmbedToken` in `ShareDialog`. Plan 06 audits and replaces these callers.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test setup mock override race**
- **Found during:** Task 2 (GREEN run, 7 failures persisted after implementation)
- **Issue:** Tests mocked `useMapEmbedTokens` and `useUpdateEmbedToken` BEFORE calling `setup()`, but `setup()` overwrote those mocks during `render()`. Component rendered with default mocks, not test-specific ones.
- **Fix:** Extended `setup()` with `allowedOrigins` and `updateEmbedTokenFn` parameters so the correct mocks are set before `render()`. Removed redundant per-test mock configuration from the test body.
- **Files modified:** `SharePanel.test.tsx`
- **Commit:** `f15c85fe`

**2. [Rule 1 - Bug] i18n key fallback in test environment**
- **Found during:** Task 2 (GREEN run — textbox `aria-label` `/allowed origin url/i` not matched)
- **Issue:** New i18n keys added in Task 3 didn't exist yet during Task 2 testing. `t('share.originsInputLabel')` returned the raw key string. Tests using regex `/allowed origin url/i` failed.
- **Fix:** Added `{ defaultValue: '...' }` to all new `t()` calls in the component so keys resolve correctly before locale files are populated.
- **Files modified:** `SharePanel.tsx`
- **Commit:** `f15c85fe`

**3. [Rule 1 - Bug] TypeScript type mismatch on `mutationResult` parameter**
- **Found during:** Task 2 typecheck
- **Issue:** `updateEmbedTokenFn` passed to `mutationResult()` had incompatible `Mock<Procedure | Constructable>` type vs. expected `Mock<Procedure>`.
- **Fix:** Added `as any` cast at the `mutationResult(updateEmbedTokenFn as any)` call site; added typed interface member `(...args: any[]) => any` for the setup param.
- **Files modified:** `SharePanel.test.tsx`
- **Commit:** `f15c85fe`

## Known Stubs

None — chip data derives from `configOrigins` prop (from `activeEmbedToken?.allowed_origins ?? []`), not hardcoded empty values.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary crossings introduced. The `handleAddOrigin` validation path (T-1137-04-01) and backend 422 round-trip (T-1137-04-03) from the plan's threat register are both implemented and regression-tested.

## Hand-off Contract for Plan 05

- `SharePanel.tsx` chip block is self-contained in `showDomainRestrict && (...)` branch
- Expiration block (`space-y-1.5` / date Input + Save button) is UNCHANGED — Plan 05 replaces it with a Select
- `configOrigins: string[]` prop signature is stable; Plan 05 does not touch it
- `parseOrigins` still present at line 24 for Plan 06's audit of `maybeCreateEmbedToken` callers

---
*Phase: 1137-sharing-and-embed-polish*
*Completed: 2026-05-27*
