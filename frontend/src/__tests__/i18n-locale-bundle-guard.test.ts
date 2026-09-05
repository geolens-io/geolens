// fix(#1866): a test file calling changeLanguage(/changeAppLanguage( must
// also import changeTestLanguage from @/test/i18n, or t() silently renders
// English under vitest instead of the target locale.
//
// Text check, not an AST walk (contrast web-storage-guard.test.ts): this is
// a testing convention, not a security boundary. Flags a real invocation
// only; misses a renamed import or dynamic property access.
import { describe, expect, it } from 'vitest';

// fix(#1866 codex r1): matches vitest's own `include` in vite.config.ts,
// which also runs *.spec.{ts,tsx}, not just *.test.{ts,tsx}.
const TEST_FILES = import.meta.glob('/src/**/*.{test,spec}.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

// A named import of the helper, from any specifier (alias or relative).
const HELPER_IMPORT = /\bimport\s*\{[^}]*\bchangeTestLanguage\b[^}]*\}\s*from/;
const CALL_PATTERN = /\b(?:changeLanguage|changeAppLanguage)\(/;

// fix(#1866): strips // and /* */ comments before matching CALL_PATTERN, so
// prose mentioning `i18n.changeLanguage('fr')` isn't read as a real call.
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
}

/** True when `source` calls changeLanguage/changeAppLanguage without importing the fix helper. */
function callsWithoutHelper(source: string): boolean {
  // fix(#1866 codex r1): both checks run on the same stripped text, or a
  // commented-out import satisfies HELPER_IMPORT while a real call is missed.
  const stripped = stripComments(source);
  return CALL_PATTERN.test(stripped) && !HELPER_IMPORT.test(stripped);
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

  it('reaches a .spec.tsx file, not just .test.tsx', () => {
    expect(
      Object.keys(TEST_FILES).some((f) => f.endsWith('spec-glob-fixture.spec.tsx')),
    ).toBe(true);
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
    [
      'a commented-out helper import beside a real direct call',
      `// import { changeTestLanguage } from '@/test/i18n';\nawait i18n.changeLanguage('fr');`,
    ],
  ])('flags %s with no helper import', (_name, src) => {
    expect(callsWithoutHelper(src)).toBe(true);
  });

  it('does not flag a stray bare call once the file imports the helper for something else', () => {
    // Known gap: the gate checks only that the file imports the helper,
    // not that each call site uses it.
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
    // not an invocation.
    const src = `vi.mock('@/i18n', () => ({ changeAppLanguage: vi.fn() }));`;
    expect(callsWithoutHelper(src)).toBe(false);
  });

  it('does not flag a comment that only mentions changeLanguage in prose', () => {
    // Real case: complete-heroTitle-plural.test.ts's comment explains why
    // `i18n.changeLanguage('fr')` doesn't work, without ever calling it.
    const src = `// i18n.changeLanguage('fr') can't reach t() in this suite.\nconst x = 1;`;
    expect(callsWithoutHelper(src)).toBe(false);
  });
});
