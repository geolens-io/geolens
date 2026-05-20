/**
 * SEC-S14 ESLint negative regression test (Phase 1062-06).
 *
 * This file contains patterns that LOOK like token writes but MUST PASS the
 * `no-restricted-syntax` rule defined in `frontend/eslint.config.js`. It proves
 * the rule doesn't over-fire and lets future contributors understand the rule's scope.
 *
 * Known gap (documented): the AST selector only matches Literal first arguments.
 * Identifier and TemplateLiteral first arguments pass silently. This is
 * acceptable per the audit framing (catch accidental regressions, not motivated
 * evasion). Closing this gap requires a custom ESLint plugin — deferred to
 * Phase 1063+ if needed.
 *
 * To verify no false positives:
 *   cd frontend
 *   npm run lint:sec-s14-no-false-positive
 *   # expect exit 0 (zero errors)
 *
 * Audit reference: docs-internal/audits/sec-audit-20260519.md S14
 * Implementation: docs-internal/audits/security-lessons.md — Phase 1062-06 section
 */

// 1. Theme key — passes (no token shape).
localStorage.setItem('geolens-theme', 'dark');

// 2. Sidebar collapsed — passes (no token shape).
localStorage.setItem('sidebar-collapsed', 'true');

// 3. View storage key — passes (no token shape).
localStorage.setItem('geolens-view-mode', 'grid');

// 4. i18n language — passes (no token shape).
localStorage.setItem('geolens-language', 'en');

// 5. Identifier-as-key — passes (rule only fires on Literal type for arg 0).
// Known gap: if the identifier resolves to a token-shape string at runtime, the
// rule won't fire. Documented above and in security-lessons.md.
const SIDEBAR_KEY = 'sidebar-collapsed';
localStorage.setItem(SIDEBAR_KEY, 'true');

// 6. Template-literal-as-key — passes (rule only fires on Literal type for arg 0).
// Known gap: `token-${id}` is a TemplateLiteral node, not a Literal.
const userId = '123';
localStorage.setItem(`view-${userId}`, 'grid');

// 7. sessionStorage.setItem — passes (rule only applies to localStorage).
// This is intentional — sessionStorage is cleared on tab close, lower risk.
sessionStorage.setItem('csrf-token', 'temporary');

// 8. localStorage.getItem — passes (only setItem is gated).
localStorage.getItem('any-key');

// 9. Some-other-object.setItem — passes (only localStorage.setItem is gated).
// The AST selector requires callee.object.name='localStorage'.
const fakeStore = { setItem: (_k: string, _v: string) => {} };
fakeStore.setItem('jwt-token', 'should not fire');

export {};
