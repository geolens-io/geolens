import { expect, getAuthToken, type APIRequestContext, type Page, type Response } from './session';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

/** JSON request headers as the saved admin. */
export function authHeaders(): Record<string, string> {
  return {
    Authorization: `Bearer ${getAuthToken()}`,
    'Content-Type': 'application/json',
  };
}

/** Creates a map as the saved admin and returns its id. */
export async function createMap(request: APIRequestContext, name: string, description?: string): Promise<string> {
  const response = await request.post(`${BASE_URL}/api/maps/`, {
    headers: authHeaders(),
    data: description === undefined ? { name } : { name, description },
  });
  expect(response.ok(), `Create map failed: ${response.status()} ${await response.text()}`).toBe(true);
  return ((await response.json()) as { id: string }).id;
}

/** Deletes a map as the saved admin; cleanup, so a failure isn't reported. */
export async function deleteMap(request: APIRequestContext, mapId: string): Promise<void> {
  await request.delete(`${BASE_URL}/api/maps/${mapId}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
  });
}

/** Waits until the Builder has drawn its map and its layer sidebar. */
export async function waitForBuilder(page: Page): Promise<void> {
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('builder-sidebar')).toBeVisible({ timeout: 15_000 });
}

/** The Builder's save of a map's settings: `PUT /api/maps/{id}`. */
export function isMapUpdateResponse(response: Response, mapId: string): boolean {
  return response.request().method() === 'PUT' && new URL(response.url()).pathname === `/api/maps/${mapId}`;
}
