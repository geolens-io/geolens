#!/usr/bin/env node
// check-readme-assets.mjs — gate over the committed README images in .github/assets/.
//
// Run: npm run check:readme-assets
//
// Asserts every committed README image is present and still exactly the size
// this file pins for it, and that no image sits in .github/assets/ unpinned.
// Needs no database, browser, or network — pure stdlib, safe anywhere.
//
// WHY A GATE OVER THE COMMITTED FILES
//
// The `image-sanitizer` Claude Code plugin registers a PreToolUse hook on the
// Read TOOL. Before a read is served it runs, in place:
//     magick <file> -resize "${CLAUDE_IMAGE_MAX_DIMENSION:-1200}x...>"
// on any path with an image extension. Shrink-only, aspect preserved, 1200px
// cap. So the rewrite is synchronous and deterministic — not a race — and it is
// triggered by somebody choosing to eyeball a committed image, which usually
// happens long after whatever produced it exited. Only a check you can run at
// commit time sees that.
//
// This is the third such gate. docs (getgeolens.com/docs) has verify-build.sh
// QUICK-03; marketing (getgeolens.com) has scripts/verify-screenshots.mjs. The
// README shots were the one unguarded surface, because they are produced in one
// repo (getgeolens.com/scripts/capture-readme.ts) and committed in another
// (here). The gate belongs where the files are committed and where CI can run it
// on every PR — so, here.
//
// Note this is a VERIFICATION script, not a capture script: .github/assets/README.md
// asks that capture tooling stay out of this public repo, and it does. Nothing
// here launches a browser or talks to a GeoLens.
//
// The operator rule this enforces: never open a master with an image-previewing
// tool. Measure with `sips -g pixelWidth -g pixelHeight`, and copy to a throwaway
// path first if you want to look at one.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const assetDir = path.join(repoRoot, '.github/assets');

// Every image committed under .github/assets/, with the size it must be on disk.
//
// `capturedAt` records the size the upstream capture recipe DECLARES for a shot,
// when that differs from what is committed. It is documentation of a known
// deficit, not a second assertion: the gate pins `width`/`height` so nothing can
// degrade further, and reports the gap so it stays visible instead of being
// silently blessed. Clear a `capturedAt` by recapturing and updating
// `width`/`height` to match it in the same commit.
const README_ASSETS = {
  // --- The five targets of getgeolens.com/scripts/capture-readme.ts ---------
  // That script declares `const VP = { width: 1600, height: 900 }` for all five,
  // and .github/assets/README.md documents "Sources are captured at 1600x900".
  // What is committed is neither: 1200x750 is a 1.6 aspect, and 1200x800 is 1.5,
  // while 1600x900 is 1.778. A sanitizer pass over a 1600x900 master lands at
  // 1200x675 (measured), so these are not downscales of the current recipe —
  // they are downscales of an older, differently-shaped hand capture. Git agrees:
  // at #205 (2026-06-07) four of them were 1200x675, i.e. genuinely 1600x900
  // shrunk; they became 1200x750 at #407 (2026-07-06) and have not moved since.
  //
  // They are pinned here at their committed size rather than at 1600x900 so this
  // gate lands green and starts protecting the other ten images immediately. See
  // the PR for why the recapture is a separate change.
  'geolens-manhattan-3d-hero.jpg': { width: 1200, height: 750, capturedAt: { width: 1600, height: 900 } },
  'geolens-search.png': { width: 1200, height: 750, capturedAt: { width: 1600, height: 900 } },
  'geolens-dataset.png': { width: 1200, height: 750, capturedAt: { width: 1600, height: 900 } },
  'geolens-matterhorn-terrain.jpg': { width: 1200, height: 750, capturedAt: { width: 1600, height: 900 } },
  'geolens-ai-labels.png': { width: 1200, height: 800, capturedAt: { width: 1600, height: 900 } },

  // --- Hand-captured, added 2026-07-23 (#659) ------------------------------
  // Not part of capture-readme.ts's target list; .github/assets/README.md
  // documents them at 1200x750, which is what is on disk. 1200 is exactly the
  // sanitizer's cap, so they are already immune to it — pinned here to catch
  // replacement and deletion.
  'geolens-dataset-chat.png': { width: 1200, height: 750 },
  'geolens-dataset-chat-dark.png': { width: 1200, height: 750 },
  'geolens-admin-overview.png': { width: 1200, height: 750 },
  'geolens-admin-overview-dark.png': { width: 1200, height: 750 },
  'geolens-admin-users.png': { width: 1200, height: 750 },
  'geolens-admin-users-dark.png': { width: 1200, height: 750 },

  // --- Source-panel crops, added 2026-08-08 (#1279, #1280) -----------------
  // These are the ones currently AT RISK: 1232 > 1200, so a single Read on any
  // of the three would shrink it to 1200 wide. That is the immediate value of
  // this gate.
  'source-panel-service.png': { width: 1232, height: 522 },
  'source-panel-vrt.png': { width: 1232, height: 619 },
  'source-state-dataset-header.png': { width: 1232, height: 116 },
  'source-state-search-chips.png': { width: 760, height: 176 },
};

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif']);

// PNG + JPEG header parse. Deliberately dependency-free: this gate has to run in
// a bare CI job with nothing installed, and shelling out to sips would tie it to
// macOS. Mirrors readImageDimensions() in getgeolens.com/scripts/lib/capture-core.mjs.
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
const deficits = [];

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
  } else if (expected.capturedAt) {
    deficits.push(
      `${filename}: pinned at ${expected.width}x${expected.height}, but the capture recipe ` +
        `declares ${expected.capturedAt.width}x${expected.capturedAt.height}`,
    );
  }
}

// A new image that nobody pinned is a new unguarded surface — which is the exact
// hole this gate exists to close. Fail rather than ignore it.
const onDisk = fs
  .readdirSync(assetDir)
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
      '  place by the image-sanitizer plugin, which hooks the Read tool. Restore it with\n' +
      '  `git checkout -- .github/assets/<file>` if it is committed correctly. Never open\n' +
      '  a master with an image-previewing tool — measure with\n' +
      '  `sips -g pixelWidth -g pixelHeight`, and copy to a throwaway path first if you\n' +
      '  want to look at it. The capture recipe lives in the getgeolens.com repo\n' +
      '  (`npm run capture:readme`); see .github/assets/README.md.',
  );
  process.exit(1);
}

if (deficits.length > 0) {
  console.log(`\n${deficits.length} image(s) are pinned below their declared capture size:`);
  for (const line of deficits) console.log(`  - ${line}`);
  console.log('  Recapture with `npm run capture:readme` from the getgeolens.com repo, then');
  console.log('  update width/height here and drop the capturedAt entry in the same commit.');
}

console.log(`\nOK: all ${rows.length} README images are at their pinned size.`);
