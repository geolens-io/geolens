/**
 * fix(#1536): structural gate for unguarded Web Storage access.
 *
 * Reading `sessionStorage` or `localStorage` throws in a storage-denied
 * context: a sandboxed frame with an opaque origin, private-mode Safari, or a
 * browser with third-party storage blocked all raise `SecurityError` on the
 * PROPERTY ACCESS, before `getItem`/`setItem` runs. A
 * `typeof sessionStorage !== 'undefined'` check passes in every one of those,
 * so it protects nothing.
 *
 * #1515 fixed three sites by hand. #1527/#1535 fixed six more, five of which
 * were writes. This is the gate so there is no seventh round.
 *
 * THE RULE (one condition, no exemptions): every member access of
 * `sessionStorage`/`localStorage` under `src/` must sit lexically inside a
 * `try` block, without crossing a function boundary on the way up.
 *
 * Why no exemption for `lib/storage.ts`: it does not need one. Its own six raw
 * accesses are already inside `try` blocks, so the single rule covers the
 * helper and any caller doing its own try/catch. `readSessionStorage(...)` is
 * a call expression, not a member access of `sessionStorage`, so a caller
 * using the helper never registers here at all. An exemption list was
 * considered and deliberately NOT added: one that exists but is never needed
 * is the kind of thing someone later widens. If you are here because you want
 * to add one, the answer is almost certainly a `try` block instead.
 *
 * WHAT THIS GATE DOES NOT PROVE. It proves an access cannot throw. It does
 * NOT prove the code degrades correctly when storage is denied, and those two
 * came apart in this repo. Before #1515, `public/asset-guard.js` wrapped the
 * access in a try and reached `window.location.reload()` from the catch: the
 * SecurityError was swallowed, the latch never got written, and the reload ran
 * anyway. Roughly 12,000 reloads in 12 seconds. That code would pass this
 * gate. An empty catch followed by the consequential action is invisible here,
 * and deliberately so, since deciding whether a catch fails open is a
 * judgement about what the code does next and an AST rule that guessed would
 * only produce noise. Read the catch block yourself.
 *
 * SCOPE. Test files are excluded (`__tests__/`, `*.test.*`, `*.spec.*`,
 * `src/test/**`): tests legitimately drive storage directly, including the
 * `denySessionStorage` harness in `src/test/deny-storage.ts`. That is a scope
 * boundary, not an allowlist, which is why the excluded count is asserted
 * below rather than silently filtered. `public/*.js` is not TypeScript and is
 * out of the glob; both files there are already guarded.
 */
import ts from 'typescript';

const STORAGE_NAMES = new Set(['sessionStorage', 'localStorage']);

// Vite-native source loading, matching src/i18n/source-keys.test.ts. Keeps
// node:fs out of tsconfig.app.json. Eager so the scan is synchronous.
const allModules = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function isProductionSource(path: string): boolean {
  if (path.includes('/__tests__/')) return false;
  if (/\.(test|spec)\.tsx?$/.test(path)) return false;
  if (path.startsWith('/src/test/')) return false;
  if (path.endsWith('.d.ts')) return false;
  if (/\.skip\.tsx?$/.test(path)) return false;
  return true;
}

const sources = Object.entries(allModules).filter(([path]) => isProductionSource(path));
const excludedCount = Object.keys(allModules).length - sources.length;

function isFunctionLike(node: ts.Node): boolean {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isFunctionExpression(node) ||
    ts.isArrowFunction(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isConstructorDeclaration(node) ||
    ts.isGetAccessor(node) ||
    ts.isSetAccessor(node)
  );
}

/**
 * Guarded means: a `try` block encloses the access lexically, reached without
 * crossing a function boundary.
 *
 * Crossing one matters. A callback declared inside a try runs later, off that
 * stack, so the try does not protect it:
 *   try { el.addEventListener('x', () => sessionStorage.getItem(k)); } catch {}
 * This is the conservative direction. It can flag a helper that is only ever
 * called from inside a try (a false positive worth discussing), but it cannot
 * miss a real one.
 *
 * Arriving at a TryStatement from its catch or finally does not count either:
 * a throw in a catch block propagates exactly as if the try were not there.
 */
function isGuarded(node: ts.Node): boolean {
  let child: ts.Node = node;
  let parent: ts.Node | undefined = node.parent;
  while (parent) {
    if (ts.isTryStatement(parent) && child === parent.tryBlock) return true;
    if (isFunctionLike(parent)) return false;
    child = parent;
    parent = parent.parent;
  }
  return false;
}

/** Identifier positions that are names rather than value reads. */
function isNonValuePosition(node: ts.Identifier): boolean {
  const p = node.parent;
  if (!p) return false;
  if (ts.isPropertyAssignment(p) && p.name === node) return true;
  if (ts.isPropertySignature(p) && p.name === node) return true;
  if (ts.isPropertyDeclaration(p) && p.name === node) return true;
  if (ts.isBindingElement(p) && p.propertyName === node) return true;
  if (ts.isImportSpecifier(p) || ts.isExportSpecifier(p)) return true;
  if (ts.isTypeReferenceNode(p)) return true;
  if (ts.isVariableDeclaration(p) && p.name === node) return true;
  if (ts.isParameter(p) && p.name === node) return true;
  return false;
}

interface Access {
  file: string;
  line: number;
  snippet: string;
  guarded: boolean;
}

/**
 * Every form that reads the storage property, since reading it is the throw:
 * `sessionStorage.x`, `window.sessionStorage`, `window['sessionStorage']`, and
 * a bare `const s = sessionStorage` alias.
 */
function collectAccesses(file: string, source: string): Access[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: Access[] = [];

  const visit = (node: ts.Node): void => {
    let hit: ts.Node | null = null;
    if (ts.isIdentifier(node) && STORAGE_NAMES.has(node.text) && !isNonValuePosition(node)) {
      hit = node;
    }
    if (
      ts.isElementAccessExpression(node) &&
      node.argumentExpression &&
      ts.isStringLiteralLike(node.argumentExpression) &&
      STORAGE_NAMES.has(node.argumentExpression.text)
    ) {
      hit = node;
    }
    if (hit) {
      const { line } = sf.getLineAndCharacterOfPosition(hit.getStart(sf));
      found.push({
        file,
        line: line + 1,
        snippet: hit.getText(sf).slice(0, 80),
        guarded: isGuarded(hit),
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

const accesses = sources.flatMap(([path, source]) => collectAccesses(path, source));

describe('#1536: Web Storage access under src/ must be exception-safe', () => {
  // Vacuity guards. If a future glob or filter change silently matches
  // nothing, these fail loudly instead of reporting a clean sweep of zero
  // files. A gate that cannot fail is worse than no gate, because it reads as
  // evidence.
  it('actually scanned the source tree', () => {
    expect(sources.length).toBeGreaterThan(200);
    expect(excludedCount).toBeGreaterThan(0);
  });

  it('actually found storage accesses to classify', () => {
    expect(accesses.length).toBeGreaterThan(0);
  });

  it('has no unguarded access', () => {
    const unguarded = accesses.filter((a) => !a.guarded);
    const detail = unguarded.map((a) => `  ${a.file}:${a.line}  ${a.snippet}`).join('\n');
    expect(
      unguarded,
      unguarded.length === 0
        ? ''
        : `Unguarded sessionStorage/localStorage access.\n${detail}\n\n` +
            'Reading the property throws SecurityError in a storage-denied context ' +
            '(sandboxed frame with an opaque origin, private-mode Safari, third-party ' +
            'storage blocked). Route it through readSessionStorage/writeSessionStorage/' +
            'removeSessionStorage in src/lib/storage.ts, or wrap it in a try block. ' +
            'A `typeof sessionStorage !== "undefined"` check does NOT fix this.',
    ).toEqual([]);
  });
});

/**
 * The detector's own fixtures. Without these the gate can rot into a pass:
 * a broken matcher finds nothing and every assertion above still goes green.
 * Each case is a shape observed in this codebase or a near miss of one.
 */
describe('#1536: detector fixtures', () => {
  const scan = (src: string) => collectAccesses('/src/fixture.tsx', src);
  const detected = (src: string) => scan(src).length;
  const unguarded = (src: string) => scan(src).filter((a) => !a.guarded).length;

  it.each([
    ['bare read', `const v = sessionStorage.getItem('k');`],
    ['bare write', `sessionStorage.setItem('k', 'v');`],
    ['bare removeItem', `sessionStorage.removeItem('k');`],
    ['window property read', `const s = window.localStorage;`],
    ['globalThis property read', `const s = globalThis.sessionStorage;`],
    ['bracket access', `const s = window['sessionStorage'];`],
    ['bare identifier alias', `const s = sessionStorage;`],
    ['callback declared inside try', `try { on('x', () => sessionStorage.getItem('k')); } catch {}`],
    ['inside catch block', `try { g(); } catch { sessionStorage.setItem('k', 'v'); }`],
    ['inside finally block', `try { g(); } finally { sessionStorage.setItem('k', 'v'); }`],
  ])('flags %s', (_name, src) => {
    expect(detected(src)).toBe(1);
    expect(unguarded(src)).toBe(1);
  });

  it.each([
    ['a direct try', `try { sessionStorage.getItem('k'); } catch {}`],
    ['a nested block inside try', `try { if (a) { sessionStorage.getItem('k'); } } catch {}`],
    [
      'a function whose body is a try',
      `function f() { try { return sessionStorage.getItem('k'); } catch { return null; } }`,
    ],
  ])('accepts %s', (_name, src) => {
    expect(detected(src)).toBe(1);
    expect(unguarded(src)).toBe(0);
  });

  it.each([
    ['a line comment', `// sessionStorage.getItem is dangerous\nconst a = 1;`],
    ['a block comment', `/* localStorage.setItem here */ const a = 1;`],
    ['a string literal', `const msg = 'sessionStorage.getItem failed';`],
    ['a helper call', `import { readSessionStorage } from '@/lib/storage'; readSessionStorage('k');`],
    ['an object literal key', `const o = { localStorage: 1 };`],
    ['a type annotation', `let s: Storage | null = null;`],
  ])('ignores %s', (_name, src) => {
    expect(detected(src)).toBe(0);
  });
});
