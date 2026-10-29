import type { BuilderCamera } from '@/components/builder/builder-camera';
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

/** The map of the first scene after chapter `index` that isn't on `currentMapId`, to load ahead. */
export function nextSceneMapId(
  chapters: readonly StoryChapter[],
  index: number,
  currentMapId: string | undefined,
): string | undefined {
  return chapters.slice(index + 1).find((c) => c.scene && c.scene.map_id !== currentMapId)?.scene
    ?.map_id;
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
