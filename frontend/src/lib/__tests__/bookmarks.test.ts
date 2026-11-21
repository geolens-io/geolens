import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { bookmarkFromMap, extentOfView, goToBookmark } from '../bookmarks';

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
  } as unknown as MaplibreMap & { fitBounds: ReturnType<typeof vi.fn> };
}

describe('bookmarkFromMap', () => {
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

describe('goToBookmark', () => {
  it('fits the extent with a bearing and pitch of 0 by default', () => {
    const map = stubMap({ bearing: 0, pitch: 0 });
    goToBookmark(map, { name: 'a', extent: [1, 2, 3, 4] });
    expect(map.fitBounds).toHaveBeenCalledWith(
      [[1, 2], [3, 4]],
      expect.objectContaining({ bearing: 0, pitch: 0, padding: 0, maxZoom: 18, duration: 800 }),
    );
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
