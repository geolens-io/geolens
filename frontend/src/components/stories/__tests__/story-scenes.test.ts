import { activeChapterFrom, applySceneVisibility, nextSceneMapId, resolveScene, toStoryCamera } from '../story-scenes';
import type { StoryChapter, StoryScene } from '@/types/api';

function scene(mapId: string, zoom = 3): StoryScene {
  return { map_id: mapId, camera: { center: [0, 0], zoom, bearing: 0, pitch: 0 }, layer_visibility: {} };
}

function chapter(id: string, s: StoryScene | null = null): StoryChapter {
  return { id, title: id, scene: s, scene_hidden: false, blocks: [] };
}

describe('resolveScene', () => {
  const a = scene('map-a', 3);
  const b = scene('map-b', 5);

  it("uses the active chapter's own scene", () => {
    const chapters = [chapter('one', a), chapter('two', b)];
    expect(resolveScene(chapters, 1)).toEqual({ scene: b, chapterId: 'two' });
  });

  it('keeps the previous scene for a chapter without one', () => {
    const chapters = [chapter('one', a), chapter('text'), chapter('three', b)];
    expect(resolveScene(chapters, 1)).toEqual({ scene: a, chapterId: 'one' });
  });

  it('shows the first later scene while text-only opening chapters are active', () => {
    const chapters = [chapter('intro'), chapter('two', b)];
    expect(resolveScene(chapters, 0)).toEqual({ scene: b, chapterId: 'two' });
  });

  it('returns null for a story with no scenes', () => {
    expect(resolveScene([chapter('one'), chapter('two')], 1)).toBeNull();
  });
});

describe('applySceneVisibility', () => {
  const layers = [
    { id: 'shown', visible: true },
    { id: 'hidden', visible: false },
    { id: 'untouched', visible: true },
  ];

  it('overrides saved visibility by layer id and leaves other layers as saved', () => {
    const result = applySceneVisibility(layers, { shown: false, hidden: true });
    expect(result.map((l) => [l.id, l.visible])).toEqual([
      ['shown', false],
      ['hidden', true],
      ['untouched', true],
    ]);
  });

  it('ignores ids the map no longer has', () => {
    expect(applySceneVisibility(layers, { 'deleted-layer': false })).toEqual(layers);
  });
});

describe('nextSceneMapId', () => {
  it('finds the next scene on a different map, skipping text-only and same-map chapters', () => {
    const chapters = [
      chapter('one', scene('map-a')),
      chapter('text'),
      chapter('same', scene('map-a', 6)),
      chapter('other', scene('map-b')),
    ];
    expect(nextSceneMapId(chapters, 0, 'map-a')).toBe('map-b');
    expect(nextSceneMapId(chapters, 3, 'map-b')).toBeUndefined();
  });
});

describe('activeChapterFrom', () => {
  it('picks the last chapter that has crossed the line', () => {
    expect(activeChapterFrom([true, true, false])).toBe(1);
    expect(activeChapterFrom([true, true, true])).toBe(2);
  });

  it('stays on the first chapter until any has crossed', () => {
    expect(activeChapterFrom([false, false])).toBe(0);
  });
});

describe('toStoryCamera', () => {
  it('wraps a longitude panned past the antimeridian and keeps the rounding it was given', () => {
    expect(toStoryCamera({ center_lng: 190.5, center_lat: 10.123457, zoom: 4.5, bearing: 12, pitch: 30 })).toEqual({
      center: [-169.5, 10.123457],
      zoom: 4.5,
      bearing: 12,
      pitch: 30,
    });
  });

  it('has no camera without a center or zoom', () => {
    expect(toStoryCamera({ center_lng: null, center_lat: 1, zoom: 2, bearing: 0, pitch: 0 })).toBeNull();
    expect(toStoryCamera({ center_lng: 1, center_lat: 1, zoom: null, bearing: 0, pitch: 0 })).toBeNull();
  });
});
