import { lstatSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';

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
// answer to be wrong. That surface is unbounded: it spans git reporting,
// filesystem semantics and compose configuration.
//
// It also does not shell out to git. The first simplification did, and review
// found that a `rev-parse` failure — an older git without `--path-format`, or a
// `safe.directory` ownership rejection — turned into an empty string and
// silently disabled the guard, which is the same false pass in a new costume.
//
// Detection is a filesystem fact instead. A linked worktree's `.git` is a FILE
// containing `gitdir: /…/.git/worktrees/<name>`; the main checkout's `.git` is
// a DIRECTORY. No subprocess, no git version dependency, no ownership checks,
// and anything unexpected fails closed.

const ACKNOWLEDGED = new Set(['1', 'true', 'yes', 'on']);

export type Marker = { dir: string; kind: 'directory' | 'file' | 'unreadable' };

// fix(#1492) round thirteen: ONLY "there is nothing here" may continue the
// walk. An earlier revision caught every stat error and walked past, so an
// inaccessible or dangling `.git` allowed the run — the same fail-open the git
// version had, relocated to the filesystem, and contradicting this module's
// own claim that unclassifiable entries block.
const NOT_HERE = new Set(['ENOENT', 'ENOTDIR']);

/** Nearest `.git` at or above `start`, or null if there is genuinely none. Exported for testing. */
export function findGitMarker(start: string): Marker | null {
  let dir = start;
  for (;;) {
    const marker = join(dir, '.git');
    try {
      // lstat, so a dangling symlink is still an entry that EXISTS and must be
      // classified rather than walked past as absent.
      const st = lstatSync(marker);
      if (st.isSymbolicLink()) {
        try {
          return { dir, kind: statSync(marker).isDirectory() ? 'directory' : 'file' };
        } catch {
          return { dir, kind: 'unreadable' }; // dangling or unresolvable
        }
      }
      return { dir, kind: st.isDirectory() ? 'directory' : 'file' };
    } catch (err) {
      const code = (err as NodeJS.ErrnoException)?.code;
      if (!NOT_HERE.has(code ?? '')) return { dir, kind: 'unreadable' };
      // genuinely absent here; keep walking up
    }
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/**
 * Throws when running from a linked git worktree without an explicit
 * acknowledgement. Call from the top level of EVERY Playwright config —
 * `npm run e2e:smoke:builder-hardening` selects its own with `-c`.
 */
export function assertWorktreeMatchesStack(): void {
  // fix(#1492) round fourteen: any non-empty string is truthy, so
  // E2E_ALLOW_WORKTREE=0 or =false — which a shell or CI profile may set to
  // mean "off" — used to bypass the guard entirely. Only an affirmative value
  // acknowledges; everything else, including 0 and false, does not.
  if (ACKNOWLEDGED.has((process.env.E2E_ALLOW_WORKTREE ?? '').trim().toLowerCase())) return;

  const marker = findGitMarker(process.cwd());
  // No .git anywhere above us: not a git checkout, so there is no worktree to
  // confuse. A tarball install is a legitimate case and must keep working.
  if (marker === null) return;
  // A real directory is the main checkout, which is what the stack serves.
  if (marker.kind === 'directory') return;
  // A .git file is a linked worktree (or a submodule); 'unreadable' is an entry
  // we could not classify. Both block — that is the fail-closed contract.

  const target = process.env.E2E_BASE_URL ?? 'http://localhost:8080 (default)';
  throw new Error(
    [
      'Refusing to run e2e from a linked git worktree without acknowledgement.',
      '',
      `  ${marker.kind === 'unreadable' ? 'unclassifiable .git in' : 'worktree: '}  ${marker.dir}`,
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
