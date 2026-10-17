/**
 * createGeolensClient() must ALSO reconfigure
 * the generated module's shared singleton, in addition to returning a
 * scoped client. Existing consumers that call
 * createGeolensClient() once and then call generated endpoints WITHOUT
 * passing `{ client: sdk.client }` rely on the singleton fallback
 * (`options?.client ?? client`, sdk.gen.ts) — losing that fallback would break
 * every implicit call, hitting whatever baseUrl (or none) the singleton
 * last had.
 *
 * Run: node --test test/auth_legacy_singleton.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGeolensClient } from '../dist/auth.js';
import { client as singletonClient } from '../dist/client/client.gen.js';

test('createGeolensClient() also configures the shared singleton for implicit (no-client) callers', () => {
  createGeolensClient({
    baseUrl: 'https://legacy.example.test',
    bearerToken: 'tok-legacy',
  });

  const cfg = singletonClient.getConfig();
  assert.equal(cfg.baseUrl, 'https://legacy.example.test');
  const hdrs = cfg.headers;
  const authValue = hdrs instanceof Headers ? hdrs.get('Authorization') : hdrs?.['Authorization'];
  assert.equal(authValue, 'Bearer tok-legacy');
});

test('a later createGeolensClient() call updates the singleton too (last caller wins, as before)', () => {
  createGeolensClient({ baseUrl: 'https://first.example.test', bearerToken: 'tok-first' });
  createGeolensClient({ baseUrl: 'https://second.example.test', apiKey: 'key-second' });

  const cfg = singletonClient.getConfig();
  assert.equal(cfg.baseUrl, 'https://second.example.test');
  const hdrs = cfg.headers;
  const apiKeyValue = hdrs instanceof Headers ? hdrs.get('X-API-Key') : hdrs?.['X-API-Key'];
  const authValue = hdrs instanceof Headers ? hdrs.get('Authorization') : hdrs?.['Authorization'];
  assert.equal(apiKeyValue, 'key-second');
  assert.ok(!authValue, `singleton still carries the first caller's Authorization: ${authValue}`);
});

test('the shared singleton sends no credential left over from a previous caller', async () => {
  const sent = [];
  const record = async (request) => {
    sent.push(request.headers);
    return new Response('{}', { headers: { 'content-type': 'application/json' } });
  };

  createGeolensClient({ baseUrl: 'https://wire.example.test', bearerToken: 'tok-old' });
  createGeolensClient({ baseUrl: 'https://wire.example.test', apiKey: 'key-new' });
  singletonClient.setConfig({ fetch: record });
  await singletonClient.get({ url: '/ping' });
  assert.equal(sent[0].get('Authorization'), null);
  assert.equal(sent[0].get('X-API-Key'), 'key-new');

  createGeolensClient({ baseUrl: 'https://wire.example.test', bearerToken: 'tok-new' });
  singletonClient.setConfig({ fetch: record });
  await singletonClient.get({ url: '/ping' });
  assert.equal(sent[1].get('X-API-Key'), null);
  assert.equal(sent[1].get('Authorization'), 'Bearer tok-new');
});
