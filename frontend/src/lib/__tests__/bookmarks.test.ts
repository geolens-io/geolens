import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { bookmarkFromMap, extentOfView, goToBookmark, sameBookmarks } from '../bookmarks';

afterEach(() => vi.unstubAllGlobals());

const view = { center: { lng: 10, lat: 20 }, zoom: 4, width: 1000, height: 500 };

describe('extentOfView', () => {
  it('is the viewport box at bearing 0', () => {
    const [w, s, e, n] = extentOfView(view);
    const worldSize = 512 * 2 ** 4;
    // 1000 px of 8192 px around the world.
    expect(e - w).toBeCloseTo((1000 / worldSize) * 360, 4);
    expect((w + e) / 2).toBeCloseTo(10, 4);
    expect(n).toBeGreaterThan(20);
    expect(s).toBeLessThan(20);
  });

  it('shrinks a rotated view so fitBounds lands on the same zoom', () => {
    const flat = extentOfView({ ...view, bearing: 0 });
    const turned = extentOfView({ ...view, bearing: 90, width: 1000, height: 500 });
    // A 2:1 box turned a quarter fits only if its width is the viewport height.
    expect(turned[2] - turned[0]).toBeCloseTo((flat[2] - flat[0]) / 2, 3);
  });

  it('stores west > east for a view over the antimeridian', () => {
    const [w, , e] = extentOfView({ ...view, center: { lng: 179.9, lat: 0 } });
    expect(w).toBeGreaterThan(0);
    expect(e).toBeLessThan(0);
    expect(w).toBeGreaterThan(e);
  });

  it('stores the whole world for a view 360 degrees wide', () => {
    const [w, s, e, n] = extentOfView({ center: { lng: 0, lat: 0 }, zoom: 0, width: 2000, height: 800 });
    expect([w, e]).toEqual([-180, 180]);
    expect(s).toBeGreaterThanOrEqual(-85.051129);
    expect(n).toBeLessThanOrEqual(85.051129);
  });

  it('keeps latitudes inside the Mercator limit', () => {
    const [, s, , n] = extentOfView({ center: { lng: 0, lat: 84 }, zoom: 1, width: 600, height: 900 });
    expect(n).toBeLessThanOrEqual(85.051129);
    expect(s).toBeLessThan(n);
  });
});

function stubMap(camera: { bearing: number; pitch: number }) {
  return {
    getCenter: () => ({ lng: 10, lat: 20 }),
    getZoom: () => 4,
    getBearing: () => camera.bearing,
    getPitch: () => camera.pitch,
    getContainer: () => ({ clientWidth: 1000, clientHeight: 500 }),
    fitBounds: vi.fn(),
    // A flat map: the box fits back at the zoom it was taken at.
    cameraForBounds: () => ({ zoom: 4 }),
  } as unknown as MaplibreMap & { fitBounds: ReturnType<typeof vi.fn> };
}

describe('bookmarkFromMap', () => {
  it('resizes the box until the map fits it at the zoom it was taken at', () => {
    // A map whose fit lands 0.3 levels deeper than the flat-map box implies, as a globe's can.
    const fitZoom = ([[west], [east]]: number[][]) => Math.log2((1000 * 360) / (512 * (east - west))) + 0.3;
    const map = { ...stubMap({ bearing: 0, pitch: 0 }), cameraForBounds: (corners: number[][]) => ({ zoom: fitZoom(corners) }) };
    const { extent } = bookmarkFromMap(map as unknown as MaplibreMap, 'a');
    expect(fitZoom([[extent[0]], [extent[2]]])).toBeCloseTo(4, 2);
    const flat = bookmarkFromMap(stubMap({ bearing: 0, pitch: 0 }), 'a').extent;
    expect(extent[2] - extent[0]).toBeGreaterThan(flat[2] - flat[0]);
  });

  it('leaves out a bearing and pitch of zero', () => {
    const bookmark = bookmarkFromMap(stubMap({ bearing: 0, pitch: 0 }), 'Flat');
    expect(bookmark).not.toHaveProperty('bearing');
    expect(bookmark).not.toHaveProperty('pitch');
    expect(bookmark.name).toBe('Flat');
  });

  it('keeps a bearing and pitch that are set', () => {
    const bookmark = bookmarkFromMap(stubMap({ bearing: 30, pitch: 45 }), 'Tilted');
    expect(bookmark).toMatchObject({ bearing: 30, pitch: 45 });
  });
});

describe('sameBookmarks', () => {
  it('reads a list the builder made and the same list from the server as equal', () => {
    const made = [{ name: ' Cafe\u0301 ', extent: [1, 2, 3, 4] }];
    const stored = [{ name: 'Caf\u00e9', extent: [1, 2, 3, 4], bearing: null, pitch: null }];
    expect(sameBookmarks(made, stored)).toBe(true);
  });

  it('tells apart a name, an area, a rotation, a tilt and an order', () => {
    const one = { name: 'a', extent: [1, 2, 3, 4] };
    expect(sameBookmarks([one], [{ ...one, name: 'b' }])).toBe(false);
    expect(sameBookmarks([one], [{ ...one, extent: [1, 2, 3, 5] }])).toBe(false);
    expect(sameBookmarks([one], [{ ...one, bearing: 10 }])).toBe(false);
    expect(sameBookmarks([one], [{ ...one, pitch: 10 }])).toBe(false);
    const two = { name: 'b', extent: [1, 2, 3, 4] };
    expect(sameBookmarks([one, two], [two, one])).toBe(false);
  });
});

describe('goToBookmark', () => {
  it('fits the extent with a bearing and pitch of 0 by default', () => {
    const map = stubMap({ bearing: 0, pitch: 0 });
    goToBookmark(map, { name: 'a', extent: [1, 2, 3, 4] });
    expect(map.fitBounds).toHaveBeenCalledWith(
      [[1, 2], [3, 4]],
      expect.objectContaining({ bearing: 0, pitch: 0, padding: 0, duration: 800 }),
    );
  });

  it('leaves the zoom to the area, and caps it only for an area with no size', () => {
    const map = stubMap({ bearing: 0, pitch: 0 });
    goToBookmark(map, { name: 'a', extent: [1, 2, 1.0001, 2.0001] });
    expect(map.fitBounds.mock.calls[0][1]).not.toHaveProperty('maxZoom');
    goToBookmark(map, { name: 'point', extent: [1, 2, 1, 2] });
    expect(map.fitBounds.mock.calls[1][1]).toMatchObject({ maxZoom: 16 });
  });

  it('passes a stored bearing and pitch', () => {
    const map = stubMap({ bearing: 0, pitch: 0 });
    goToBookmark(map, { name: 'a', extent: [1, 2, 3, 4], bearing: 20, pitch: 50 });
    expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ bearing: 20, pitch: 50 }));
  });

  it('runs east past 180 for an extent across the antimeridian', () => {
    const map = stubMap({ bearing: 0, pitch: 0 });
    goToBookmark(map, { name: 'a', extent: [178, -20, -178, -15] });
    expect(map.fitBounds.mock.calls[0][0]).toEqual([[178, -20], [182, -15]]);
  });

  it('jumps without animating under reduced motion', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    const map = stubMap({ bearing: 0, pitch: 0 });
    goToBookmark(map, { name: 'a', extent: [1, 2, 3, 4] });
    expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ duration: 0 }));
  });
});
