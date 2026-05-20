/**
 * SEC-FU-03 ESLint positive regression fixture (Phase 1063-03).
 *
 * This file contains an INTENTIONAL violation of the `react/no-danger` rule
 * defined in `frontend/eslint.config.js`. The rule MUST fire on the JSX below.
 * If `npm run lint` with `--no-inline-config` over this file ever passes cleanly,
 * the react/no-danger guard has regressed.
 *
 * The inline `eslint-disable-next-line` comment keeps `npm run lint` green in
 * everyday development. To verify the rule fires, run:
 *
 *   cd frontend
 *   npm run lint:sec-fu-03-regression
 *   # expect: exit 0 — the script succeeds when eslint FAILS on this file
 *   # (the npm script inverts the exit code: `eslint --no-inline-config ...; test $? -ne 0`)
 *
 * Alternatively, to see ESLint output directly:
 *   cd frontend
 *   npx eslint --no-inline-config src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx
 *   # expect non-zero exit and 1 `react/no-danger` error on the JSX below
 *
 * The `.skip.tsx` suffix signals "regression fixture — not a test file". Vitest ignores files
 * that do not contain test() / it() / describe() calls, so this file does not appear in test runs.
 *
 * Audit reference: docs-internal/audits/sec-audit-20260519.md line 534 (SEC-FU-03)
 * Mirroring pattern: src/__tests__/sec-s14-eslint-regression.ts (Phase 1062-06)
 */

import React from 'react';

// This component uses dangerouslySetInnerHTML — banned by the SEC-FU-03 react/no-danger rule.
// The inline disable keeps `npm run lint` green; run with --no-inline-config to see the rule fire.
function DangerousComponent({ html }: { html: string }) {
  // eslint-disable-next-line react/no-danger -- SEC-FU-03 regression fixture; DELETE THIS COMMENT TO RUN THE REGRESSION CHECK
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}

export { DangerousComponent };
