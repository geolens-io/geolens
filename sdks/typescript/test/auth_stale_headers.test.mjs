/**
 * BUG-023: createGeolensClient must clear stale Authorization / X-API-Key
 * headers when the corresponding credential is NOT provided on a subsequent
 * call to the shared singleton client.
 *
 * Uses Node's built-in node:test runner (Node >= 18 required, per package.json).
 * Run: node --test test/auth_stale_headers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGeolensClient } from '../dist/auth.js';

const BASE_URL = 'https://example.test';

test('BUG-023: re-creating client without bearerToken clears stale Authorization header', () => {
  // 1. Create with a bearer token.
  const sdk1 = createGeolensClient({ baseUrl: BASE_URL, bearerToken: 'tok-first' });
  assert.equal(sdk1.headers['Authorization'], 'Bearer tok-first');

  // 2. Re-create WITHOUT a bearer token — Authorization must be gone from the
  //    singleton's headers (not just absent from the returned headers dict).
  const sdk2 = createGeolensClient({ baseUrl: BASE_URL });
  assert.equal(
    sdk2.headers['Authorization'],
    undefined,
    'Authorization header should be absent after re-create without bearerToken',
  );

  // Confirm the singleton config no longer has Authorization.
  const cfg = sdk2.client.getConfig();
  const hdrs = cfg.headers;
  let authValue;
  if (hdrs instanceof Headers) {
    authValue = hdrs.get('Authorization');
  } else if (hdrs && typeof hdrs === 'object') {
    authValue = hdrs['Authorization'] ?? hdrs['authorization'];
  }
  assert.ok(
    !authValue,
    `singleton client still has Authorization: ${authValue}`,
  );
});

test('BUG-023: re-creating client without apiKey clears stale X-API-Key header', () => {
  // 1. Create with an API key.
  const sdk1 = createGeolensClient({ baseUrl: BASE_URL, apiKey: 'key-first' });
  assert.equal(sdk1.headers['X-API-Key'], 'key-first');

  // 2. Re-create WITHOUT an API key — X-API-Key must be gone.
  const sdk2 = createGeolensClient({ baseUrl: BASE_URL });
  assert.equal(
    sdk2.headers['X-API-Key'],
    undefined,
    'X-API-Key header should be absent after re-create without apiKey',
  );

  const cfg = sdk2.client.getConfig();
  const hdrs = cfg.headers;
  let apiKeyValue;
  if (hdrs instanceof Headers) {
    apiKeyValue = hdrs.get('X-API-Key');
  } else if (hdrs && typeof hdrs === 'object') {
    apiKeyValue = hdrs['X-API-Key'] ?? hdrs['x-api-key'];
  }
  assert.ok(
    !apiKeyValue,
    `singleton client still has X-API-Key: ${apiKeyValue}`,
  );
});

test('BUG-023: switching from bearer token to API key works correctly', () => {
  const sdk1 = createGeolensClient({ baseUrl: BASE_URL, bearerToken: 'tok-a' });
  assert.equal(sdk1.headers['Authorization'], 'Bearer tok-a');

  const sdk2 = createGeolensClient({ baseUrl: BASE_URL, apiKey: 'key-b' });
  // Old Authorization must be gone; new X-API-Key must be present.
  assert.equal(
    sdk2.headers['Authorization'],
    undefined,
    'stale Authorization should be cleared when switching to API key',
  );
  assert.equal(sdk2.headers['X-API-Key'], 'key-b');
});
