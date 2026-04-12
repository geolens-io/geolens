import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..');
const gitRepoRoot = tryRunGit(['rev-parse', '--show-toplevel'], frontendRoot);
const repoRoot = gitRepoRoot || path.resolve(frontendRoot, '..');
const localeRoot = path.join(frontendRoot, 'src', 'i18n', 'locales');

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
  if (!gitRepoRoot) {
    return '';
  }

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

function collectLanguages() {
  return readdirSync(localeRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

function collectAllNamespaces(languages) {
  const namespaces = new Set();

  for (const language of languages) {
    const languageRoot = path.join(localeRoot, language);
    for (const entry of readdirSync(languageRoot, { withFileTypes: true })) {
      if (entry.isFile() && entry.name.endsWith('.json')) {
        namespaces.add(entry.name);
      }
    }
  }

  return namespaces;
}

const languages = collectLanguages();
const diffRange = resolveDiffRange();
const committedChanges =
  gitRepoRoot && diffRange
    ? tryRunGit(
        ['diff', '--name-only', '--diff-filter=ACMR', diffRange, '--', 'frontend/src/i18n/locales'],
        repoRoot,
      )
    : '';
const workingTreeChanges = gitRepoRoot
  ? tryRunGit(
      ['diff', '--name-only', '--diff-filter=ACMR', 'HEAD', '--', 'frontend/src/i18n/locales'],
      repoRoot,
    )
  : '';
const untrackedChanges = gitRepoRoot
  ? tryRunGit(
      ['ls-files', '--others', '--exclude-standard', '--', 'frontend/src/i18n/locales'],
      repoRoot,
    )
  : '';
const changedFilesOutput = [committedChanges, workingTreeChanges, untrackedChanges]
  .filter(Boolean)
  .join('\n');

let changedNamespaces;

if (!gitRepoRoot) {
  changedNamespaces = collectAllNamespaces(languages);
  console.warn('Git metadata unavailable; checking all locale namespaces for parity.');
} else if (!changedFilesOutput) {
  console.log('No locale file changes detected.');
  process.exit(0);
} else {
  changedNamespaces = new Set(
    changedFilesOutput
      .split('\n')
      .map((file) => file.match(/^frontend\/src\/i18n\/locales\/[^/]+\/([^/]+\.json)$/)?.[1] ?? null)
      .filter(Boolean),
  );
}

if (changedNamespaces.size === 0) {
  console.log('No namespace bundle changes detected.');
  process.exit(0);
}

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
