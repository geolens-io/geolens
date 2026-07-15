import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

export interface SearchSeed {
  id: string;
  title: string;
  query: string;
}

type SearchFeature = {
  id?: string;
  properties?: {
    record_type?: string;
    title?: string;
    type?: string;
  };
};

type SearchPayload = {
  features?: SearchFeature[];
};

const PREFERRED_SEARCH_QUERIES = [
  'Geography Regions Elevation Points',
  'Wgs84 Bounding Box',
  'ADK 46er High Peaks AOI subset',
  'APA Adirondack Park Boundary',
];

export function getAuthToken(): string {
  const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
  const state = JSON.parse(raw);
  for (const origin of state.origins ?? []) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        return JSON.parse(entry.value).state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}

function authHeaders() {
  return {
    Authorization: `Bearer ${getAuthToken()}`,
  };
}

function buildQueryCandidates(title: string): string[] {
  const words = title.match(/[A-Za-z0-9]+/g) ?? [];
  const candidates = [title.trim(), ...words];
  const deduped = new Set<string>();

  for (const candidate of candidates) {
    const value = candidate.trim();
    if (value.length >= 2) deduped.add(value);
  }

  return [...deduped];
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function searchUrl(params: Record<string, string | number | boolean>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    searchParams.set(key, String(value));
  }
  return `${BASE_URL}/api/search/datasets/?${searchParams.toString()}`;
}

async function fetchSearchPayload(url: string): Promise<SearchPayload> {
  let lastStatus = 0;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const response = await fetch(url, { headers: authHeaders() });
    if (response.ok) {
      return response.json() as Promise<SearchPayload>;
    }

    lastStatus = response.status;
    if (response.status !== 429 && response.status < 500) break;

    const retryAfter = Number(response.headers.get('retry-after'));
    const retryDelay = Number.isFinite(retryAfter)
      ? retryAfter * 1000
      : 1500 * (attempt + 1);
    await sleep(retryDelay);
  }

  throw new Error(`Failed to fetch searchable datasets: ${lastStatus}`);
}

function seedFromFeature(feature: SearchFeature, query: string): SearchSeed | null {
  const title = feature.properties?.title;
  const id = feature.id;
  if (typeof title !== 'string' || typeof id !== 'string') return null;
  if (feature.properties?.type === 'collection') return null;
  return { id, title, query };
}

let searchSeedPromise: Promise<SearchSeed> | null = null;

export async function getSearchSeed(): Promise<SearchSeed> {
  if (searchSeedPromise) return searchSeedPromise;

  searchSeedPromise = (async () => {
    for (const query of PREFERRED_SEARCH_QUERIES) {
      const payload = await fetchSearchPayload(searchUrl({ q: query, limit: 5 }));
      const seed = (payload.features ?? [])
        .map((feature) => seedFromFeature(feature, query))
        .find((candidate): candidate is SearchSeed => candidate !== null);
      if (seed) return seed;
    }

    const initialPayload = await fetchSearchPayload(searchUrl({ limit: 50 }));
    const features: SearchFeature[] = initialPayload.features ?? [];
    for (const feature of features) {
      const title = feature.properties?.title;
      const id = feature.id;
      if (typeof title !== 'string' || typeof id !== 'string') continue;

      for (const query of buildQueryCandidates(title)) {
        const matchPayload = await fetchSearchPayload(searchUrl({ q: query, limit: 5 }));
        const matches: SearchFeature[] = matchPayload.features ?? [];
        const [firstMatch] = matches;
        const exactTitleMatches = matches.filter(
          (candidate) => candidate.properties?.title === title,
        );

        if (
          firstMatch?.id === id &&
          exactTitleMatches.length === 1
        ) {
          return {
            id,
            title,
            query,
          };
        }
      }
    }

    throw new Error('Could not find a stable searchable dataset fixture');
  })().catch((error) => {
    searchSeedPromise = null;
    throw error;
  });

  return searchSeedPromise;
}

export interface SeededDataset {
  id: string;
  title: string;
}

/**
 * Ingest the sample fixture as a real dataset and return its id + title.
 *
 * The default Playwright setup uses this helper to give every project one
 * catalog fixture. Specs may also create an isolated fixture when they need to
 * publish or mutate it. The helper follows the same upload, commit, and poll
 * sequence as the import UI. Pair each call with `deleteDataset()`.
 */
export async function seedDataset(titlePrefix = 'E2E Seed Dataset'): Promise<SeededDataset> {
  return seedFixtureDataset('sample.geojson', 'application/geo+json', `${titlePrefix} ${Date.now()}`);
}

/**
 * fix(#451): ingest the single-band Float32 GeoTIFF fixture as a real DEM
 * dataset (`is_dem_candidate` in processing/raster/cog.py flags single-band
 * float rasters). Powers the two-switch DEM editor spec. Pair with
 * `deleteDataset()` in `afterAll`.
 */
export async function seedDemDataset(): Promise<SeededDataset> {
  return seedFixtureDataset('sample-dem.tif', 'image/tiff', `E2E DEM ${Date.now()}`);
}

async function seedFixtureDataset(
  fixtureName: string,
  mimeType: string,
  title: string,
): Promise<SeededDataset> {
  const fixture = path.join(__dirname, `../fixtures/${fixtureName}`);
  const bytes = fs.readFileSync(fixture);

  const form = new FormData();
  form.append('file', new Blob([bytes], { type: mimeType }), fixtureName);
  const upload = await fetch(`${BASE_URL}/api/ingest/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  if (!upload.ok) throw new Error(`ingest upload failed: ${upload.status}`);
  const { job_id: jobId } = (await upload.json()) as { job_id: string };

  const commit = await fetch(`${BASE_URL}/api/ingest/commit/${jobId}`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!commit.ok) throw new Error(`ingest commit failed: ${commit.status}`);

  // Commit returns 202 and queues an async ingest task; poll until the dataset row exists.
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}`, { headers: authHeaders() });
    if (res.ok) {
      const job = (await res.json()) as { status?: string; dataset_id?: string | null };
      if (job.dataset_id && ['complete', 'completed', 'succeeded'].includes(job.status ?? '')) {
        return { id: job.dataset_id, title };
      }
      if (['failed', 'error'].includes(job.status ?? '')) {
        throw new Error(`ingest job ${jobId} failed: ${JSON.stringify(job)}`);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`ingest job ${jobId} did not produce a dataset in time`);
}

/** Delete a seeded dataset. Returns false when best-effort cleanup fails. */
export async function deleteDataset(id: string, title: string): Promise<boolean> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(`${BASE_URL}/api/datasets/${id}`, {
        method: 'DELETE',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm_title: title }),
      });
      if (response.ok || response.status === 404) return true;
      if (response.status < 500 && response.status !== 429) return false;
    } catch {
      // Retry transient network failures before reporting cleanup failure.
    }

    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }

  return false;
}
