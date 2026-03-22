import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..');
const repoRoot = runGit(['rev-parse', '--show-toplevel'], frontendRoot).trim();
const localeRoot = path.join(repoRoot, 'frontend', 'src', 'i18n', 'locales');

function runGit(args, cwd) {
  return execFileSync('git', args, {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

function tryRunGit(args, cwd) {
  try {
    return runGit(args, cwd).trim();
  } catch {
    return '';
  }
}

function resolveDiffRange() {
  const explicitRange = process.env.I18N_DIFF_RANGE?.trim();
  if (explicitRange) {
    return explicitRange;
  }

  const baseRef = process.env.GITHUB_BASE_REF?.trim();
  if (baseRef) {
    const remoteBase = `origin/${baseRef}`;
    const hasBase = tryRunGit(['rev-parse', '--verify', remoteBase], repoRoot);
    if (hasBase) {
      return `${remoteBase}...HEAD`;
    }
  }

  const hasParent = tryRunGit(['rev-parse', '--verify', 'HEAD^'], repoRoot);
  return hasParent ? 'HEAD^...HEAD' : '';
}

const diffRange = resolveDiffRange();
const committedChanges = diffRange
  ? tryRunGit(
      ['diff', '--name-only', '--diff-filter=ACMR', diffRange, '--', 'frontend/src/i18n/locales'],
      repoRoot,
    )
  : '';
const workingTreeChanges = tryRunGit(
  ['diff', '--name-only', '--diff-filter=ACMR', 'HEAD', '--', 'frontend/src/i18n/locales'],
  repoRoot,
);
const untrackedChanges = tryRunGit(
  ['ls-files', '--others', '--exclude-standard', '--', 'frontend/src/i18n/locales'],
  repoRoot,
);
const changedFilesOutput = [committedChanges, workingTreeChanges, untrackedChanges]
  .filter(Boolean)
  .join('\n');

if (!changedFilesOutput) {
  console.log('No locale file changes detected.');
  process.exit(0);
}

const changedNamespaces = new Set(
  changedFilesOutput
    .split('\n')
    .map((file) => file.match(/^frontend\/src\/i18n\/locales\/[^/]+\/([^/]+\.json)$/)?.[1] ?? null)
    .filter(Boolean),
);

if (changedNamespaces.size === 0) {
  console.log('No namespace bundle changes detected.');
  process.exit(0);
}

const languages = readdirSync(localeRoot, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .sort();

const missingBundles = [];

for (const namespaceFile of changedNamespaces) {
  for (const language of languages) {
    const bundlePath = path.join(localeRoot, language, namespaceFile);
    if (!existsSync(bundlePath)) {
      missingBundles.push(path.relative(repoRoot, bundlePath));
    }
  }
}

if (missingBundles.length > 0) {
  console.error('Changed i18n namespaces are missing bundles in some languages:');
  for (const bundlePath of missingBundles) {
    console.error(`- ${bundlePath}`);
  }
  process.exit(1);
}

console.log(
  `Changed namespaces exist across all locale directories: ${[...changedNamespaces].sort().join(', ')}`,
);
