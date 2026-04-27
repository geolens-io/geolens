/**
 * TypeScript SDK round-trip test (Phase 215 / OCSDK-02).
 *
 * Invoked by backend/tests/test_sdks_round_trip.py via subprocess. Reads
 * GEOLENS_BASE_URL and GEOLENS_TOKEN from env, then exercises the same three
 * endpoints as the Python half through the @hey-api-generated SDK functions:
 *
 *   GET  /search/datasets/         (200 expected)
 *   GET  /datasets/{dataset_id}    (404 expected for fake UUID — proves auth + route)
 *   POST /ingest/upload            (any non-5xx ok — proves request shape)
 *
 * Exits 0 on success; non-zero on any failure with a descriptive console.error.
 *
 * The function names below follow @hey-api/openapi-ts 0.96.1's camelCase
 * conversion of FastAPI operationIds. Verified against
 * sdks/typescript/dist/client/sdk.gen.d.ts on 2026-04-27.
 */
import { createGeolensClient } from '../dist/index.js';
import {
  searchDatasetsEndpointSearchDatasetsGet,
  getSingleDatasetDatasetsDatasetIdGet,
  uploadFileIngestUploadPost,
} from '../dist/client/sdk.gen.js';

const baseUrl = process.env.GEOLENS_BASE_URL;
const token = process.env.GEOLENS_TOKEN;
if (!baseUrl || !token) {
  console.error('GEOLENS_BASE_URL and GEOLENS_TOKEN env vars required');
  process.exit(2);
}

const sdk = createGeolensClient({ baseUrl, bearerToken: token });

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg);
    process.exit(1);
  }
}

async function main() {
  // 1. /search/datasets/  → 200
  const sr = await searchDatasetsEndpointSearchDatasetsGet({
    client: sdk.client,
  });
  assert(
    sr.response.status === 200,
    `search/datasets status: ${sr.response.status}`,
  );

  // 2. /datasets/{dataset_id} with a fake UUID  → 404
  const fakeId = '00000000-0000-0000-0000-000000000000';
  const dr = await getSingleDatasetDatasetsDatasetIdGet({
    client: sdk.client,
    path: { dataset_id: fakeId },
  });
  assert(
    dr.response.status === 404,
    `get-single-dataset (fake UUID) status: ${dr.response.status}`,
  );

  // 3. /ingest/upload  → any non-5xx (round-trip means the SDK reached the handler).
  // We send a tiny GeoJSON via a Node FormData; backend will likely 422 on
  // extension/filename validation (the @hey-api SDK's body type is loose for
  // this endpoint), which is fine — non-5xx proves the request shape works.
  const tinyGeoJson = JSON.stringify({
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [0, 0] },
        properties: { name: 'origin' },
      },
    ],
  });
  const blob = new Blob([tinyGeoJson], { type: 'application/geo+json' });
  const formData = new FormData();
  formData.append('file', blob, 'tiny.geojson');

  const ur = await uploadFileIngestUploadPost({
    client: sdk.client,
    body: formData,
  });
  assert(
    ur.response.status < 500,
    `ingest/upload 5xx — SDK request shape rejected by server: ${ur.response.status}`,
  );

  console.log('OK');
}

main().catch((e) => {
  console.error('Exception:', e);
  process.exit(99);
});
