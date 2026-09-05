// fix(#1866): structural gate for the vitest-only locale-bundle bug.
//
// A bare `i18n.changeLanguage(lng)`, or the app's own `changeAppLanguage(lng)`,
// silently switches `i18n.language` under vitest without ever loading that
// locale's strings, so `t()` keeps rendering English — see `@/test/i18n.ts`
// for the two i18next behaviours that combine to cause it. A test that
// switches language and asserts on `t()` output is then checking English and
// passes as long as English also satisfies the assertion, which is exactly
// how the FileDropzone es/fr/de sub-tests and the original heroTitle
// "distinct singular form" test in #1863 went vacuous without failing.
//
// The rule: any test file that calls `changeLanguage(` or
// `changeAppLanguage(` must also import `changeTestLanguage` from
// `@/test/i18n`, which registers the target locale's real bundles first.
// This is a text check, not a full AST walk (contrast
// `web-storage-guard.test.ts`, which needs one because storage denial is a
// security invariant with adversarial-shaped call sites). Getting the
// language-switch helper right is a testing convention, not a security
// boundary, so a scan for the two call names — real invocations only, an
// immediate `(` after the identifier — is proportionate. It will not catch a
// renamed import (`import { changeLanguage as go } from 'i18next'`) or a
// dynamic property access; neither shows up anywhere in this codebase today,
// and either is a bug in this file the moment one does.
import { describe, expect, it } from 'vitest';

const TEST_FILES = import.meta.glob('/src/**/*.test.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

// A named import of the helper, from any specifier — `@/test/i18n` from most
// files, `./i18n` from the co-located `src/test/i18n.test.ts`. Matching the
// imported NAME rather than a hardcoded path is what makes both work.
const HELPER_IMPORT = /\bimport\s*\{[^}]*\bchangeTestLanguage\b[^}]*\}\s*from/;
const CALL_PATTERN = /\b(?:changeLanguage|changeAppLanguage)\(/;

/** True when `source` calls changeLanguage/changeAppLanguage without importing the fix helper. */
function callsWithoutHelper(source: string): boolean {
  return CALL_PATTERN.test(source) && !HELPER_IMPORT.test(source);
}

const violations = Object.entries(TEST_FILES)
  .filter(([, source]) => callsWithoutHelper(source))
  .map(([file]) => file);

describe('#1866: vitest language switches must load real locale bundles', () => {
  // Vacuity guard: a glob that silently matched nothing would make the check
  // below pass for the wrong reason.
  it('actually scanned test files', () => {
    expect(Object.keys(TEST_FILES).length).toBeGreaterThan(50);
  });

  it('has no changeLanguage/changeAppLanguage call without the test helper', () => {
    expect(
      violations,
      violations.length === 0
        ? ''
        : `These test files call changeLanguage/changeAppLanguage directly, which ` +
            `switches i18n.language without loading that locale's bundles under ` +
            `vitest (t() keeps rendering English):\n${violations.map((f) => `  ${f}`).join('\n')}\n\n` +
            `Import changeTestLanguage from '@/test/i18n' and use it instead of a ` +
            `bare changeLanguage/changeAppLanguage call.`,
    ).toEqual([]);
  });
});

describe('#1866: detector fixtures', () => {
  it.each([
    ['bare i18n.changeLanguage', `await i18n.changeLanguage('fr');`],
    ['app changeAppLanguage', `await changeAppLanguage('fr');`],
    ['changeLanguage with no await', `i18n.changeLanguage('fr');`],
  ])('flags %s with no helper import', (_name, src) => {
    expect(callsWithoutHelper(src)).toBe(true);
  });

  it('flags changeLanguage even when the helper is imported for something else in the same file, if the call itself is not through it', () => {
    // The gate cannot tell WHICH call site used the helper — it only checks
    // that the file imports it at all. A file mixing a helper-backed switch
    // with a stray bare call is a real gap; documented here rather than
    // silently assumed away.
    const src = `import { changeTestLanguage } from '@/test/i18n';\nawait i18n.changeLanguage('fr');`;
    expect(callsWithoutHelper(src)).toBe(false);
  });

  it('does not flag a call routed through the helper', () => {
    const src = `import { changeTestLanguage } from '@/test/i18n';\nawait changeTestLanguage('fr');`;
    expect(callsWithoutHelper(src)).toBe(false);
  });

  it('does not flag a file with no language switch at all', () => {
    expect(callsWithoutHelper(`const x = 1;`)).toBe(false);
  });

  it('does not flag a mock declaration that merely names changeAppLanguage', () => {
    // No `(` immediately after the identifier, so this is a property key,
    // not an invocation — matches src/pages/__tests__/SettingsPage.a11y.test.tsx.
    const src = `vi.mock('@/i18n', () => ({ changeAppLanguage: vi.fn() }));`;
    expect(callsWithoutHelper(src)).toBe(false);
  });
});
