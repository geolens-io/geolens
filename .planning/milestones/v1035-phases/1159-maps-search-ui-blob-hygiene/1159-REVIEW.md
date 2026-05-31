---
phase: 1159-maps-search-ui-blob-hygiene
status: clean
reviewed: 2026-05-30
blockers: 0
findings: 3
---

# Phase 1159 — Code Review

**Verdict:** CLEAN — 0 BLOCKER, 1 WARNING, 2 INFO. All three findings fixed inline (commit `681bbe88`).

Reviewer covered all five focus areas and confirmed:
- **MAPS-01** (`main.tsx` `__glRoot` cached-root guard): StrictMode preserved, no `as any`, no unmount-then-re-root, `Root` type used correctly, production cold-load path creates exactly one root (guard only matters on HMR re-exec). Sound.
- **HYG-01** (`registerBlobUrlRevocation` moved into `useEffect([queryClient])` in both hooks): behavior genuinely unchanged (idempotent WeakSet + stable queryClient singleton → fires once); rules-of-hooks satisfied (effect is unconditional, no early-return above it); no dep-array bug.
- **MAPS-02** (`blob-url-cache.test.ts`): 6 tests pin the real eviction→revoke contract (not over-mocked — calls the real `registerBlobUrlRevocation`, spies only `URL.revokeObjectURL`).
- **MAPS-01 e2e** (`console-hygiene.spec.ts`): non-tautological — forces HMR re-exec via `import('/src/main.tsx?t=...')`; regex matches the exact React warning.

## Findings (all fixed inline)

| ID | Sev | File | Issue | Resolution |
|----|-----|------|-------|------------|
| WR-01 | WARNING | `e2e/console-hygiene.spec.ts` | Spec would error (not skip) against a production static build (no `/src/main.tsx` path) | Added `test.skip(!isViteDevServer, …)` guard keyed on the `/@vite/client` script tag |
| IN-01 | INFO | `e2e/console-hygiene.spec.ts:45` | `waitForTimeout(500)` dead sleep (createRoot warning is synchronous) | Trimmed to a 100ms CDP-delivery buffer with accurate comment |
| IN-02 | INFO | `frontend/src/main.tsx:30` | `interface RootContainer` declared inside `bootstrap()` | Hoisted to module scope (type-only, no runtime change) |

**Post-fix gate:** typecheck 0; MAPS-01 e2e 2 passed; MAPS-02 vitest 6/6; existing hook eviction tests green.
