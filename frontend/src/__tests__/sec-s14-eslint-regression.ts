/**
 * SEC-S14 ESLint regression test (Phase 1062-06).
 *
 * This file contains INTENTIONAL violations of the `no-restricted-syntax` rule
 * defined in `frontend/eslint.config.js`. The rule MUST fire on every line below.
 * If `npm run lint` over this file ever passes cleanly (without the eslint-disable
 * comments), the rule has regressed and the SEC-S14 guard is no longer enforcing
 * the token-shape localStorage ban.
 *
 * This file is NOT imported by any production code path. It exists solely as a
 * regression pin. Vite's default `__tests__/` exclusion keeps it out of dist.
 *
 * To verify the rule fires (regression check command):
 *   cd frontend
 *   npm run lint:sec-s14-regression
 *   # expect exit 0 — the script succeeds when eslint FAILS on this file
 *   # (the npm script inverts the exit code: `eslint ...; test $? -ne 0`)
 *
 * Alternatively, to see eslint output directly:
 *   cd frontend
 *   npx eslint --no-inline-config src/__tests__/sec-s14-eslint-regression.ts
 *   # expect non-zero exit and 4 `no-restricted-syntax` errors
 *
 * Audit reference: docs-internal/audits/sec-audit-20260519.md S14
 * Implementation: docs-internal/audits/security-lessons.md — Phase 1062-06 section
 */

// Each of the following MUST be flagged by `no-restricted-syntax` when
// --no-inline-config is passed (i.e. the inline eslint-disable comments removed).
// The inline disable comments let `npm run lint` pass for everyday workflow.

// 1. Bare "token" key
// eslint-disable-next-line no-restricted-syntax -- DELETE THIS COMMENT TO RUN THE REGRESSION CHECK
localStorage.setItem('token', 'sec-s14-violation-1');

// 2. JWT-shaped key
// eslint-disable-next-line no-restricted-syntax -- DELETE THIS COMMENT TO RUN THE REGRESSION CHECK
localStorage.setItem('my-jwt-key', 'sec-s14-violation-2');

// 3. Auth-shaped key
// eslint-disable-next-line no-restricted-syntax -- DELETE THIS COMMENT TO RUN THE REGRESSION CHECK
localStorage.setItem('partner-auth-key', 'sec-s14-violation-3');

// 4. Case-insensitive match (TOKEN uppercase)
// eslint-disable-next-line no-restricted-syntax -- DELETE THIS COMMENT TO RUN THE REGRESSION CHECK
localStorage.setItem('SESSION_TOKEN', 'sec-s14-violation-4');

export {};
