#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const configPath = path.join(repoRoot, 'frontend/src/i18n/config.ts');
const config = fs.readFileSync(configPath, 'utf8');

const supportedMatch = config.match(/supportedLngs\s*=\s*\[([^\]]+)\]\s*as const/);
if (!supportedMatch) {
  console.error(`Could not parse supportedLngs from ${path.relative(repoRoot, configPath)}`);
  process.exit(1);
}

const supportedLngs = [...supportedMatch[1].matchAll(/'([^']+)'/g)].map((match) => match[1]);
if (!supportedLngs.includes('en')) {
  console.error('README locale check expects en to be the canonical fallback language.');
  process.exit(1);
}

const expectedFiles = supportedLngs.map((lng) => (
  lng === 'en' ? 'README.md' : `README.${lng}.md`
));

let failed = false;
for (const file of expectedFiles) {
  if (!fs.existsSync(path.join(repoRoot, file))) {
    console.error(`Missing localized README: ${file}`);
    failed = true;
  }
}

const navPattern = expectedFiles.map((file) => `](${file})`);
for (const file of expectedFiles) {
  const readmePath = path.join(repoRoot, file);
  if (!fs.existsSync(readmePath)) continue;
  const text = fs.readFileSync(readmePath, 'utf8');
  for (const marker of navPattern) {
    if (!text.includes(marker)) {
      console.error(`${file} is missing language nav marker ${marker}`);
      failed = true;
    }
  }
}

if (failed) {
  process.exit(1);
}

console.log(`README locale coverage OK: ${expectedFiles.join(', ')}`);
