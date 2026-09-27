/**
 * fix(#2361/#2374): the file-read routes (COG download, dataset export, a
 * 3D Tiles file, a COPC point cloud file) declare a binary body, but the
 * generated fetch client only infers a Blob from a handful of Content-Type
 * prefixes (`getParseAs`, client/client/utils.gen.ts). `installFileReadHandling`
 * (fileReads.ts), wired into every client `createGeolensClient()` returns,
 * forces these routes to parse as a Blob unless the caller asked for
 * something else (e.g. `parseAs: 'stream'` for a large download).
 *
 * A 304 from a conditional read is still an error to the generated client
 * (any non-2xx status is), and stays exactly that here — a synthesized
 * 204 made `ok` true while `status`/`clone().status` disagreed about what
 * actually happened. `notModified(result)` reads the real, unmodified
 * response instead, so a caller checks one thing rather than relying on
 * response identity the client itself doesn't preserve.
 *
 * Run: node --test test/file_reads.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGeolensClient } from '../dist/auth.js';
import { notModified } from '../dist/index.js';
import {
  getTilesetFileDatasetsDatasetIdTiles3dPathGet,
  exportDatasetEndpointDatasetsDatasetIdExportGet,
  getPointcloudFileDatasetsDatasetIdCopcAttemptIdNameCopcLazGet,
} from '../dist/client/sdk.gen.js';

const BASE_URL = 'https://example.test';

function mockFetch(respond) {
  return async (request) => respond(request);
}

async function blobText(blob) {
  return new TextDecoder().decode(new Uint8Array(await blob.arrayBuffer()));
}

test('a JSON tileset.json body parses as a Blob, not a parsed object', async () => {
  const sdk = createGeolensClient({ baseUrl: BASE_URL });
  const body = '{"asset": {"version": "1.1"}}';
  sdk.client.setConfig({
    fetch: mockFetch(() => new Response(body, { headers: { 'Content-Type': 'application/json' } })),
  });

  const result = await getTilesetFileDatasetsDatasetIdTiles3dPathGet({
    client: sdk.client,
    path: { dataset_id: 'd1', path: '0/tileset.json' },
  });

  assert.equal(result.error, undefined);
  assert.ok(result.data instanceof Blob, 'expected a Blob, got ' + typeof result.data);
  assert.equal(await blobText(result.data), body);
});

test('a GLB body (model/gltf-binary) parses as a Blob', async () => {
  const sdk = createGeolensClient({ baseUrl: BASE_URL });
  const bytes = new Uint8Array([0x67, 0x6c, 0x54, 0x46, 1, 2, 3, 4]); // "glTF" + filler
  sdk.client.setConfig({
    fetch: mockFetch(
      () => new Response(bytes, { headers: { 'Content-Type': 'model/gltf-binary' } }),
    ),
  });

  const result = await getTilesetFileDatasetsDatasetIdTiles3dPathGet({
    client: sdk.client,
    path: { dataset_id: 'd1', path: '0/content.glb' },
  });

  assert.equal(result.error, undefined);
  assert.ok(result.data instanceof Blob, 'expected a Blob, got ' + typeof result.data);
  assert.deepEqual(new Uint8Array(await result.data.arrayBuffer()), bytes);
});

test('a CSV export body parses as a Blob, not text', async () => {
  const sdk = createGeolensClient({ baseUrl: BASE_URL });
  const body = 'id,name\n1,origin\n';
  sdk.client.setConfig({
    fetch: mockFetch(() => new Response(body, { headers: { 'Content-Type': 'text/csv' } })),
  });

  const result = await exportDatasetEndpointDatasetsDatasetIdExportGet({
    client: sdk.client,
    path: { dataset_id: 'd1' },
    query: { format: 'csv' },
  });

  assert.equal(result.error, undefined);
  assert.ok(result.data instanceof Blob, 'expected a Blob, got ' + typeof result.data);
  assert.equal(await blobText(result.data), body);
});

test('an explicit parseAs is honoured, not overridden to blob', async () => {
  // fix(P1 review of #2382): the request interceptor used to force
  // parseAs: 'blob' unconditionally, which would buffer a large COG or
  // export in memory even when the caller explicitly asked to stream it.
  const sdk = createGeolensClient({ baseUrl: BASE_URL });
  const bytes = new Uint8Array([1, 2, 3, 4]);
  sdk.client.setConfig({
    fetch: mockFetch(() => new Response(bytes, { headers: { 'Content-Type': 'application/vnd.laszip+copc' } })),
  });

  const result = await getPointcloudFileDatasetsDatasetIdCopcAttemptIdNameCopcLazGet({
    client: sdk.client,
    path: { dataset_id: 'd1', attempt_id: 'a1', name: 'points' },
    parseAs: 'stream',
  });

  assert.equal(result.error, undefined);
  assert.ok(
    !(result.data instanceof Blob),
    'expected the explicit parseAs to survive, got a Blob',
  );
  assert.ok(
    result.data instanceof ReadableStream,
    `expected a ReadableStream, got ${typeof result.data}`,
  );
  assert.equal(result.data.locked, false, 'the body must not have been consumed already');
});

test('a 304 on a file route leaves the original Response, and notModified() reports it', async () => {
  const sdk = createGeolensClient({ baseUrl: BASE_URL });
  sdk.client.setConfig({
    fetch: mockFetch(
      () => new Response(null, { status: 304, headers: { etag: '"abc123"' } }),
    ),
  });

  const result = await getPointcloudFileDatasetsDatasetIdCopcAttemptIdNameCopcLazGet({
    client: sdk.client,
    path: { dataset_id: 'd1', attempt_id: 'a1', name: 'points' },
    headers: { 'If-None-Match': '"abc123"' },
  });

  // fix(P1 review of #2382): a synthesized 204 made `ok` true while
  // `status`/`clone().status` still disagreed about what happened — no
  // rewrite here, so every view of the response agrees: not ok, still 304.
  assert.equal(result.response.status, 304);
  assert.equal(result.response.ok, false);
  assert.equal(
    result.response.clone().status,
    304,
    'a clone must see the same status as the original',
  );
  assert.equal(result.response.headers.get('etag'), '"abc123"');
  assert.ok(notModified(result), 'notModified() must report the cache hit');
});

test('a 200 on a file route reports modified, with a Blob', async () => {
  const sdk = createGeolensClient({ baseUrl: BASE_URL });
  const bytes = new Uint8Array([1, 2, 3, 4]);
  sdk.client.setConfig({
    fetch: mockFetch(
      () => new Response(bytes, { headers: { 'Content-Type': 'application/vnd.laszip+copc' } }),
    ),
  });

  const result = await getPointcloudFileDatasetsDatasetIdCopcAttemptIdNameCopcLazGet({
    client: sdk.client,
    path: { dataset_id: 'd1', attempt_id: 'a1', name: 'points' },
  });

  assert.equal(result.error, undefined);
  assert.ok(result.data instanceof Blob, 'expected a Blob, got ' + typeof result.data);
  assert.ok(!notModified(result), 'notModified() must be false for a fresh download');
});
