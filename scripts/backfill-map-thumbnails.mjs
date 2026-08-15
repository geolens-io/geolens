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

/**
 * Log in through the API. Returns the whole token payload, not just the access
 * token: the refresh token and expiry are what let the browser session renew
 * itself mid-batch (see the store seeding in main()).
 */
async function login() {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: USERNAME, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`);
  const payload = await res.json();
  if (!payload?.access_token) throw new Error('login returned no access_token');
  return payload;
}

const PAGE_SIZE = 200; // the endpoint's cap

/**
 * Every map the credential can see, following pagination to the end.
 *
 * fix(#1501 review): a single `?limit=200` returns only the first page. On an
 * instance with more maps than that, everything after page one was skipped
 * while the script still reported "N maps visible" and exited 0 — silently
 * doing a fraction of the job, which is worse than failing.
 */
async function listMaps(token) {
  const headers = { Authorization: `Bearer ${token}` };
  const all = [];
  for (let skip = 0; ; skip += PAGE_SIZE) {
    const res = await fetch(`${BASE_URL}/api/maps/?limit=${PAGE_SIZE}&skip=${skip}`, { headers });
    if (!res.ok) throw new Error(`GET /api/maps/ failed: ${res.status}`);
    const data = await res.json();
    const page = Array.isArray(data) ? data : (data.maps ?? data.items ?? []);
    all.push(...page);

    const total = Array.isArray(data) ? null : data.total;
    // Stop on a short page (covers a server that ignores `skip`) or once the
    // reported total is accounted for. Both, so neither alone can loop forever.
    if (page.length < PAGE_SIZE) break;
    if (typeof total === 'number' && all.length >= total) break;
  }
  return all;
}

/**
 * Node-side GET that re-authenticates once on 401.
 *
 * The polling below runs for the whole batch, so it outlives the access token
 * for the same reason the browser session does. Without this, every poll after
 * expiry returns 401 -> "no thumbnail" -> the script reports TIMED OUT for maps
 * whose capture actually succeeded. A false negative is worse than a failure
 * here, because it sends the operator looking for a rendering bug.
 */
let nodeToken = null;
async function authedGet(path) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: { Authorization: `Bearer ${nodeToken}` },
    });
    if (res.status !== 401) return res;
    nodeToken = (await login()).access_token;
  }
  return null;
}

/** Re-read one map's thumbnail_url; the auto-capture upload is what flips it. */
async function hasThumbnail(id) {
  const res = await authedGet(`/api/maps/${id}`);
  if (!res || !res.ok) return false;
  const m = await res.json();
  return Boolean(m.thumbnail_url);
}

async function main() {
  const auth = await login();
  const token = auth.access_token;
  nodeToken = token;
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
  //
  // fix(#1501 review): seed the REAL refresh token and expiry rather than null
  // and a hard-coded 15 minutes. Login happened in Node, so no refresh cookie
  // was installed in this browser; discarding the body refresh token left the
  // session with no way to renew and nothing to renew from. A backfill over
  // many maps easily outlives one access token — more so on an instance with
  // ACCESS_TOKEN_EXPIRE_MINUTES below the default — and every map after
  // expiry would fail its thumbnail PUT while the script kept going.
  //
  // With these seeded, apiFetch's own 401 -> refresh path keeps the session
  // alive for the whole batch using the mechanism the app already ships.
  await page.goto(`${BASE_URL}/`);
  const me = await (await fetch(`${BASE_URL}/api/auth/me/`, {
    headers: { Authorization: `Bearer ${token}` },
  })).json();
  await page.evaluate(
    ([tok, refresh, expiresIn, user]) => {
      localStorage.setItem(
        'geolens-auth',
        JSON.stringify({
          state: {
            token: tok,
            refreshToken: refresh ?? null,
            expiresAt: Date.now() + (expiresIn ?? 900) * 1000,
            user,
          },
          version: 1,
        }),
      );
    },
    [token, auth.refresh_token ?? null, auth.expires_in ?? null, me],
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
        if (await hasThumbnail(m.id)) { ok = true; break; }
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
