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

/**
 * fix(#1545 codex P2): destructuring evaluates the getter too.
 *
 * `const { sessionStorage: store } = window` throws exactly like
 * `window.sessionStorage` does, because binding the property reads it. The
 * storage name sits in a key position there, which `isNonValuePosition` below
 * classifies as a name rather than a read, so the whole family slipped through
 * as a FALSE NEGATIVE. That contradicted this file's own invariant, and false
 * negatives are the one thing this walk promises not to have.
 *
 * Five forms were missed, not the one that was reported:
 *   const { sessionStorage: s } = window          BindingElement.propertyName
 *   function f({ sessionStorage: s } = window)    BindingElement.propertyName
 *   const { a: { sessionStorage: s } } = obj      BindingElement.propertyName
 *   const { ['sessionStorage']: s } = window      ComputedPropertyName
 *   ({ sessionStorage: s } = window)              PropertyAssignment.name
 *
 * The unrenamed forms (`const { sessionStorage } = window`) were already caught,
 * by falling through this function rather than by design, and the fixtures now
 * pin that so it cannot regress silently.
 *
 * Deliberately NOT conditioned on the initializer being a global. The review
 * suggested flagging only when destructuring from `window`/`globalThis`, which
 * is more precise and reintroduces the same class of hole: `const w = window;
 * const { sessionStorage: s } = w;` would read as safe. A destructuring key
 * named `sessionStorage`/`localStorage` on a non-global object is close to
 * nonexistent in real code, and flagging it is a false positive, which this
 * walk already accepts. Precision here would be bought with the invariant.
 */
function isDestructuringTarget(node: ts.Node): boolean {
  let child: ts.Node = node;
  let parent: ts.Node | undefined = node.parent;
  while (parent) {
    // `({ sessionStorage: s } = window)` — the pattern is the assignment's LHS.
    if (ts.isBinaryExpression(parent) && parent.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      return child === parent.left;
    }
    // Keep climbing through nested patterns; anything else means this object
    // literal is a value, not a target, so `const o = { localStorage: 1 }` stays
    // unflagged.
    if (
      ts.isObjectLiteralExpression(parent) ||
      ts.isArrayLiteralExpression(parent) ||
      ts.isPropertyAssignment(parent) ||
      ts.isSpreadAssignment(parent) ||
      ts.isParenthesizedExpression(parent)
    ) {
      child = parent;
      parent = parent.parent;
      continue;
    }
    return false;
  }
  return false;
}

/** The storage name in a property-key position, in any of the spellings a key takes. */
function storageNameOfKey(key: ts.Node): string | null {
  if (ts.isIdentifier(key) && STORAGE_NAMES.has(key.text)) return key.text;
  if (ts.isStringLiteralLike(key) && STORAGE_NAMES.has(key.text)) return key.text;
  if (
    ts.isComputedPropertyName(key) &&
    ts.isStringLiteralLike(key.expression) &&
    STORAGE_NAMES.has(key.expression.text)
  ) {
    return key.expression.text;
  }
  return null;
}

/** Identifier positions that are names rather than value reads. */
function isNonValuePosition(node: ts.Identifier): boolean {
  const p = node.parent;
  if (!p) return false;
  if (ts.isPropertyAssignment(p) && p.name === node) return true;
  if (ts.isPropertySignature(p) && p.name === node) return true;
  if (ts.isPropertyDeclaration(p) && p.name === node) return true;
  if (ts.isBindingElement(p) && p.propertyName === node) return true;
  // `const { foo: sessionStorage } = cfg` binds a local that merely shares the
  // name; the key `foo` is what gets read. Only the SHORTHAND form
  // (`const { sessionStorage } = window`, no propertyName) has the name double
  // as the key, and that one must stay a read. Both sit at BindingElement.name,
  // so this distinction is the only thing separating them.
  if (ts.isBindingElement(p) && p.name === node && p.propertyName !== undefined) return true;
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
 * `sessionStorage.x`, `window.sessionStorage`, `window['sessionStorage']`, a
 * bare `const s = sessionStorage` alias, and every destructuring spelling
 * (`const { sessionStorage: s } = window` and friends) — see
 * `isDestructuringTarget` for why that family needed its own handling, and for
 * the one it deliberately over-flags.
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
    // Destructuring key positions. A BindingElement is always a pattern, so its
    // propertyName needs no further test; an object literal is only a pattern
    // when it is an assignment target.
    if (ts.isBindingElement(node) && node.propertyName && storageNameOfKey(node.propertyName)) {
      hit = node.propertyName;
    }
    if (
      ts.isPropertyAssignment(node) &&
      storageNameOfKey(node.name) &&
      isDestructuringTarget(node)
    ) {
      hit = node.name;
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
    // fix(#1545 codex P2): the destructuring family. Binding the property runs
    // the getter, so every one of these throws under an opaque origin. The
    // renamed forms were the false negative; the unrenamed ones are pinned here
    // because they passed by falling through rather than by design.
    ['renamed destructuring', `const { sessionStorage: store } = window;`],
    ['unrenamed destructuring', `const { sessionStorage } = window;`],
    ['renamed destructuring in a parameter', `function f({ sessionStorage: s } = window) { return s; }`],
    ['unrenamed destructuring in a parameter', `function f({ sessionStorage } = window) {}`],
    ['nested destructuring', `const { a: { sessionStorage: s } } = obj;`],
    ['computed-key destructuring', `const { ['sessionStorage']: s } = window;`],
    ['assignment destructuring', `let s; ({ sessionStorage: s } = window);`],
    ['shorthand assignment destructuring', `let sessionStorage; ({ sessionStorage } = window);`],
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
    ['destructuring inside a try', `try { const { sessionStorage: s } = window; use(s); } catch {}`],
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
    ['a nested object literal key', `const o = { cfg: { sessionStorage: 'off' } };`],
    // The counterpart to the renamed-destructuring fix: here the KEY is `foo`,
    // so nothing reads the global. Both this and the shorthand form put the
    // storage word at BindingElement.name, so this pins the one distinction
    // that separates a false positive from a real access.
    ['a local renamed FROM a non-storage key', `const { foo: sessionStorage } = cfg;`],
    ['a type annotation', `let s: Storage | null = null;`],
  ])('ignores %s', (_name, src) => {
    expect(detected(src)).toBe(0);
  });
});
