import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

export interface SearchSeed {
  id: string;
  title: string;
  query: string;
}

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

let searchSeedPromise: Promise<SearchSeed> | null = null;

export async function getSearchSeed(): Promise<SearchSeed> {
  if (searchSeedPromise) return searchSeedPromise;

  searchSeedPromise = (async () => {
    const initialResponse = await fetch(`${BASE_URL}/api/search/datasets/?limit=20`, {
      headers: authHeaders(),
    });
    if (!initialResponse.ok) {
      throw new Error(`Failed to fetch searchable datasets: ${initialResponse.status}`);
    }

    const initialPayload = await initialResponse.json();
    const features = initialPayload.features ?? [];
    for (const feature of features) {
      const title = feature.properties?.title;
      const id = feature.id;
      if (typeof title !== 'string' || typeof id !== 'string') continue;

      for (const query of buildQueryCandidates(title)) {
        const matchResponse = await fetch(
          `${BASE_URL}/api/search/datasets/?q=${encodeURIComponent(query)}&limit=5`,
          { headers: authHeaders() },
        );
        if (!matchResponse.ok) continue;

        const matchPayload = await matchResponse.json();
        const match = (matchPayload.features ?? []).find(
          (candidate: { id?: string; properties?: { title?: string } }) =>
            candidate.id === id || candidate.properties?.title === title,
        );
        if (match) {
          return {
            id,
            title,
            query,
          };
        }
      }
    }

    throw new Error('Could not find a stable searchable dataset fixture');
  })();

  return searchSeedPromise;
}
