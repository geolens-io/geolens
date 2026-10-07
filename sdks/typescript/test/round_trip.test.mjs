/**
 * TypeScript SDK round-trip test (Phase 215 / OCSDK-02).
 *
 * Invoked by backend/tests/test_sdks_round_trip.py via subprocess. Reads
 * GEOLENS_BASE_URL and GEOLENS_TOKEN from env, then exercises the same three
 * endpoints as the Python half through the @hey-api-generated SDK functions:
 *
 *   GET  /search/datasets/         (200 expected)
 *   GET  /datasets/{dataset_id}    (404 expected for fake UUID — proves auth + route)
 *   POST /ingest/upload            (201 expected for a real file part)
 *
 * Exits 0 on success; non-zero on any failure with a descriptive console.error.
 *
 * The function names below follow @hey-api/openapi-ts 0.99.0's camelCase
 * conversion of FastAPI operationIds. Verified against
 * sdks/typescript/dist/client/sdk.gen.d.ts on 2026-07-10.
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

  // 3. /ingest/upload  → 201 with a job id for a real file part.
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
  const file = new File([tinyGeoJson], 'tiny.geojson', {
    type: 'application/geo+json',
  });

  const ur = await uploadFileIngestUploadPost({
    client: sdk.client,
    body: { file },
  });
  assert(
    ur.response.status === 201,
    `ingest/upload status: ${ur.response.status} ${JSON.stringify(ur.error)}`,
  );
  assert(ur.data && ur.data.job_id, 'ingest/upload returned no job_id');
  console.log(`UPLOAD_JOB_ID=${ur.data.job_id}`);

  console.log('OK');
}

main().catch((e) => {
  console.error('Exception:', e);
  process.exit(99);
});
