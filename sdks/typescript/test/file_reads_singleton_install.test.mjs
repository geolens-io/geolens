/**
 * fix(P1 review of #2382): a caller who invokes a root-exported generated
 * download directly with a per-call `baseUrl` (an anonymous public file)
 * never calls createGeolensClient(), so the blob-parsing interceptor was
 * never installed on the generated singleton such a call falls back to. A
 * GLB then fell to JSON parsing (SyntaxError), contradicting the route's
 * declared `Blob | File` type.
 *
 * Kept in its own file, separate from file_reads.test.mjs: `node --test`
 * runs each file in its own process, but every test within ONE file shares
 * the same generated singleton. That file's other tests all call
 * createGeolensClient() first, which installs the same (idempotent)
 * interceptor — so a test living there would still pass even without the
 * module-load install in index.ts, silently losing its counterfactual.
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
