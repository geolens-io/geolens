import { execFileSync } from 'node:child_process';

// fix(#1480): a worktree e2e run silently tests whatever the shared stack is
// serving, which is the MAIN checkout.
//
// The dev stack bind-mounts the main checkout (`./frontend` -> /app, and
// `backend/app` -> /app/app with --reload), so it serves main's code no matter
// which branch a linked worktree is on. That yields false failures when your
// fix is absent from the stack and — worse, because nothing distinguishes it
// from a real pass — false passes when your break is.
//
// This deliberately does NOT try to work out whether your changes happen to be
// in the stack. An earlier revision did, comparing git metadata and then file
// bytes between the two trees, and review found eleven separate ways for that
// answer to be wrong: rename detection hiding an endpoint, porcelain's leading
// status column, a missing merge base, HEAD versus working tree, byte-identical
// branches, collapsed untracked directories, symlinks compared through their
// targets, and a configurable FRONTEND_PORT. That surface is unbounded because
// it spans git reporting, filesystem semantics and compose configuration.
//
// So it asks the one question it can answer reliably — am I in a linked
// worktree — and requires an explicit acknowledgement to proceed. Blocking a
// run that would have been fine costs one environment variable. Allowing a run
// that reports on code you did not write costs a wrong answer you cannot see.

function git(args: string[]): string {
  try {
    return execFileSync('git', args, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return '';
  }
}

/**
 * Throws when running from a linked git worktree without an explicit
 * acknowledgement. Call from the top level of EVERY Playwright config —
 * `npm run e2e:smoke:builder-hardening` selects its own with `-c`.
 */
export function assertWorktreeMatchesStack(): void {
  if (process.env.E2E_ALLOW_WORKTREE) return;

  // Equal in the main checkout; in a linked worktree git-dir is
  // <common>/worktrees/<name>. Also returns early outside a repo, and in CI,
  // where the checkout is ordinary and this must never fire.
  const gitDir = git(['rev-parse', '--absolute-git-dir']);
  const commonDir = git(['rev-parse', '--path-format=absolute', '--git-common-dir']);
  if (!gitDir || !commonDir || gitDir === commonDir) return;

  const target = process.env.E2E_BASE_URL ?? 'http://localhost:8080 (default)';
  throw new Error(
    [
      'Refusing to run e2e from a linked git worktree without acknowledgement.',
      '',
      `  worktree:  ${git(['rev-parse', '--show-toplevel'])}`,
      `  target:    ${target}`,
      '',
      "The dev stack bind-mounts the MAIN checkout, so it serves main's code",
      "regardless of this worktree's branch. A run against it reports on code",
      'that is not yours — as a false failure, or as a false pass that looks',
      'exactly like a real one.',
      '',
      "To exercise this worktree's FRONTEND code, run Vite from here and point",
      'the tests at it:',
      '  cd frontend && API_PROXY_TARGET=http://localhost:8001 npm run dev -- --port 5174',
      '  E2E_ALLOW_WORKTREE=1 E2E_BASE_URL=http://localhost:5174 npx playwright test',
      '',
      "That recipe is frontend-only: :8001 is the main checkout's API container,",
      'so a change under backend/app/ or backend/alembic/ still would not be',
      'under test. Exercising a worktree BACKEND change needs a stack built from',
      'this worktree — a separate compose project with its own ports, or a',
      "host-run API serving this worktree's backend.",
      '',
      'If you have already pointed at the right stack, or you are running',
      'spec-only changes against the shared one on purpose:',
      '  E2E_ALLOW_WORKTREE=1 npx playwright test',
    ].join('\n'),
  );
}
