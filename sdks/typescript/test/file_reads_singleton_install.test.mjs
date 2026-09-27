/**
 * A generated download called directly, without createGeolensClient(),
 * still returns a Blob. This lives in its own file because node --test
 * shares one process per file, and file_reads.test.mjs's other tests
 * install the handler on the same singleton first.
 *
 * Run: node --test test/file_reads_singleton_install.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getTilesetFileDatasetsDatasetIdTiles3dPathGet } from '../dist/index.js';

const BASE_URL = 'https://example.test';

function mockFetch(respond) {
  return async (request) => respond(request);
}

test('a GLB body parses as a Blob via a direct call, without createGeolensClient()', async () => {
  const bytes = new Uint8Array([0x67, 0x6c, 0x54, 0x46, 1, 2, 3, 4]); // "glTF" + filler

  const result = await getTilesetFileDatasetsDatasetIdTiles3dPathGet({
    baseUrl: BASE_URL,
    fetch: mockFetch(
      () => new Response(bytes, { headers: { 'Content-Type': 'model/gltf-binary' } }),
    ),
    path: { dataset_id: 'd1', path: '0/content.glb' },
  });

  assert.equal(result.error, undefined);
  assert.ok(result.data instanceof Blob, 'expected a Blob, got ' + typeof result.data);
  assert.deepEqual(new Uint8Array(await result.data.arrayBuffer()), bytes);
});
