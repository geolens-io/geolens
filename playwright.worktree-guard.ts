import { execFileSync } from 'node:child_process';

// fix(#1480): a worktree e2e run silently tests `main`.
//
// The dev stack bind-mounts the MAIN checkout (`./frontend` -> /app, and
// `backend/app` -> /app/app with --reload), so localhost:8080 serves main's
// code no matter which branch this worktree is on. That yields false failures
// when your fix is absent from the stack, and — worse, because nothing
// distinguishes it from a real pass — false passes when your break is.
//
// Lives in its own module because EVERY Playwright config must call it.
// `npm run e2e:smoke:builder-hardening` runs with
// `-c playwright.builder-hardening.config.ts`, so a guard that existed only in
// playwright.config.ts left that suite able to false-pass from a worktree
// (fix(#1492): caught in review).

// Paths the dev stack bind-mounts AND serves to the browser. `backend/tests`
// and `scripts` are mounted too but cannot change what a Playwright run sees,
// and docs / .github / e2e-spec-only branches are safe against the shared stack.
const FRONTEND_PATHS = ['frontend/'];
const BACKEND_PATHS = ['backend/app/', 'backend/alembic/'];

// fix(#1492): execFileSync with an argv array, never a shell string. The
// primary checkout's path is interpolated into these calls, and a path
// containing a space would word-split under a shell, silently fall back to
// `main`, and compare against a tree that is not the one bind-mounted.
function gitRaw(args: string[], cwd?: string): string {
  try {
    return execFileSync('git', args, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      ...(cwd ? { cwd } : {}),
    });
  } catch {
    return '';
  }
}

// fix(#1492): NEVER trim porcelain output. Its first line begins with a space
// for an ordinary unstaged change (" M frontend/src/a.ts"), so trimming eats
// the status column and the subsequent slice then eats a real character,
// yielding "rontend/src/a.ts" — which matches no served prefix and silently
// disables the check for that file. Only non-porcelain callers may trim.
function git(args: string[], cwd?: string): string {
  return gitRaw(args, cwd).trim();
}

/**
 * Parse `git status --porcelain -z`. NUL-terminated, so paths are never quoted
 * or escaped and a leading-space status column cannot be lost to trimming.
 * Each entry is "XY path"; a rename or copy is followed by one extra field
 * holding the origin path. Both sides of a rename are kept, because either
 * being under a served prefix means the trees differ there.
 * Exported for testing.
 */
export const porcelainPaths = (out: string): string[] => {
  const parts = out.split('\0').filter((s) => s.length > 0);
  const paths: string[] = [];
  for (let i = 0; i < parts.length; i += 1) {
    const entry = parts[i];
    paths.push(entry.slice(3));
    if (entry[0] === 'R' || entry[0] === 'C') {
      i += 1;
      if (parts[i]) paths.push(parts[i]);
    }
  }
  return paths.filter(Boolean);
};

/** Paths reported as untracked (`??`) by `git status --porcelain -z`. */
export const porcelainUntracked = (out: string): string[] =>
  out
    .split('\0')
    .filter((e) => e.startsWith('??'))
    .map((e) => e.slice(3))
    .filter(Boolean);

/**
 * Throws when this worktree's changes are absent from the stack under test.
 * Call from the top level of every Playwright config.
 */
export function assertWorktreeMatchesStack(): void {
  if (process.env.E2E_ALLOW_WORKTREE) return;
  const base = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
  // Only the shared stack is guarded. Pointing at your own stack is already
  // correct and doubles as the escape hatch.
  if (!/\/\/(localhost|127\.0\.0\.1):8080(\/|$)/.test(base)) return;

  // Equal in the main checkout; in a linked worktree git-dir is
  // <common>/worktrees/<name>. Cheaper than parsing `git worktree list`, and it
  // returns early in CI before any further git call, which matters under a
  // shallow clone where `main` may not exist.
  const gitDir = git(['rev-parse', '--absolute-git-dir']);
  const commonDir = git(['rev-parse', '--path-format=absolute', '--git-common-dir']);
  if (!gitDir || !commonDir || gitDir === commonDir) return;

  // What the stack serves is the MAIN CHECKOUT's working tree, which is
  // bind-mounted. So compare against whatever is actually checked out there,
  // not against `origin/main`: an unfetched local main is still what the
  // containers are serving, and the main checkout may even be on another
  // branch. Deriving it from the common dir keeps this literal instead of
  // assumed. Falls back to the main ref, then origin/main, then nothing.
  const mainCheckout = commonDir.replace(/\/\.git\/?$/, '');
  const servedRef =
    (mainCheckout && git(['rev-parse', '--verify', '--quiet', 'HEAD'], mainCheckout)) ||
    git(['rev-parse', '--verify', '--quiet', 'main']) ||
    git(['rev-parse', '--verify', '--quiet', 'origin/main']) ||
    '';
  const mainRef = servedRef;
  const mergeBase = mainRef ? git(['merge-base', 'HEAD', mainRef]) : '';
  // fix(#1492): an orphan or otherwise unrelated branch has NO merge base, and
  // `git merge-base` then exits non-zero with no output. Diffing against
  // nothing dropped every committed change out of `mine`, so a changed
  // frontend/ file fell through to `stale` and only warned. With no common
  // ancestor there is no way to tell my divergence from the served tree's, so
  // compare against the served tree directly and treat all of it as mine,
  // which fails CLOSED.
  const mineBase = mergeBase || mainRef;
  // Human label for messages; mainRef itself is a 40-char sha and unreadable.
  const branch = mainCheckout ? git(['rev-parse', '--abbrev-ref', 'HEAD'], mainCheckout) : '';
  const servedLabel =
    branch && branch !== 'HEAD' ? `${branch} (${mainRef.slice(0, 9)})` : mainRef.slice(0, 9) || 'main';

  // MY changes: merge-base -> working tree. Absent from the stack, so a run
  // reports on code I did not write.
  //
  // fix(#1492): --no-renames is load-bearing. With rename detection on,
  // `--name-only` prints only the destination, so moving frontend/a.ts to
  // docs/a.ts reports just docs/a.ts — and the served frontend/a.ts, which
  // still exists in the main checkout, becomes invisible to the guard.
  // Disabling detection emits the delete and the add separately, which is
  // exactly the set of touched paths this needs and costs no extra parser.
  const mine = [
    ...(mineBase ? gitRaw(['diff', '--name-only', '--no-renames', '-z', mineBase]).split('\0') : []),
    // Uncommitted changes count: they are equally absent from the stack.
    ...porcelainPaths(gitRaw(['status', '--porcelain', '-z'])),
  ].filter(Boolean);

  // fix(#1492): the merge-base delta only ever sees MY side. It is blind to
  // everything main gained after I forked, so a worktree that is merely stale
  // used to pass the guard while the stack served app code I do not have.
  // Comparing the working tree with main directly catches that direction too.
  //
  // fix(#1492): and the served tree is the main checkout's WORKING tree, not
  // its HEAD. An uncommitted or untracked file there is bind-mounted and being
  // served right now, so resolving only the committed HEAD stayed blind to it.
  const divergent = [
    ...(mainRef ? gitRaw(['diff', '--name-only', '--no-renames', '-z', mainRef]).split('\0') : []),
    ...(mainCheckout ? porcelainPaths(gitRaw(['status', '--porcelain', '-z'], mainCheckout)) : []),
  ].filter(Boolean);
  const mineSet = new Set(mine);
  const stale = divergent.filter((p) => !mineSet.has(p));

  // fix(#1492): divergence from the served tree is the ground truth; the
  // merge-base delta only CLASSIFIES it for the message. Blocking straight off
  // the delta rejected byte-identical worktrees: when main and this branch make
  // the same change independently, the path appears in the delta while the two
  // files are identical and the run is perfectly valid.
  //
  // `git diff` cannot see untracked files, so mine's untracked entries are
  // folded in separately — those are real divergence, being absent from the
  // served tree entirely.
  const reallyDifferent = new Set([
    ...divergent,
    ...porcelainUntracked(gitRaw(['status', '--porcelain', '-z'])),
  ]);
  const mineDivergent = mine.filter((p) => reallyDifferent.has(p));

  const hits = (paths: string[], prefixes: string[]) =>
    [...new Set(paths.filter((p) => prefixes.some((s) => p.startsWith(s))))];
  const frontend = hits(mineDivergent, FRONTEND_PATHS);
  const backend = hits(mineDivergent, BACKEND_PATHS);

  if (frontend.length === 0 && backend.length === 0) {
    // Nothing of mine is missing from the stack, so a run is still meaningful.
    // Being behind main is a different, milder problem: the specs run against
    // NEWER app code, which is what CI will do after merge anyway. Warn with a
    // remedy rather than blocking — a guard that blocks every stale worktree in
    // a repo whose main moves hourly gets disabled, and then it guards nothing.
    const staleServed = hits(stale, [...FRONTEND_PATHS, ...BACKEND_PATHS]);
    if (staleServed.length > 0) {
      console.warn(
        `\n[worktree] This worktree is behind ${servedLabel} in paths the stack serves:\n` +
          staleServed.slice(0, 5).map((p) => `  ${p}`).join('\n') +
          (staleServed.length > 5 ? `\n  …and ${staleServed.length - 5} more` : '') +
          `\nSpecs will run against ${servedLabel}'s newer app code, not your worktree's.` +
          `\nRebase onto ${branch || 'main'} if that matters for what you are testing.\n`,
      );
    }
    return;
  }

  const lines = [
    'e2e from this worktree would test `main`, not your changes.',
    '',
    `The dev stack bind-mounts the MAIN checkout, so ${base} serves main's code`,
    "regardless of this worktree's branch. These changed paths are served by the",
    'stack and are NOT in it:',
    '',
    ...[...frontend, ...backend].map((p) => `  ${p}`),
    '',
  ];

  if (backend.length === 0) {
    lines.push(
      'Frontend-only change. Run Vite from THIS worktree against the shared API:',
      '  cd frontend && API_PROXY_TARGET=http://localhost:8001 npm run dev -- --port 5174',
      '  E2E_BASE_URL=http://localhost:5174 npx playwright test',
    );
  } else {
    // fix(#1492): the :5174 recipe proxies to :8001, which IS the main
    // checkout's API container (docker-compose.yml: "host :8001 -> api:8000").
    // Recommending it for a backend change would reproduce the exact false pass
    // this guard exists to prevent, and E2E_BASE_URL=:5174 also disables the
    // guard, so nothing would warn you a second time.
    lines.push(
      'This change touches the BACKEND. The usual `:5174` Vite recipe will NOT',
      'exercise it: API_PROXY_TARGET=http://localhost:8001 points at the main',
      "checkout's API container, so your backend change still would not be under",
      'test — and pointing E2E_BASE_URL at :5174 also disables this guard.',
      '',
      'You need a stack built from THIS worktree (a separate compose project with',
      'its own ports, or a host-run API serving this worktree\'s backend), then:',
      '  E2E_BASE_URL=<that stack> npx playwright test',
    );
  }

  lines.push(
    '',
    'Spec-only changes (e2e/**) are safe against the shared stack and are not blocked.',
    'Set E2E_ALLOW_WORKTREE=1 to override.',
  );

  throw new Error(lines.join('\n'));
}
