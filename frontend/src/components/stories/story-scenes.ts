import type { BuilderCamera } from '@/components/builder/builder-camera';
import { lngOffset } from '@/lib/bbox';
import type { StoryCamera, StoryChapter, StoryScene } from '@/types/api';

export interface ResolvedScene {
  scene: StoryScene;
  /** The chapter the scene belongs to, which may be an earlier one than the active chapter. */
  chapterId: string;
}

/**
 * The chapter whose scene the map shows while chapter `index` is active: its
 * own, else the nearest earlier one with a scene; text-only chapters at the
 * start take the first scene after them, so the map isn't empty while the
 * story opens. A chapter whose scene is on a map the reader can't open counts
 * too, so the map doesn't keep showing an earlier chapter's scene for it.
 */
export function nearestSceneChapter(chapters: readonly StoryChapter[], index: number): StoryChapter | null {
  const hasScene = (c: StoryChapter) => !!c.scene || c.scene_hidden;
  for (let i = Math.min(index, chapters.length - 1); i >= 0; i--) if (hasScene(chapters[i])) return chapters[i];
  for (let i = index + 1; i < chapters.length; i++) if (hasScene(chapters[i])) return chapters[i];
  return null;
}

/** The scene the map shows while chapter `index` is active; null for none, or one the reader can't open. */
export function resolveScene(chapters: readonly StoryChapter[], index: number): ResolvedScene | null {
  const chapter = nearestSceneChapter(chapters, index);
  return chapter?.scene ? { scene: chapter.scene, chapterId: chapter.id } : null;
}

/** The first scene after chapter `index` that isn't on `currentMapId`, to load ahead. */
export function nextMapScene(
  chapters: readonly StoryChapter[],
  index: number,
  currentMapId: string | undefined,
): ResolvedScene | null {
  const chapter = chapters.slice(index + 1).find((c) => c.scene && c.scene.map_id !== currentMapId);
  return chapter?.scene ? { scene: chapter.scene, chapterId: chapter.id } : null;
}

/**
 * The map's layers with the scene's visibility applied. Ids the map no longer
 * has are ignored, and a layer the scene leaves out keeps its saved visibility.
 */
export function applySceneVisibility<T extends { id?: string | null; visible: boolean }>(
  layers: T[],
  layerVisibility: StoryScene['layer_visibility'],
): T[] {
  if (!layerVisibility || Object.keys(layerVisibility).length === 0) return layers;
  return layers.map((layer) => {
    const visible = layer.id ? layerVisibility[layer.id] : undefined;
    return visible === undefined || visible === layer.visible ? layer : { ...layer, visible };
  });
}

/** A scene camera in the shape ViewerMap opens at. MapLibre's camera calls take the camera as is. */
export function cameraViewState({ center: [lng, lat], zoom, bearing, pitch }: StoryCamera) {
  return { center_lng: lng, center_lat: lat, zoom, bearing, pitch };
}

/**
 * A camera from `readMapCamera` or `savedMapCamera` as a scene stores it, with
 * the longitude wrapped into -180..180 (a map panned across the antimeridian
 * reports it unwrapped). Null when the camera has no center or zoom.
 */
export function toStoryCamera(camera: BuilderCamera): StoryCamera | null {
  const { center_lng: lng, center_lat: lat, zoom, bearing, pitch } = camera;
  if (lng === null || lat === null || zoom === null) return null;
  const wrapped = ((((lng + 180) % 360) + 360) % 360) - 180;
  return { center: [Number(wrapped.toFixed(6)), lat], zoom, bearing, pitch };
}

/**
 * The chapter a scrolling reader is on: the last one whose top has crossed
 * the activation line, given whether each chapter has. The first chapter until
 * any has.
 */
export function activeChapterFrom(crossed: readonly boolean[]): number {
  return Math.max(0, crossed.lastIndexOf(true));
}

const TRANSITION_MIN_MS = 600;
const TRANSITION_MAX_MS = 2500;
const TRANSITION_PX_PER_ZOOM = 150;

/** Pixels, zoom levels and degrees of difference between the map's view and a scene camera. */
export interface CameraGap {
  panPx: number;
  zoom: number;
  bearing: number;
  pitch: number;
}

/**
 * How long a Fly or Glide takes: one millisecond per screen pixel of the move
 * at the current zoom, plus 150 px per zoom level changed, between 600 ms and 2.5 s.
 */
export function transitionDuration({ panPx, zoom }: CameraGap): number {
  const distance = panPx + zoom * TRANSITION_PX_PER_ZOOM;
  if (!Number.isFinite(distance)) return TRANSITION_MAX_MS;
  return Math.round(Math.min(TRANSITION_MAX_MS, TRANSITION_MIN_MS + distance));
}

/** The part of the map a camera comparison reads. */
export interface CameraProbe {
  getCenter(): { lng: number; lat: number };
  getZoom(): number;
  getBearing(): number;
  getPitch(): number;
  project(lngLat: [number, number]): { x: number; y: number };
  getContainer(): { clientWidth: number; clientHeight: number };
}

/** How far the view may drift from a scene camera before it counts as moved, in screen pixels. */
export function panTolerancePx(map: Pick<CameraProbe, 'getContainer'>): number {
  const { clientWidth, clientHeight } = map.getContainer();
  return 0.02 * Math.min(clientWidth, clientHeight);
}

export function cameraGap(map: CameraProbe, target: StoryCamera): CameraGap {
  const center = map.getCenter();
  // The target in the world the centre is in, so a pan across the antimeridian takes the short way.
  const lng = center.lng + lngOffset(target.center[0], center.lng);
  const to = map.project([lng, target.center[1]]);
  // The map's centre is the middle of its container.
  const { clientWidth, clientHeight } = map.getContainer();
  return {
    panPx: Math.hypot(to.x - clientWidth / 2, to.y - clientHeight / 2),
    zoom: Math.abs(map.getZoom() - target.zoom),
    bearing: Math.abs(lngOffset(map.getBearing(), target.bearing)),
    pitch: Math.abs(map.getPitch() - target.pitch),
  };
}

/** True when the view is off the scene's camera by more than a small tolerance. */
export function cameraDiffers(map: CameraProbe, target: StoryCamera, tolerancePx: number): boolean {
  const gap = cameraGap(map, target);
  return gap.panPx > tolerancePx || gap.zoom > 0.1 || gap.bearing > 1 || gap.pitch > 1;
}
