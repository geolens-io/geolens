import {
  activeChapterFrom,
  applySceneVisibility,
  cameraDiffers,
  nextMapScene,
  panTolerancePx,
  resolveScene,
  toStoryCamera,
  transitionDuration,
  type CameraProbe,
} from '../story-scenes';
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

describe('nextMapScene', () => {
  it('finds the next scene on a different map, skipping text-only and same-map chapters', () => {
    const chapters = [
      chapter('one', scene('map-a')),
      chapter('text'),
      chapter('same', scene('map-a', 6)),
      chapter('other', scene('map-b')),
    ];
    expect(nextMapScene(chapters, 0, 'map-a')).toEqual({ scene: chapters[3].scene, chapterId: 'other' });
    expect(nextMapScene(chapters, 3, 'map-b')).toBeNull();
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

const gap = (panPx: number, zoom = 0) => ({ panPx, zoom, bearing: 0, pitch: 0 });

describe('transitionDuration', () => {
  it('starts at the 600 ms floor and grows with the pan and the zoom change', () => {
    expect(transitionDuration(gap(0))).toBe(600);
    expect(transitionDuration(gap(400))).toBe(1000);
    expect(transitionDuration(gap(0, 2))).toBe(900);
    expect(transitionDuration(gap(400, 2))).toBe(1300);
  });

  it('stops at the 2.5 s cap, and for a distance that is not a number', () => {
    expect(transitionDuration(gap(100000))).toBe(2500);
    expect(transitionDuration(gap(Number.POSITIVE_INFINITY, 1))).toBe(2500);
    expect(transitionDuration(gap(Number.NaN, 1))).toBe(2500);
  });
});

describe('cameraDiffers', () => {
  const target = { center: [10, 20] as [number, number], zoom: 5, bearing: 0, pitch: 0 };
  const TOLERANCE = 10;
  function probe(
    view: Partial<{ lng: number; lat: number; zoom: number; bearing: number; pitch: number }> = {},
    limits: Pick<CameraProbe, 'getMaxPitch' | 'getMinZoom' | 'getMaxZoom'> = {},
  ): CameraProbe {
    const v = { lng: 10, lat: 20, zoom: 5, bearing: 0, pitch: 0, ...view };
    return {
      ...limits,
      getCenter: () => ({ lng: v.lng, lat: v.lat }),
      getZoom: () => v.zoom,
      getBearing: () => v.bearing,
      getPitch: () => v.pitch,
      // One pixel per degree around the container's centre.
      project: ([lng, lat]) => ({ x: 500 + lng - v.lng, y: 250 - (lat - v.lat) }),
      getContainer: () => ({ clientWidth: 1000, clientHeight: 500 }),
    };
  }

  it('is false at the scene camera and within the tolerance', () => {
    expect(cameraDiffers(probe(), target, TOLERANCE)).toBe(false);
    expect(cameraDiffers(probe({ lng: 10.9, zoom: 5.1, bearing: 1, pitch: 1 }), target, TOLERANCE)).toBe(false);
  });

  it('compares against the pitch and zoom the map can reach', () => {
    const steep = { ...target, pitch: 70, zoom: 25 };
    const limits = { getMaxPitch: () => 60, getMinZoom: () => 0, getMaxZoom: () => 22 };
    expect(cameraDiffers(probe({ pitch: 60, zoom: 22 }, limits), steep, TOLERANCE)).toBe(false);
    expect(cameraDiffers(probe({ pitch: 40, zoom: 22 }, limits), steep, TOLERANCE)).toBe(true);
  });

  it('is true when the centre, zoom, bearing or pitch is past it', () => {
    expect(cameraDiffers(probe({ lng: 21 }), target, TOLERANCE)).toBe(true);
    expect(cameraDiffers(probe({ zoom: 5.2 }), target, TOLERANCE)).toBe(true);
    expect(cameraDiffers(probe({ bearing: 2 }), target, TOLERANCE)).toBe(true);
    expect(cameraDiffers(probe({ pitch: 2 }), target, TOLERANCE)).toBe(true);
  });

  it('reads a bearing across north as the short way round', () => {
    expect(cameraDiffers(probe({ bearing: 359.5 }), target, TOLERANCE)).toBe(false);
    expect(cameraDiffers(probe({ bearing: 358 }), target, TOLERANCE)).toBe(true);
  });

  it('reads a centre panned across the antimeridian as the short way round', () => {
    const near = { ...target, center: [-179.99, 20] as [number, number] };
    expect(cameraDiffers(probe({ lng: 180.01 }), near, TOLERANCE)).toBe(false);
  });
});

describe('panTolerancePx', () => {
  it('is 2% of the smaller side of the map', () => {
    expect(panTolerancePx({ getContainer: () => ({ clientWidth: 1000, clientHeight: 500 }) })).toBe(10);
  });
});
