#!/usr/bin/env node
// backfill-map-thumbnails.mjs — give seeded maps the thumbnail they never got.
//
// WHY THIS EXISTS
//
// A map thumbnail has exactly one producer: the builder's client-side
// auto-capture (`use-builder-save.ts`), which fires on first load when
// `hasThumbnail` is false, crops the WebGL canvas to 400x250, and PUTs it to
// /maps/{id}/thumbnail/. There is no server-side path, and `seed-showcase.py`
// creates none — it never mentions thumbnails at all.
//
// So a map has a thumbnail if and only if a browser has opened it. That splits
// a seeded instance in a way nobody intends:
//
//   public showcase maps  -> opened by visitors and capture runs -> have one
//   private maps          -> only the owner can open them, and the owner is a
//                            seeding script -> never get one, and the gallery
//                            renders a grey placeholder forever
//
// This script is the missing producer. It opens each thumbnail-less map once,
// in a real browser, and lets the app's own code path do the work — nothing
// here fabricates an image or writes the column directly.
//
// Usage:
//   GEOLENS_URL=https://demo.example.com \
//   GEOLENS_ADMIN_USERNAME=... GEOLENS_ADMIN_PASSWORD=... \
//   node scripts/backfill-map-thumbnails.mjs [--dry-run] [--include-public]
//
// Defaults to every map the credential can see that is missing a thumbnail.
// --dry-run lists what it would open and changes nothing.

import { chromium } from 'playwright';

const BASE_URL = (process.env.GEOLENS_URL ?? 'http://localhost:8080').replace(/\/+$/, '');
const USERNAME = process.env.GEOLENS_ADMIN_USERNAME ?? 'admin';
const PASSWORD = process.env.GEOLENS_ADMIN_PASSWORD;
const DRY_RUN = process.argv.includes('--dry-run');

// How long to wait for auto-capture to upload. The capture runs after the map
// idles, so this is map-render time plus the PUT, not a fixed cost we control.
const CAPTURE_TIMEOUT_MS = 45_000;
const POLL_MS = 1_500;

if (!PASSWORD) {
  console.error('FAIL: GEOLENS_ADMIN_PASSWORD is required.');
  process.exit(2);
}

/** Log in through the API and return the bearer token. */
async function login() {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: USERNAME, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`);
  const { access_token: token } = await res.json();
  if (!token) throw new Error('login returned no access_token');
  return token;
}

async function listMaps(token) {
  const res = await fetch(`${BASE_URL}/api/maps/?limit=200`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`GET /api/maps/ failed: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : (data.maps ?? data.items ?? []);
}

/** Re-read one map's thumbnail_url; the auto-capture upload is what flips it. */
async function hasThumbnail(token, id) {
  const res = await fetch(`${BASE_URL}/api/maps/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return false;
  const m = await res.json();
  return Boolean(m.thumbnail_url);
}

async function main() {
  const token = await login();
  const maps = await listMaps(token);
  const missing = maps.filter((m) => !m.thumbnail_url);

  console.log(`${BASE_URL}: ${maps.length} maps visible, ${missing.length} without a thumbnail`);
  if (missing.length === 0) {
    console.log('Nothing to do.');
    return;
  }
  for (const m of missing) {
    console.log(`  - ${m.visibility ?? '?'}  ${m.name}`);
  }
  if (DRY_RUN) {
    console.log('\n--dry-run: opened nothing.');
    return;
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await context.newPage();

  // Seed the auth store the same way a signed-in browser holds it, so the
  // builder's own fetches (and the thumbnail PUT) are authenticated.
  await page.goto(`${BASE_URL}/`);
  await page.evaluate(
    ([tok, user]) => {
      localStorage.setItem(
        'geolens-auth',
        JSON.stringify({
          state: { token: tok, refreshToken: null, expiresAt: Date.now() + 15 * 60_000, user },
          version: 1,
        }),
      );
    },
    [token, await (await fetch(`${BASE_URL}/api/auth/me/`, { headers: { Authorization: `Bearer ${token}` } })).json()],
  );

  let filled = 0;
  const failed = [];
  for (const m of missing) {
    process.stdout.write(`  opening ${m.name} ... `);
    try {
      await page.goto(`${BASE_URL}/maps/${m.id}`);
      await page.waitForLoadState('networkidle').catch(() => {});

      // Poll the API rather than guessing at a fixed wait: the upload is
      // fire-and-forget inside the app, so its completion is only observable
      // as thumbnail_url flipping non-null.
      const deadline = Date.now() + CAPTURE_TIMEOUT_MS;
      let ok = false;
      while (Date.now() < deadline) {
        await page.waitForTimeout(POLL_MS);
        if (await hasThumbnail(token, m.id)) { ok = true; break; }
      }
      if (ok) { filled++; console.log('ok'); }
      else { failed.push(m.name); console.log('TIMED OUT'); }
    } catch (err) {
      failed.push(m.name);
      console.log(`ERROR ${err?.message ?? err}`);
    }
  }

  await browser.close();

  console.log(`\nFilled ${filled}/${missing.length}.`);
  if (failed.length > 0) {
    console.error('Still missing a thumbnail:');
    for (const n of failed) console.error(`  - ${n}`);
    // Non-zero so a CI or cron caller notices, without pretending the run
    // achieved nothing: the count above says what did land.
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(`FAIL: ${err?.message ?? err}`);
  process.exit(2);
});
