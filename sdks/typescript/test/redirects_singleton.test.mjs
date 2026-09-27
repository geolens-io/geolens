/**
 * A generated call made without createGeolensClient() uses the shared
 * singleton, which follows redirects the same way: nothing the request
 * carried reaches another origin. Its own file because node --test shares
 * one process per file, and redirects.test.mjs installs the handling on
 * the same singleton through createGeolensClient() first.
 *
 * Run: node --test test/redirects_singleton.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { downloadCogDatasetsDatasetIdDownloadCogGet as downloadCog } from '../dist/index.js';

const BODY = new Uint8Array([0x49, 0x49, 0x2a, 0x00, 1, 2, 3, 4]);

function listen(handler) {
  const server = http.createServer(handler);
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

test('a direct generated call sends no credentials to a cross-origin target', async () => {
  const seen = [];
  const storage = await listen((req, res) => {
    seen.push(req.headers);
    res.end(BODY);
  });
  const api = await listen((req, res) => {
    res.writeHead(302, { location: `http://127.0.0.1:${storage.address().port}/cog.tif` });
    res.end();
  });
  const credential = randomUUID();

  try {
    const result = await downloadCog({
      baseUrl: `http://127.0.0.1:${api.address().port}`,
      headers: { 'X-API-Key': credential },
      path: { dataset_id: 'd1' },
    });

    assert.equal(result.error, undefined);
    assert.deepEqual(new Uint8Array(await result.data.arrayBuffer()), BODY);
    assert.equal(seen.length, 1);
    assert.equal(seen[0]['x-api-key'], undefined);
    assert.ok(!Object.values(seen[0]).join(' ').includes(credential));
  } finally {
    api.close();
    storage.close();
  }
});
