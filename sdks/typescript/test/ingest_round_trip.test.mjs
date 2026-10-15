/**
 * TypeScript SDK ingest, reupload and PNG round trips against a live server.
 *
 * Invoked by backend/tests/test_sdks_round_trip.py, which runs the queued
 * worker task between phases. Reads GEOLENS_BASE_URL and GEOLENS_TOKEN from
 * env; argv[2] selects the phase:
 *
 *   upload                      stage + commit a 3-row GeoJSON, print UPLOAD_JOB_ID
 *   reupload <dataset> <names>  stage + commit a replacement, print REUPLOAD_JOB_ID
 *   verify <job> <names>        job is complete; the dataset holds exactly <names>
 *   png <icon_id> <base64>      the icon asset is those exact PNG bytes; the sprite is a PNG
 *
 * <names> is a comma-separated list of feature names.
 */
import * as nodeBuffer from 'node:buffer';
import { createGeolensClient } from '../dist/index.js';
import {
  commitImportIngestCommitJobIdPost,
  getFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGet,
  getGeolensSpritePngEndpointMapsSpritesGeolensPngGet,
  getJobStatusJobsJobIdGet,
  getMapIconAssetEndpointMapsIconsIconIdAssetGet,
  getSingleDatasetDatasetsDatasetIdGet,
  reuploadCommitDatasetsDatasetIdReuploadJobIdCommitPost,
  reuploadDatasetDatasetsDatasetIdReuploadPost,
  uploadFileIngestUploadPost,
} from '../dist/client/sdk.gen.js';

const File = nodeBuffer.File;
const baseUrl = process.env.GEOLENS_BASE_URL;
const token = process.env.GEOLENS_TOKEN;
if (!File || !baseUrl || !token) {
  console.error('Node 18.13+ with GEOLENS_BASE_URL and GEOLENS_TOKEN is required');
  process.exit(2);
}

const sdk = createGeolensClient({ baseUrl, bearerToken: token });
const [phase, ...args] = process.argv.slice(2);
const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg);
    process.exit(1);
  }
}

function collection(names) {
  return JSON.stringify({
    type: 'FeatureCollection',
    features: names.map((name, i) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [i, i] },
      properties: { name },
    })),
  });
}

function geojsonFile(names, fileName) {
  return new File([collection(names)], fileName, { type: 'application/geo+json' });
}

async function assertPng(result, label, expected) {
  assert(result.response.status === 200, `${label} status: ${result.response.status}`);
  assert(result.data instanceof Blob, `${label} is not a Blob`);
  const bytes = new Uint8Array(await result.data.arrayBuffer());
  assert(
    PNG_MAGIC.every((b, i) => bytes[i] === b),
    `${label} does not start with the PNG signature`,
  );
  assert(
    !expected || Buffer.from(bytes).equals(expected),
    `${label} differs from the uploaded PNG`,
  );
}

async function main() {
  if (phase === 'upload') {
    const up = await uploadFileIngestUploadPost({
      client: sdk.client,
      body: { file: geojsonFile(['a', 'b', 'c'], 'rt.geojson') },
    });
    assert(up.response.status === 201, `upload status: ${up.response.status}`);
    const commit = await commitImportIngestCommitJobIdPost({
      client: sdk.client,
      path: { job_id: up.data.job_id },
      body: { title: `ts-sdk-rt-${Date.now()}` },
    });
    assert(commit.response.status === 202, `commit status: ${commit.response.status}`);
    console.log(`UPLOAD_JOB_ID=${up.data.job_id}`);
  } else if (phase === 'reupload') {
    const [datasetId, names] = args;
    const up = await reuploadDatasetDatasetsDatasetIdReuploadPost({
      client: sdk.client,
      path: { dataset_id: datasetId },
      body: { file: geojsonFile(names.split(','), 'rt2.geojson') },
    });
    assert(up.response.status === 201, `reupload status: ${up.response.status}`);
    const commit = await reuploadCommitDatasetsDatasetIdReuploadJobIdCommitPost({
      client: sdk.client,
      path: { dataset_id: datasetId, job_id: up.data.job_id },
      body: {},
    });
    assert(
      commit.response.status === 202,
      `reupload commit status: ${commit.response.status}`,
    );
    console.log(`REUPLOAD_JOB_ID=${up.data.job_id}`);
  } else if (phase === 'verify') {
    const [jobId, names] = args;
    const expected = names.split(',').sort();
    const job = await getJobStatusJobsJobIdGet({
      client: sdk.client,
      path: { job_id: jobId },
    });
    assert(job.data?.status === 'complete', `job status: ${job.data?.status}`);
    const datasetId = job.data.dataset_id;
    const dataset = await getSingleDatasetDatasetsDatasetIdGet({
      client: sdk.client,
      path: { dataset_id: datasetId },
    });
    assert(
      dataset.data.feature_count === expected.length,
      `feature_count ${dataset.data.feature_count} != ${expected.length}`,
    );
    const rows = await getFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGet({
      client: sdk.client,
      path: { dataset_id: datasetId },
    });
    const got = rows.data.features.map((f) => f.properties.name).sort();
    assert(
      JSON.stringify(got) === JSON.stringify(expected),
      `rows ${JSON.stringify(got)} != ${JSON.stringify(expected)}`,
    );
    console.log(`DATASET_ID=${datasetId}`);
  } else if (phase === 'png') {
    const [iconId, iconBase64] = args;
    await assertPng(
      await getMapIconAssetEndpointMapsIconsIconIdAssetGet({
        client: sdk.client,
        path: { icon_id: iconId },
      }),
      'icon asset',
      Buffer.from(iconBase64, 'base64'),
    );
    await assertPng(
      await getGeolensSpritePngEndpointMapsSpritesGeolensPngGet({ client: sdk.client }),
      'sprite',
    );
  } else {
    assert(false, `unknown phase: ${phase}`);
  }
  console.log('OK');
}

main().catch((e) => {
  console.error('Exception:', e);
  process.exit(99);
});
