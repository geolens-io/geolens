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
 * `sessionStorage`/`localStorage` under `src/` must sit lexically inside the
 * block of a `try` that CATCHES, without crossing a function boundary on the
 * way up. A `try`/`finally` with no `catch` does not count — the finally runs
 * and the SecurityError carries on out of the statement. See `isGuarded` for
 * the other ways an enclosing try fails to protect.
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
 * THE FALSE-NEGATIVE PROMISE. This gate claims false positives are possible and
 * false negatives are not. It broke that claim four times: renamed
 * destructuring (five spellings, not the one that was reported), instance field
 * initializers, a `try` with no `catch`, and assignment targets in for-of and
 * for-in. Every fix was correct and every one was incomplete, because each
 * predicate decided membership by listing the shapes it recognised and calling
 * the rest safe. A list of TypeScript shapes is never finished.
 *
 * What makes the claim defensible now is not a longer list, it is the failure
 * direction. Every membership predicate here answers "report" when it meets
 * something it does not recognise:
 *   - RUNS_IN_ENCLOSING_FRAME — an unlisted node is an execution boundary, so
 *     the access is reported instead of assumed synchronous.
 *   - OBJECT_LITERAL_IS_A_VALUE — an unlisted position is a destructuring
 *     target, so the key is reported instead of assumed to be data.
 *   - isGuarded — every `try` it cannot prove catches keeps climbing, and
 *     running out of enclosing nodes reports.
 *   - isNonValuePosition — an unlisted identifier position is a value read.
 *   - isProductionSource — an unrecognised path is production source and is
 *     scanned.
 * So a construct nobody anticipated makes this gate noisy rather than blind,
 * and noisy is a bug report. Two predicates cannot be inverted; they are named
 * below with the reason.
 *
 * Adding a kind to any of those allowlists widens what the gate calls safe.
 * That is a deliberate act and must read like one: a one-line reason at the
 * entry saying why the construct runs where the gate assumes it runs. If you
 * are adding one to silence a report, you are removing the finding, not fixing
 * it.
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
 * TWO PREDICATES THAT DO NOT FAIL TOWARD REPORTING. `catchStopsTheThrow` calls
 * a catch with no lexical `throw` protective, so `catch (e) { fail(e); }` where
 * `fail` throws reads as safe. `storageNameOfKey`, and the element-access
 * matcher beside it, need a literal name, so `const k = 'sessionStorage';
 * window[k]` reads as nothing at all. Neither can be inverted at a price worth
 * paying: the first would report every catch that calls anything, the second
 * every dynamic property key in the codebase. Both would make the gate
 * unsatisfiable, and an unsatisfiable gate is how a repo ends up with an
 * exemption list. This one has none to give.
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

/**
 * fix(#1545 codex P2, round 2): this list is an ALLOWLIST, and that is the
 * whole design.
 *
 * The previous version asked the opposite question: it climbed toward the `try`
 * and stopped at anything it recognised as function-like. Everything it did not
 * recognise was assumed to run synchronously. That is a blocklist of
 * deferred-execution constructs, and a blocklist of those in TypeScript will
 * never be complete. Two rounds of review found two holes in it: a callback is
 * obvious, a non-static class field initializer is not, and neither is the next
 * one nobody has thought of. Every gap was a silent FALSE NEGATIVE in a gate
 * whose docstring promises there are none.
 *
 * So the question is inverted. An access counts as guarded only if EVERY node
 * between it and the `try` is listed below as running in the enclosing frame.
 * Anything unrecognised is treated as a boundary, so the access gets reported.
 * That fails toward false positives, which this gate accepts by design, instead
 * of toward silence. A construct nobody anticipated now makes the gate noisy
 * rather than blind, and noisy is a bug report.
 *
 * Note what this buys for free. Arrow functions, function expressions, methods,
 * constructors, getters, setters and generator bodies are all boundaries
 * without being named anywhere: they simply are not on this list. The old code
 * had to enumerate each one, which is exactly why it could miss one.
 *
 * If you are here because the gate flagged something that is genuinely
 * synchronous, add that kind here with a one-line reason. Adding a kind is a
 * deliberate widening and should read like one.
 */
const RUNS_IN_ENCLOSING_FRAME: ReadonlySet<ts.SyntaxKind> = new Set([
  // Statements and control flow.
  ts.SyntaxKind.Block,
  ts.SyntaxKind.ExpressionStatement,
  ts.SyntaxKind.VariableStatement,
  ts.SyntaxKind.VariableDeclarationList,
  ts.SyntaxKind.VariableDeclaration,
  ts.SyntaxKind.IfStatement,
  ts.SyntaxKind.ForStatement,
  ts.SyntaxKind.ForInStatement,
  ts.SyntaxKind.ForOfStatement,
  ts.SyntaxKind.WhileStatement,
  ts.SyntaxKind.DoStatement,
  ts.SyntaxKind.SwitchStatement,
  ts.SyntaxKind.CaseBlock,
  ts.SyntaxKind.CaseClause,
  ts.SyntaxKind.DefaultClause,
  ts.SyntaxKind.ReturnStatement,
  ts.SyntaxKind.ThrowStatement,
  ts.SyntaxKind.LabeledStatement,
  // A catch body runs synchronously on the frame that threw. Whether the try it
  // belongs to protects an access INSIDE that body is a separate question,
  // answered at the TryStatement in isGuarded — reaching a try from its catch
  // never counts as guarded there.
  ts.SyntaxKind.CatchClause,
  // A class body's STATIC parts evaluate when the class definition does, so a
  // try around the class really does cover them. Non-static field initializers
  // are handled in runsInEnclosingFrame below and are NOT covered.
  ts.SyntaxKind.ClassDeclaration,
  ts.SyntaxKind.ClassExpression,
  ts.SyntaxKind.ClassStaticBlockDeclaration,
  // Expressions.
  ts.SyntaxKind.PropertyAccessExpression,
  ts.SyntaxKind.ElementAccessExpression,
  ts.SyntaxKind.CallExpression,
  ts.SyntaxKind.NewExpression,
  ts.SyntaxKind.BinaryExpression,
  ts.SyntaxKind.ConditionalExpression,
  ts.SyntaxKind.ParenthesizedExpression,
  ts.SyntaxKind.PrefixUnaryExpression,
  ts.SyntaxKind.PostfixUnaryExpression,
  ts.SyntaxKind.TypeOfExpression,
  ts.SyntaxKind.VoidExpression,
  ts.SyntaxKind.DeleteExpression,
  ts.SyntaxKind.AwaitExpression,
  ts.SyntaxKind.ArrayLiteralExpression,
  ts.SyntaxKind.ObjectLiteralExpression,
  ts.SyntaxKind.PropertyAssignment,
  ts.SyntaxKind.ShorthandPropertyAssignment,
  ts.SyntaxKind.SpreadAssignment,
  ts.SyntaxKind.SpreadElement,
  ts.SyntaxKind.TemplateExpression,
  ts.SyntaxKind.TemplateSpan,
  ts.SyntaxKind.TaggedTemplateExpression,
  ts.SyntaxKind.AsExpression,
  ts.SyntaxKind.SatisfiesExpression,
  ts.SyntaxKind.NonNullExpression,
  ts.SyntaxKind.TypeAssertionExpression,
  ts.SyntaxKind.CommaListExpression,
  ts.SyntaxKind.ComputedPropertyName,
  ts.SyntaxKind.ObjectBindingPattern,
  ts.SyntaxKind.ArrayBindingPattern,
  ts.SyntaxKind.BindingElement,
  // JSX evaluates during render, on the frame that renders it.
  ts.SyntaxKind.JsxElement,
  ts.SyntaxKind.JsxSelfClosingElement,
  ts.SyntaxKind.JsxFragment,
  ts.SyntaxKind.JsxOpeningElement,
  ts.SyntaxKind.JsxAttributes,
  ts.SyntaxKind.JsxAttribute,
  ts.SyntaxKind.JsxSpreadAttribute,
  ts.SyntaxKind.JsxExpression,
]);

function runsInEnclosingFrame(node: ts.Node): boolean {
  // The static/non-static split is the one place the kind alone is not enough.
  // `static v = sessionStorage.getItem(k)` runs at class-definition time, so a
  // try around the class does cover it. `v = sessionStorage.getItem(k)` runs at
  // construction, on whatever frame calls `new`, which can be anywhere.
  if (ts.isPropertyDeclaration(node)) {
    return node.modifiers?.some((m) => m.kind === ts.SyntaxKind.StaticKeyword) ?? false;
  }
  return RUNS_IN_ENCLOSING_FRAME.has(node.kind);
}

/**
 * Does this `catch` stop the exception, or hand it back?
 *
 * Any `throw` anywhere in the catch body counts as handing it back. That is
 * deliberately blunt: `throw e`, `throw new Error(...)` and `if (x) throw e`
 * all read the same here, because a conditional rethrow protects the access on
 * some paths and not others, and "some paths" is not a guard. Sorting the
 * reachable throws from the dead ones is control-flow analysis, and the
 * cautious answer costs a false positive while the clever one costs the
 * invariant.
 *
 * Two shapes are over-reported and one is missed, all noted rather than coded
 * around:
 *   - over: a throw the catch body catches itself,
 *     `catch (e) { try { throw e; } catch {} }`.
 *   - over: a throw inside a callback the catch body merely schedules,
 *     `catch (e) { queueMicrotask(() => { throw e; }); }`. Telling that from
 *     `arr.forEach(() => { throw e; })`, which does propagate, means knowing
 *     what the callee does with the function. Pinned as a fixture.
 *   - missed: `catch (e) { fail(e); }` where `fail` throws. Cross-function, so
 *     nothing lexical can see it. Catching it needs whole-program analysis,
 *     which this file does not do and should not start doing.
 * The over-reports cost noise, which this gate accepts. The miss is the honest
 * limit of a lexical rule, stated so nobody reads a pass here as proof that a
 * catch swallows.
 */
function catchStopsTheThrow(clause: ts.CatchClause): boolean {
  let rethrows = false;
  const visit = (n: ts.Node): void => {
    if (rethrows) return;
    if (ts.isThrowStatement(n)) {
      rethrows = true;
      return;
    }
    ts.forEachChild(n, visit);
  };
  visit(clause.block);
  return !rethrows;
}

/**
 * Guarded means: some enclosing `try` CATCHES the throw, and every node between
 * the access and that try's block runs in the same frame.
 *
 * fix(#1545 codex P2, round 3): the old version asked "is there an enclosing
 * try", which is a different question — `try { ... } finally { ... }` runs the
 * finally and then lets the SecurityError carry on out. That was the third
 * false negative in a gate whose docstring promises none, so here is the
 * enumeration rather than a fourth point fix. An enclosing `try` fails to
 * protect the access when:
 *
 *   1. it has no `catch`. Detected exactly, from `catchClause`.
 *   2. the access is in the `catch` block — a throw there propagates as if the
 *      try were not there. Detected exactly, from the arrival position.
 *   3. the access is in the `finally` block. Same, detected the same way.
 *   4. the `catch` rethrows, conditionally or not. Detected conservatively;
 *      `catchStopsTheThrow` says what that costs in both directions.
 *   5. the `catch` calls something that throws. NOT detected and deliberately
 *      not attempted — a whole-program question, and a lexical rule guessing at
 *      it would be wrong in both directions.
 *   6. the `catch` swallows the error and then does something worse: the
 *      asset-guard reload in this file's header. NOT detected, for the reason
 *      given up there. Read the catch block yourself.
 *
 * None of 1 through 4 answers on its own, because the catching try is not
 * always the nearest one:
 *   try { try { sessionStorage.getItem(k); } finally { a(); } } catch {}
 * is guarded. So each of them keeps climbing, and only running out of enclosing
 * nodes is an answer. Stopping at the first TryStatement made the catch- and
 * finally-arrival cases false POSITIVES, which the fixtures now pin alongside
 * the negatives.
 *
 * The frame rule is unchanged. A callback declared inside a try runs later, off
 * that stack, so the try does not protect it:
 *   try { el.addEventListener('x', () => sessionStorage.getItem(k)); } catch {}
 * Nor does it protect an instance field initializer, which runs at `new`:
 *   try { class C { v = sessionStorage.getItem(k); } } catch {}
 * Both fall out of the allowlist above rather than being special-cased.
 *
 * This can flag a helper that is only ever called from inside a try, which is a
 * false positive worth discussing. It cannot miss a real one.
 */
function isGuarded(node: ts.Node): boolean {
  let child: ts.Node = node;
  let parent: ts.Node | undefined = node.parent;
  while (parent) {
    if (ts.isTryStatement(parent)) {
      if (
        child === parent.tryBlock &&
        parent.catchClause &&
        catchStopsTheThrow(parent.catchClause)
      ) {
        return true;
      }
      // The throw leaves this statement — no catch, a catch that may rethrow,
      // or we came up out of the catch/finally. An outer try may still stop it.
      child = parent;
      parent = parent.parent;
      continue;
    }
    if (!runsInEnclosingFrame(parent)) return false;
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
 *
 * fix(#1545 codex P2, round 4): INVERTED, for the reason given at
 * RUNS_IN_ENCLOSING_FRAME. The old version asked "is the parent an `=`
 * expression", answered false for everything else, and so missed
 * `for ({ sessionStorage: store } of [window]) {}` — a target that binds the
 * key on every iteration. That was the fourth false negative in four rounds,
 * and the third produced by a predicate that recognises shapes and calls the
 * rest safe.
 *
 * So the question is inverted here too. The positions where an object literal
 * is a VALUE are enumerated below; everything else is treated as a target and
 * gets reported. for-of, for-in, for-await-of and the array-wrapped forms all
 * fall out of that without being named, as does the next spelling nobody has
 * thought of.
 *
 * Note which nodes are NOT decisions. An object literal inside another object
 * literal, an array literal, a property assignment, a spread or a paren is the
 * same syntax whether it ends up a value or a nested target —
 * `{ cfg: { sessionStorage: 'off' } }` against
 * `({ a: { sessionStorage: s } } = window)` — so those keep climbing and the
 * enclosing context decides.
 */
const OBJECT_LITERAL_IS_A_VALUE: ReadonlySet<ts.SyntaxKind> = new Set([
  // Initializer and argument positions.
  ts.SyntaxKind.VariableDeclaration,
  ts.SyntaxKind.PropertyDeclaration,
  ts.SyntaxKind.Parameter,
  ts.SyntaxKind.BindingElement,
  ts.SyntaxKind.CallExpression,
  ts.SyntaxKind.NewExpression,
  ts.SyntaxKind.Decorator,
  // Statements that consume an expression. None can take an assignment target
  // without an `=`, which is handled as a position below.
  ts.SyntaxKind.ExpressionStatement,
  ts.SyntaxKind.ReturnStatement,
  ts.SyntaxKind.ThrowStatement,
  ts.SyntaxKind.ExportAssignment,
  ts.SyntaxKind.IfStatement,
  ts.SyntaxKind.WhileStatement,
  ts.SyntaxKind.DoStatement,
  ts.SyntaxKind.SwitchStatement,
  ts.SyntaxKind.CaseClause,
  // Expression contexts.
  ts.SyntaxKind.ArrowFunction,
  ts.SyntaxKind.ConditionalExpression,
  ts.SyntaxKind.PropertyAccessExpression,
  ts.SyntaxKind.ElementAccessExpression,
  ts.SyntaxKind.AwaitExpression,
  ts.SyntaxKind.YieldExpression,
  ts.SyntaxKind.TypeOfExpression,
  ts.SyntaxKind.VoidExpression,
  ts.SyntaxKind.DeleteExpression,
  ts.SyntaxKind.PrefixUnaryExpression,
  ts.SyntaxKind.TemplateSpan,
  ts.SyntaxKind.TaggedTemplateExpression,
  ts.SyntaxKind.AsExpression,
  ts.SyntaxKind.SatisfiesExpression,
  ts.SyntaxKind.NonNullExpression,
  ts.SyntaxKind.TypeAssertionExpression,
  ts.SyntaxKind.JsxExpression,
]);

function isDestructuringTarget(node: ts.Node): boolean {
  let child: ts.Node = node;
  let parent: ts.Node | undefined = node.parent;
  while (parent) {
    // Pattern-internal, so undecidable here. Climb.
    if (
      ts.isObjectLiteralExpression(parent) ||
      ts.isArrayLiteralExpression(parent) ||
      ts.isPropertyAssignment(parent) ||
      ts.isSpreadAssignment(parent) ||
      ts.isSpreadElement(parent) ||
      ts.isParenthesizedExpression(parent)
    ) {
      child = parent;
      parent = parent.parent;
      continue;
    }
    // Two positions where the same parent kind means either thing, so the kind
    // alone cannot answer.
    //   `({ sessionStorage: s } = window)` — only the left of a plain `=`.
    if (ts.isBinaryExpression(parent)) {
      return parent.operatorToken.kind === ts.SyntaxKind.EqualsToken && child === parent.left;
    }
    //   `for ({ sessionStorage: s } of [window])` — the initializer is the
    //   target; the iterated expression is a value, so a config array like
    //   `for (const c of [{ localStorage: 1 }])` stays unflagged.
    if (ts.isForOfStatement(parent) || ts.isForInStatement(parent)) {
      return child === parent.initializer;
    }
    return !OBJECT_LITERAL_IS_A_VALUE.has(parent.kind);
  }
  // Ran out of enclosing nodes without finding a value position. Report.
  return true;
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

/**
 * Identifier positions that are names rather than value reads.
 *
 * fix(#1545 codex P2, round 4): audited, and deliberately left as it is. This
 * one already fails the right way — the default is `false`, so an identifier in
 * a position nobody enumerated counts as a read and gets reported. Inverting it
 * would mean listing every position that IS a read, which is most of the
 * grammar, and would turn a short list of exceptions into a long list of
 * obligations with the same hole at the end.
 *
 * Two entries are silent only because another branch of `collectAccesses`
 * covers them, and that split is what round 4 tripped over. The key of a
 * `PropertyAssignment` and the `propertyName` of a `BindingElement` are skipped
 * here and matched there instead, so a storage key in a destructuring pattern
 * is seen exactly once. When the BindingElement branch says "always a pattern"
 * it is stating a fact about the grammar; when the PropertyAssignment branch
 * asks `isDestructuringTarget`, it is asking a question that used to be
 * answered by a shape list, and a for-of target was not on it. The compensation
 * is only as good as the predicate doing the compensating, which is why that
 * one is now inverted.
 *
 * The other entries are safe for a reason that does not depend on any other
 * branch: a property signature or declaration name, an import or export
 * specifier, a type reference, a variable or parameter name, and a local
 * renamed FROM a non-storage key all name something rather than read the
 * global. Each is pinned by a fixture below.
 */
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
    // isNonValuePosition's default direction: a position it does not list is a
    // read. Nothing enumerates "call argument" anywhere, and it is still caught.
    ['a bare identifier passed as an argument', `use(sessionStorage);`],
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
    // fix(#1545 codex P2 round 2): the deferred-execution class. Each of these
    // sits lexically inside a try whose frame is gone by the time the code
    // runs. None is special-cased; they are all simply absent from
    // RUNS_IN_ENCLOSING_FRAME, which is the point of the inversion.
    [
      'an instance field initializer inside a try',
      `try { class C { v = sessionStorage.getItem('k'); } } catch {}`,
    ],
    [
      'a getter body inside a try',
      `try { class C { get v() { return sessionStorage.getItem('k'); } } } catch {}`,
    ],
    [
      'a setter body inside a try',
      `try { class C { set v(_x) { sessionStorage.setItem('k', _x); } } } catch {}`,
    ],
    [
      'a generator body inside a try',
      `try { function* g() { yield sessionStorage.getItem('k'); } } catch {}`,
    ],
    [
      'a default parameter value inside a try',
      `try { function f(a = sessionStorage.getItem('k')) { return a; } } catch {}`,
    ],
    [
      'an object-literal method inside a try',
      `try { const o = { m() { return sessionStorage.getItem('k'); } }; } catch {}`,
    ],
    [
      'a constructor body inside a try',
      `try { class C { constructor() { sessionStorage.getItem('k'); } } } catch {}`,
    ],
    // fix(#1545 codex P2 round 3): a try that does not CATCH does not guard.
    // `finally` runs and the SecurityError carries on out of the statement, so
    // every one of these still crashes the frame the access ran on.
    ['a try with only a finally', `try { sessionStorage.getItem('k'); } finally { done(); }`],
    [
      'nested try/finally with no catch anywhere',
      `try { try { sessionStorage.getItem('k'); } finally { a(); } } finally { b(); }`,
    ],
    [
      'a catch that rethrows the error',
      `try { sessionStorage.getItem('k'); } catch (e) { throw e; }`,
    ],
    [
      'a catch that throws a wrapped error',
      `try { sessionStorage.getItem('k'); } catch { throw new Error('storage'); }`,
    ],
    [
      'a catch that rethrows conditionally',
      `try { sessionStorage.getItem('k'); } catch (e) { if (!ok(e)) throw e; }`,
    ],
    [
      'a catch that rethrows from a nested block',
      `try { sessionStorage.getItem('k'); } catch (e) { if (a) { log(e); throw e; } }`,
    ],
    // fix(#1545 codex P2 round 4): assignment patterns outside an `=`. Each of
    // these binds the storage key on every iteration, so each reads the getter.
    [
      'a for-of assignment target',
      `let store; for ({ sessionStorage: store } of [window]) {}`,
    ],
    [
      'a for-in assignment target',
      `let store; for ({ sessionStorage: store } in obj) {}`,
    ],
    [
      'a for-await-of assignment target',
      `async function f() { for await ({ sessionStorage: s } of gen()) {} }`,
    ],
    ['an array-wrapped for-of target', `let s; for ([{ sessionStorage: s }] of xs) {}`],
    [
      'a parenthesized nested pattern',
      `let s; ({ a: ({ sessionStorage: s }) } = window);`,
    ],
    // Deliberately over-reported: the throw is deferred, so this catch really
    // does contain the SecurityError. Distinguishing it needs to know whether
    // `queue` defers, which is the whole-program question this walk refuses to
    // guess at. Pinned so the over-report is a choice, not a surprise.
    [
      'a catch whose only throw is inside a deferred callback',
      `try { sessionStorage.getItem('k'); } catch (e) { queue(() => { throw e; }); }`,
    ],
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
    // The counterexample that keeps the static/non-static split honest. A
    // static initializer runs when the class definition is evaluated, which IS
    // inside the try. Deleting this distinction would look like a
    // simplification and would be a false positive.
    [
      'a STATIC field initializer inside a try',
      `try { class C { static v = sessionStorage.getItem('k'); } } catch {}`,
    ],
    [
      'a static block inside a try',
      `try { class C { static { sessionStorage.getItem('k'); } } } catch {}`,
    ],
    // Ordinary synchronous nesting must keep passing, or the inversion would
    // have made the gate useless by flagging everything.
    [
      'nested control flow inside a try',
      `try { for (const k of ks) { if (a) { sessionStorage.getItem(k); } } } catch {}`,
    ],
    [
      'a ternary inside a try',
      `try { const v = a ? sessionStorage.getItem('k') : null; use(v); } catch {}`,
    ],
    [
      'a JSX attribute inside a try',
      `try { render(<div title={sessionStorage.getItem('k')} />); } catch {}`,
    ],
    // fix(#1545 codex P2 round 3): the catching try is not always the nearest
    // one — each of these reaches an outer `catch` that does stop the throw.
    // The old rule answered at the first TryStatement it met, so it reported
    // the last two outright; the middle pair passed only because stopping early
    // happened to land on the right answer.
    [
      'a try with a catch and a finally',
      `try { sessionStorage.getItem('k'); } catch {} finally { done(); }`,
    ],
    [
      'a try/finally nested inside a try/catch',
      `try { try { sessionStorage.getItem('k'); } finally { a(); } } catch {}`,
    ],
    [
      'a rethrowing catch nested inside a try/catch',
      `try { try { sessionStorage.getItem('k'); } catch (e) { throw e; } } catch {}`,
    ],
    [
      'a catch block nested inside an outer try/catch',
      `try { try { g(); } catch { sessionStorage.setItem('k', 'v'); } } catch {}`,
    ],
    [
      'a finally block nested inside an outer try/catch',
      `try { try { g(); } finally { sessionStorage.setItem('k', 'v'); } } catch {}`,
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
    ['a nested object literal key', `const o = { cfg: { sessionStorage: 'off' } };`],
    // The counterpart to the renamed-destructuring fix: here the KEY is `foo`,
    // so nothing reads the global. Both this and the shorthand form put the
    // storage word at BindingElement.name, so this pins the one distinction
    // that separates a false positive from a real access.
    ['a local renamed FROM a non-storage key', `const { foo: sessionStorage } = cfg;`],
    ['a type annotation', `let s: Storage | null = null;`],
    // fix(#1545 codex P2 round 4): the counterweight to inverting the
    // destructuring-target test. Treating every unrecognised position as a
    // target is only affordable if the positions where an object literal is a
    // VALUE are enumerated properly, so each of these pins one of them. Without
    // them the inversion would quietly become a false-positive machine and the
    // next contributor would reach for the exemption list this gate refuses to
    // have.
    ['an object literal on the value side of for-of', `for (const c of [{ localStorage: 1 }]) { use(c); }`],
    ['an object literal call argument', `f({ localStorage: 1 });`],
    ['an object literal array element', `const a = [{ localStorage: 1 }];`],
    ['an object literal returned from an arrow', `const f = () => ({ localStorage: 1 });`],
    ['an object literal return value', `function f() { return { localStorage: 1 }; }`],
    ['an object literal ternary branch', `const o = cond ? { localStorage: 1 } : null;`],
    ['an object literal widened with as const', `const o = { localStorage: 1 } as const;`],
    ['an object literal JSX prop value', `const el = <C cfg={{ localStorage: 1 }} />;`],
    // The isNonValuePosition entries that stand on their own, one fixture each,
    // so "audited and left as it is" is a checked claim rather than a note.
    ['a class field named like storage', `class C { sessionStorage = 1; }`],
    ['an interface member named like storage', `interface X { sessionStorage: Storage }`],
    ['an import specifier', `import { sessionStorage } from './x';`],
    ['a parameter named like storage', `function f(sessionStorage) { return 1; }`],
  ])('ignores %s', (_name, src) => {
    expect(detected(src)).toBe(0);
  });
});
