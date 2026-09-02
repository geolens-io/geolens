/**
 * fix(#1778): createGeolensClient() must return a client scoped to that
 * call. Before this fix, every call reconfigured one module-level
 * singleton, so a second concurrent caller (e.g. a per-request client in a
 * Node server) overwrote the first caller's credentials and base URL on
 * the object the first caller was still holding a reference to.
 *
 * Run: node --test test/auth_concurrent_clients.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGeolensClient } from '../dist/auth.js';

test('a second createGeolensClient() call does not mutate an earlier caller\'s client', () => {
  const sdkA = createGeolensClient({
    baseUrl: 'https://tenant-a.test',
    bearerToken: 'tok-a',
  });

  // A second, unrelated caller configures its own client with different
  // credentials and a different base URL.
  const sdkB = createGeolensClient({
    baseUrl: 'https://tenant-b.test',
    apiKey: 'key-b',
  });

  assert.notEqual(
    sdkA.client,
    sdkB.client,
    'each createGeolensClient() call must return a distinct client instance',
  );

  // sdkA's own client object must still carry sdkA's credentials/base URL,
  // unaffected by sdkB having been created afterwards.
  const cfgA = sdkA.client.getConfig();
  assert.equal(cfgA.baseUrl, 'https://tenant-a.test');
  const hdrsA = cfgA.headers;
  const authA = hdrsA instanceof Headers ? hdrsA.get('Authorization') : hdrsA?.['Authorization'];
  const apiKeyA = hdrsA instanceof Headers ? hdrsA.get('X-API-Key') : hdrsA?.['X-API-Key'];
  assert.equal(authA, 'Bearer tok-a');
  assert.ok(!apiKeyA, `sdkA client picked up sdkB's X-API-Key: ${apiKeyA}`);

  const cfgB = sdkB.client.getConfig();
  assert.equal(cfgB.baseUrl, 'https://tenant-b.test');
  const hdrsB = cfgB.headers;
  const apiKeyB = hdrsB instanceof Headers ? hdrsB.get('X-API-Key') : hdrsB?.['X-API-Key'];
  assert.equal(apiKeyB, 'key-b');
});
