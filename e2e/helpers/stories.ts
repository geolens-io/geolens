import { randomUUID } from 'crypto';
import { expect, type APIRequestContext, type Page } from './session';
import { authHeaders } from './maps';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

export interface SceneCamera {
  center: [number, number];
  zoom: number;
  bearing?: number;
  pitch?: number;
}

export interface ChapterSpec {
  title: string;
  mapId: string;
  camera: SceneCamera;
  transition?: 'fly' | 'glide' | 'cut';
  /** Paragraphs of text, so a chapter has height to scroll through. */
  paragraphs?: number;
  /** Markdown that replaces the paragraphs. */
  text?: string;
}

export interface StorySettingsSpec {
  navigation?: boolean;
  layout?: 'side' | 'floating';
  panel_position?: 'left' | 'right' | 'center';
  theme?: 'follow' | 'light' | 'dark';
}

/** Creates a story with these chapters and settings and publishes it; returns its id. */
export async function createPublishedStory(
  request: APIRequestContext,
  title: string,
  chapters: ChapterSpec[],
  settings: StorySettingsSpec = {},
): Promise<string> {
  const created = await request.post(`${BASE_URL}/api/stories/`, { headers: authHeaders(), data: { title } });
  expect(created.ok(), `Create story failed: ${created.status()} ${await created.text()}`).toBe(true);
  const draft = (await created.json()) as { id: string; revision: number };

  const document = {
    version: 1,
    chapters: chapters.map((chapter) => ({
      id: randomUUID(),
      title: chapter.title,
      scene: {
        map_id: chapter.mapId,
        camera: { bearing: 0, pitch: 0, ...chapter.camera },
        ...(chapter.transition ? { transition: chapter.transition } : {}),
      },
      blocks: [
        {
          id: randomUUID(),
          type: 'markdown',
          v: 1,
          config: {
            text:
              chapter.text ??
              Array.from({ length: chapter.paragraphs ?? 6 }, (_, i) => `${chapter.title} paragraph ${i + 1}.`).join('\n\n'),
          },
        },
      ],
    })),
    settings: { navigation: false, layout: 'side', panel_position: 'left', theme: 'follow', ...settings },
  };
  const saved = await request.put(`${BASE_URL}/api/stories/${draft.id}/draft`, {
    headers: authHeaders(),
    data: { revision: draft.revision, document },
  });
  expect(saved.ok(), `Save draft failed: ${saved.status()} ${await saved.text()}`).toBe(true);
  const { revision } = (await saved.json()) as { revision: number };

  const published = await request.post(`${BASE_URL}/api/stories/${draft.id}/publish`, {
    headers: authHeaders(),
    data: { revision },
  });
  expect(published.ok(), `Publish story failed: ${published.status()} ${await published.text()}`).toBe(true);
  return draft.id;
}

/** Deletes a story as the saved admin; cleanup, so a failure isn't reported. */
export async function deleteStory(request: APIRequestContext, storyId: string): Promise<void> {
  await request.delete(`${BASE_URL}/api/stories/${storyId}`, { headers: authHeaders() });
}

export interface MapCamera {
  lng: number;
  lat: number;
  zoom: number;
}

// The app exposes no map handle, so the live MapLibre map is found through the
// canvas's React fiber, the same route the paint-timing smokes use.
const FIND_MAP = `
  (() => {
    const isMap = (v) => v && typeof v === 'object' && typeof v.getCenter === 'function' && typeof v.getZoom === 'function';
    const pick = (v) => {
      if (isMap(v)) return v;
      if (v && typeof v === 'object') {
        for (const key of ['current', 'map', '_map', 'value']) {
          const inner = v[key];
          if (isMap(inner)) return inner;
          if (inner && typeof inner === 'object') {
            if (isMap(inner.current)) return inner.current;
            if (isMap(inner.map)) return inner.map;
          }
        }
      }
      return null;
    };
    // The canvas is MapLibre's own; its React-rendered container is the nearest element with a fiber.
    let host = document.querySelector('canvas.maplibregl-canvas');
    const fiberKeyOf = (el) => Object.keys(el).find((k) => k.startsWith('__reactFiber$'));
    while (host && !fiberKeyOf(host)) host = host.parentElement;
    if (!host) return null;
    for (let fiber = host[fiberKeyOf(host)]; fiber; fiber = fiber.return) {
      for (let s = fiber.memoizedState; s; s = s.next) {
        const hit = pick(s.memoizedState) || pick(s.queue && s.queue.lastRenderedState);
        if (hit) return hit;
      }
      const hit = pick(fiber.memoizedProps) || pick(fiber.stateNode);
      if (hit) return hit;
    }
    return null;
  })()
`;

/** The story map's camera right now, once the map has drawn. */
export async function readMapCamera(page: Page): Promise<MapCamera> {
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
  return page.evaluate(`(() => {
    const map = ${FIND_MAP};
    if (!map) return null;
    const c = map.getCenter();
    return { lng: c.lng, lat: c.lat, zoom: map.getZoom() };
  })()`) as Promise<MapCamera>;
}

/** Waits until the story map exists and has settled at the camera's first position. */
export async function waitForStoryMap(page: Page, camera: SceneCamera): Promise<void> {
  // The viewer sets this once the story pane holds the map, so a chapter change then plays its transition.
  await expect(page.locator('[data-map-ready="true"]')).toBeVisible({ timeout: 20_000 });
  await expect
    .poll(async () => {
      const now = await readMapCamera(page);
      return now ? cameraDistance(now, camera) : Infinity;
    }, { timeout: 20_000 })
    .toBeLessThan(0.05);
}

/** A rough gap between a read camera and a target: degrees of centre plus zoom levels. */
export function cameraDistance(now: MapCamera, target: SceneCamera): number {
  return Math.abs(now.lng - target.center[0]) + Math.abs(now.lat - target.center[1]) + Math.abs(now.zoom - target.zoom);
}

/** Drags the map with the mouse, which MapLibre tags as the reader's own move. */
export async function dragMap(page: Page, dx = 220, dy = 0): Promise<void> {
  const box = await page.locator('canvas.maplibregl-canvas').boundingBox();
  if (!box) throw new Error('The map canvas has no box');
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 5 });
  await page.mouse.move(x + dx, y + dy, { steps: 5 });
  await page.mouse.up();
}
