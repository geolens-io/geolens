/**
 * Seed fixture for large-map perf tests (Phase 1047 PERF-01..04).
 *
 * Creates a builder map with many layers via the REST API so Playwright perf
 * specs can measure first-paint, hover latency, and bulk-op throughput on a
 * realistic 50-layer stack.
 *
 * Usage:
 *   const { mapId, layerIds } = await createLargeBuilderMap(request, {
 *     name: 'Perf test map',
 *     layerCount: 50,
 *     datasetId: '<uuid>',
 *   });
 *   // … run assertions …
 *   await deleteBuilderMap(request, mapId);
 */

import type { APIRequestContext } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

export interface CreateLargeBuilderMapOptions {
  /** Display name for the new map. */
  name: string;
  /** Number of layers to add (each adds the same dataset as a separate layer). */
  layerCount: number;
  /** Dataset UUID to use for every layer. Must be pre-existing in the catalog. */
  datasetId: string;
}

export interface LargeBuilderMapResult {
  mapId: string;
  layerIds: string[];
}

interface MapCreateResponse {
  id: string;
}

interface LayerAddResponse {
  id: string;
}

/**
 * Create a builder map and populate it with `opts.layerCount` layers.
 *
 * The `request` parameter should already carry the session's auth cookies /
 * storage state (Playwright's `storageState` propagates the JWT).  Requests
 * that need an explicit Authorization header use the helper below.
 */
export async function createLargeBuilderMap(
  request: APIRequestContext,
  opts: CreateLargeBuilderMapOptions,
): Promise<LargeBuilderMapResult> {
  // 1. Create the map
  const createRes = await request.post(`${BASE_URL}/api/maps/`, {
    data: {
      name: opts.name,
      description: `Auto-created by seed-large-builder-map fixture (layerCount=${opts.layerCount})`,
    },
  });
  if (!createRes.ok()) {
    const body = await createRes.text();
    throw new Error(`createLargeBuilderMap: POST /api/maps/ failed (${createRes.status()}): ${body}`);
  }
  const mapData = (await createRes.json()) as MapCreateResponse;
  const mapId = mapData.id;

  // 2. Add layers sequentially (parallel batch risks hitting rate limits or ordering issues)
  const layerIds: string[] = [];
  for (let i = 0; i < opts.layerCount; i++) {
    const layerRes = await request.post(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      data: { dataset_id: opts.datasetId },
    });
    if (!layerRes.ok()) {
      // Partial success: log and continue rather than failing the whole seeder
      if (process.env.DEBUG_SEEDER) {
        console.warn(`seed-large-builder-map: layer ${i + 1}/${opts.layerCount} failed (${layerRes.status()})`);
      }
      continue;
    }
    const layerData = (await layerRes.json()) as LayerAddResponse;
    layerIds.push(layerData.id);
  }

  return { mapId, layerIds };
}

/**
 * Delete a builder map created by `createLargeBuilderMap`.
 * Silently ignores 404 (already deleted).
 */
export async function deleteBuilderMap(
  request: APIRequestContext,
  mapId: string,
): Promise<void> {
  const res = await request.delete(`${BASE_URL}/api/maps/${mapId}`);
  if (!res.ok() && res.status() !== 404) {
    if (process.env.DEBUG_SEEDER) {
      console.warn(`seed-large-builder-map: DELETE /api/maps/${mapId} failed (${res.status()})`);
    }
  }
}
