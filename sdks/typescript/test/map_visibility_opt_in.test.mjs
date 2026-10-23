/**
 * Every client the SDK configures reads the restricted map visibility.
 *
 * Run: node --test test/map_visibility_opt_in.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGeolensClient } from '../dist/index.js';
import { client as singletonClient } from '../dist/client/client.gen.js';

async function sentHeaders(client) {
  const sent = [];
  client.setConfig({
    fetch: async (request) => {
      sent.push(request.headers);
      return new Response('{}', { headers: { 'content-type': 'application/json' } });
    },
  });
  await client.get({ url: '/maps/' });
  return sent[0];
}

test('the shared singleton opts in before createGeolensClient() runs', async () => {
  singletonClient.setConfig({ baseUrl: 'https://default.example.test' });
  const headers = await sentHeaders(singletonClient);
  assert.equal(headers.get('X-GeoLens-Map-Visibility'), 'restricted');
});

test('a scoped client and the singleton it reconfigures both opt in', async () => {
  const sdk = createGeolensClient({ baseUrl: 'https://maps.example.test', apiKey: 'key' });

  const scoped = await sentHeaders(sdk.client);
  const shared = await sentHeaders(singletonClient);

  assert.equal(scoped.get('X-GeoLens-Map-Visibility'), 'restricted');
  assert.equal(shared.get('X-GeoLens-Map-Visibility'), 'restricted');
  assert.equal(scoped.get('X-API-Key'), 'key');
});
