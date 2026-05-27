---
phase: 1137-sharing-and-embed-polish
plan: 01
subsystem: ui
tags: [share, normalization, url, vitest, pitfall-8, csp]

requires: []
provides:
  - "normalizeOrigin: canonical-form origin helper (Pitfall #8) — scheme-add, lowercase, default-port strip, path discard, wildcard rejection"
  - "dedupeOrigins: Set-based canonical dedup with first-seen order preservation"
  - "WildcardOriginError + InvalidOriginError: named error classes for chip-input UI surfaces"
  - "22 vitest cases pinning contract across 3 describe blocks (normalizeOrigin / dedupeOrigins / backend parity)"
affects:
  - "1137-04 (SharePanel chip input — consumes normalizeOrigin, dedupeOrigins, WildcardOriginError)"

tech-stack:
  added: []
  patterns:
    - "TDD RED (test only) → GREEN (impl) → parity block (backend verification) for normalization helpers"
    - "WHATWG URL constructor for origin parsing — no regex hacks"
    - "Named error class hierarchy for structured error handling at chip-input boundary"

key-files:
  created:
    - frontend/src/lib/builder/url-normalize.ts
    - frontend/src/lib/builder/__tests__/url-normalize.test.ts
  modified: []

key-decisions:
  - "Use new URL() (WHATWG) instead of regex for port/hostname extraction — matches backend urlparse semantics"
  - "Wildcard rejection at normalizeOrigin boundary (throws WildcardOriginError) rather than at dedupeOrigins — callers get typed error for inline UI message"
  - "dedupeOrigins silently filters wildcards/invalid entries — caller never needs a try/catch for the dedup path"
  - "Explicit port='' check after URL parse as defense against future WHATWG parser changes (plan directive)"

patterns-established:
  - "Pitfall #8 normalization at chip-input boundary: normalizeOrigin mirrors backend _normalize_origin exactly so optimistic chip = persisted value"
  - "CSP no-* invariant locked at unit boundary: WildcardOriginError is load-bearing for ROADMAP SC #1"

requirements-completed:
  - SHARE-06

duration: 2min
completed: 2026-05-27
---

# Phase 1137 Plan 01: url-normalize Helper Summary

**`url-normalize.ts` with 4 named exports (normalizeOrigin, dedupeOrigins, WildcardOriginError, InvalidOriginError) mirroring backend `_normalize_origin` contract exactly — 22 vitest cases including wildcard-rejection and backend-parity pins**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-27T22:59:27Z
- **Completed:** 2026-05-27T23:01:18Z
- **Tasks:** 3 (TDD RED + GREEN + parity verification)
- **Files modified:** 2

## Accomplishments

- Implemented `normalizeOrigin` mirroring backend `_normalize_origin` (schemas.py:14-31): trim, wildcard-reject, scheme-add, WHATWG URL parse, lowercase scheme+host, default-port strip (80/443), path discard
- Implemented `dedupeOrigins` with Set-keyed canonical dedup and first-seen order preservation; wildcards/invalid entries silently filtered
- 22 vitest unit tests across 3 describe blocks: normalizeOrigin (13 cases), dedupeOrigins (4 cases), parity-with-backend (5 cases)
- Zero regressions in full suite (2385/2385 pass)
- Backend parity verified against `backend/app/modules/embed_tokens/schemas.py:14-31`

## Task Commits

Each task was committed atomically:

1. **Task 1: Failing tests (RED)** — `5f83342d` (test)
2. **Task 2: Implementation (GREEN)** — `7ce97290` (feat)
3. **Task 3: Parity block** — included in Task 1 test file (no additional commit needed — all 5 parity cases written in RED step)

## Files Created/Modified

- `frontend/src/lib/builder/url-normalize.ts` — 123 lines; exports `normalizeOrigin`, `dedupeOrigins`, `WildcardOriginError`, `InvalidOriginError`
- `frontend/src/lib/builder/__tests__/url-normalize.test.ts` — 116 lines; 22 it() blocks across 3 describe blocks

## Test Counts by Describe Block

| describe block | it() count |
|---|---|
| normalizeOrigin | 13 |
| dedupeOrigins | 4 |
| parity with backend _normalize_origin | 5 |
| **Total** | **22** |

## Exported Names (4 named exports)

```
export class WildcardOriginError extends Error
export class InvalidOriginError extends Error
export function normalizeOrigin(input: string): string
export function dedupeOrigins(inputs: string[]): string[]
```

## Backend Parity

**Verified: yes** — citation `backend/app/modules/embed_tokens/schemas.py:14-31`.

The backend `_normalize_origin` algorithm:
1. `strip().lower().rstrip("/")` — trim + lowercase + trailing slash
2. Prepend `https://` if no scheme
3. `urlparse` → extract scheme, hostname, port
4. Drop default ports (80/443)
5. Return `scheme://host` or `scheme://host:port`

Frontend `normalizeOrigin` follows identical semantics via `new URL()` (WHATWG). Parity pins for 5 backend-confirmed input/output pairs all pass GREEN.

## Hand-off Contract for Plan 04

**Import path:** `@/lib/builder/url-normalize`

**Consumed exports:**
- `normalizeOrigin` — called on Enter/comma/Add-button submit in chip input; throws `WildcardOriginError` for `*` (inline error message) or `InvalidOriginError` for malformed input
- `dedupeOrigins` — called on full chip list to remove canonical duplicates
- `WildcardOriginError` — caught at chip input to show `"Wildcard origin not allowed"` as `text-xs text-destructive` below input (UI-SPEC Normalization Contract, line 192)
- `InvalidOriginError` — caught to show inline malformed-URL error

## Decisions Made

- Used `new URL()` (WHATWG URL API) over regex — browser-native parser handles port/hostname/scheme split exactly as Python's `urlparse` does for the overlap cases
- Wildcard rejection in `normalizeOrigin` (not in `dedupeOrigins`) so callers that want inline UI error get a typed exception; `dedupeOrigins` silently skips to avoid forcing try/catch at batch-use sites
- Parity block written in Task 1 (RED) test file rather than Task 3 separate commit — all 5 cases were known upfront, consolidating them into the initial test file was cleaner (no deviation, just execution order)

## Deviations from Plan

None — plan executed exactly as written. The parity `describe` block was included in the Task 1 test file rather than appended in a separate Task 3 commit; all 5 cases were present before the implementation was written, which strengthens the RED gate rather than weakening it.

## Issues Encountered

None.

## Next Phase Readiness

- `normalizeOrigin`, `dedupeOrigins`, `WildcardOriginError`, `InvalidOriginError` ready for import at `@/lib/builder/url-normalize`
- Plan 04 SharePanel chip input can consume directly without re-implementing normalization
- Legacy `parseOrigins` in `SharePanel.tsx` still present (5 matches) — Plan 04 removes it per plan spec

---
*Phase: 1137-sharing-and-embed-polish*
*Completed: 2026-05-27*
