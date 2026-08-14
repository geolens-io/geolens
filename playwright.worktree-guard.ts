import { execSync } from 'node:child_process';

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

function git(args: string): string {
  try {
    return execSync(`git ${args}`, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return '';
  }
}

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
  const gitDir = git('rev-parse --absolute-git-dir');
  const commonDir = git('rev-parse --path-format=absolute --git-common-dir');
  if (!gitDir || !commonDir || gitDir === commonDir) return;

  const mergeBase = git('merge-base HEAD main') || git('merge-base HEAD origin/main');
  const changed = [
    ...(mergeBase ? git(`diff --name-only ${mergeBase}`).split('\n') : []),
    // Uncommitted changes count: they are equally absent from the stack.
    ...git('status --porcelain').split('\n').map((l) => l.slice(3)),
  ].filter(Boolean);

  const hits = (prefixes: string[]) =>
    [...new Set(changed.filter((p) => prefixes.some((s) => p.startsWith(s))))];
  const frontend = hits(FRONTEND_PATHS);
  const backend = hits(BACKEND_PATHS);
  if (frontend.length === 0 && backend.length === 0) return;

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
