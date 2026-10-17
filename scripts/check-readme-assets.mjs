#!/usr/bin/env node
// check-readme-assets.mjs — gate over the committed README images in .github/assets/.
//
// Run: npm run check:readme-assets
//
// Asserts every committed README image is present and still exactly the size
// this file pins for it, and that no image sits in .github/assets/ unpinned.
// Needs no database, browser, or network — pure stdlib, safe anywhere.
//
// Some image tools resize a file in place when it is opened for viewing (the
// `image-sanitizer` Claude Code plugin shrinks anything over 1200px wide on
// Read), long after the capture that produced it. Only a check over the
// committed files sees that, so the gate pins exact sizes.
//
// Never open a master with an image-previewing tool. Measure with
// `sips -g pixelWidth -g pixelHeight`, and copy to a throwaway path first if you
// want to look at one.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const assetDir = path.join(repoRoot, '.github/assets');

// Every image committed under .github/assets/, with the size it must be on disk.
const README_ASSETS = {
  // Light and dark pairs, except QGIS, which has one theme. The provenance
  // shot is cropped to the Source panel.
  'geolens-manhattan-3d-hero.jpg': { width: 1600, height: 900 },
  'geolens-manhattan-3d-hero-dark.jpg': { width: 1600, height: 900 },
  'geolens-provenance.png': { width: 1600, height: 872 },
  'geolens-provenance-dark.png': { width: 1600, height: 872 },
  'geolens-qgis.png': { width: 1600, height: 900 },
  'geolens-ask-ai.png': { width: 1600, height: 900 },
  'geolens-ask-ai-dark.png': { width: 1600, height: 900 },
  // The "A closer look" grid.
  'geolens-catalog-search.png': { width: 1600, height: 900 },
  'geolens-catalog-search-dark.png': { width: 1600, height: 900 },
  'geolens-dataset-page.png': { width: 1600, height: 900 },
  'geolens-dataset-page-dark.png': { width: 1600, height: 900 },
  'geolens-import-preview.png': { width: 1600, height: 900 },
  'geolens-import-preview-dark.png': { width: 1600, height: 900 },
  'geolens-version-history.png': { width: 1600, height: 900 },
  'geolens-version-history-dark.png': { width: 1600, height: 900 },
  'geolens-builder-style.png': { width: 1600, height: 900 },
  'geolens-builder-style-dark.png': { width: 1600, height: 900 },
  'geolens-matterhorn-terrain.jpg': { width: 1600, height: 900 },
  'geolens-matterhorn-terrain-dark.jpg': { width: 1600, height: 900 },
  'geolens-stac-imagery.jpg': { width: 1600, height: 900 },
  'geolens-stac-imagery-dark.jpg': { width: 1600, height: 900 },
  'geolens-share-embed.png': { width: 1600, height: 900 },
  'geolens-share-embed-dark.png': { width: 1600, height: 900 },
  'geolens-admin-overview.png': { width: 1600, height: 900 },
  'geolens-admin-overview-dark.png': { width: 1600, height: 900 },
  'geolens-admin-permissions.png': { width: 1600, height: 900 },
  'geolens-admin-permissions-dark.png': { width: 1600, height: 900 },
};

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif']);

// PNG + JPEG header parse. Deliberately dependency-free: this gate has to run in
// a bare CI job with nothing installed, and shelling out to sips would tie it to
// macOS.
function readImageDimensions(file) {
  const buf = fs.readFileSync(file);
  if (buf.length > 24 && buf.toString('ascii', 1, 4) === 'PNG') {
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
  }
  if (buf.length > 4 && buf[0] === 0xff && buf[1] === 0xd8) {
    // Scan JPEG segments for the first SOF marker (0xC0-0xCF minus DHT/JPG/DAC).
    let off = 2;
    while (off + 9 < buf.length) {
      if (buf[off] !== 0xff) { off++; continue; }
      const marker = buf[off + 1];
      if (marker === 0xff) { off++; continue; }
      if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
        return { height: buf.readUInt16BE(off + 5), width: buf.readUInt16BE(off + 7) };
      }
      off += 2 + buf.readUInt16BE(off + 2);
    }
    throw new Error('no JPEG SOF marker found');
  }
  throw new Error('not a PNG or JPEG');
}

const failures = [];
const rows = [];

for (const [filename, expected] of Object.entries(README_ASSETS)) {
  const file = path.join(assetDir, filename);

  if (!fs.existsSync(file)) {
    failures.push(`${filename}: missing from .github/assets/`);
    continue;
  }

  let actual;
  try {
    actual = readImageDimensions(file);
  } catch (err) {
    failures.push(`${filename}: ${err instanceof Error ? err.message : String(err)}`);
    continue;
  }

  const ok = actual.width === expected.width && actual.height === expected.height;
  rows.push(
    `  ${ok ? 'ok  ' : 'FAIL'} ${filename.padEnd(34)} ${actual.width}x${actual.height}` +
      (ok ? '' : `  (expected ${expected.width}x${expected.height})`),
  );
  if (!ok) {
    failures.push(
      `${filename} is ${actual.width}x${actual.height} on disk; expected ${expected.width}x${expected.height}`,
    );
  }
}

// An unpinned image is an unguarded one, so it fails the gate. The manifest is
// keyed by bare filename, and AGENTS.md keeps README images flat in
// .github/assets/, so a subdirectory fails too rather than hiding images from
// the scan below.
const entries = fs.readdirSync(assetDir, { withFileTypes: true });

for (const entry of entries) {
  if (entry.isDirectory()) {
    failures.push(
      `${entry.name}/: .github/assets/ must stay flat — README images live directly in it ` +
        '(AGENTS.md), and a nested image would not be covered by this gate',
    );
  }
}

const onDisk = entries
  .filter((entry) => !entry.isDirectory())
  .map((entry) => entry.name)
  .filter((name) => IMAGE_EXTENSIONS.has(path.extname(name).toLowerCase()));
for (const name of onDisk) {
  if (!(name in README_ASSETS)) {
    failures.push(
      `${name}: committed in .github/assets/ but not pinned in ${path.basename(fileURLToPath(import.meta.url))} — ` +
        'add it with its dimensions so it is covered too',
    );
  }
}

console.log(`Verifying ${Object.keys(README_ASSETS).length} committed README images in .github/assets`);
for (const row of rows) console.log(row);

if (failures.length > 0) {
  console.error(`\nFAIL: ${failures.length} problem(s) with the committed README images:`);
  for (const line of failures) console.error(`  ${line}`);
  console.error(
    '\n  An image at exactly 1200px on its long edge was almost certainly resized in\n' +
      '  place when someone opened it. Restore it with\n' +
      '  `git checkout -- .github/assets/<file>` if it is committed correctly. Never open\n' +
      '  a master with an image-previewing tool — measure with\n' +
      '  `sips -g pixelWidth -g pixelHeight`, and copy to a throwaway path first if you\n' +
      '  want to look at it. .github/assets/README.md describes how the shots are made.',
  );
  process.exit(1);
}

console.log(`\nOK: all ${rows.length} README images are at their pinned size.`);
