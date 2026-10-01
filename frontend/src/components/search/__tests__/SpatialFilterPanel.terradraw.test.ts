import { TerraDraw, TerraDrawRectangleMode } from 'terra-draw';
import { bboxToRings } from '../SpatialFilterPanel';

// Terra Draw validates what it is given; a stub would hide the constraints
// (longitudes within +/-180, at most nine decimals) the restore path must meet.
function startDraw() {
  const noop = () => undefined;
  const adapter: Record<string, unknown> = {
    project: () => ({ x: 0, y: 0 }),
    unproject: () => ({ lng: 0, lat: 0 }),
    getMapEventElement: () => document.createElement('div'),
    getLngLatFromEvent: () => ({ lng: 0, lat: 0 }),
    getCoordinatePrecision: () => 9,
  };
  const td = new TerraDraw({
    adapter: new Proxy(adapter, { get: (t, k: string) => (k in t ? t[k] : noop) }) as never,
    modes: [new TerraDrawRectangleMode()],
  });
  td.start();
  return td;
}

const feature = (ring: number[][], n: number) => ({
  id: `${n}${n}${n}${n}${n}${n}${n}${n}-${n}${n}${n}${n}-4${n}${n}${n}-8${n}${n}${n}-${String(n).repeat(12)}`,
  type: 'Feature',
  properties: { mode: 'rectangle' },
  geometry: { type: 'Polygon', coordinates: [ring] },
}) as never;

describe('bboxToRings against Terra Draw validation', () => {
  it('produces rings Terra Draw accepts for an unrounded box', () => {
    const [ring] = bboxToRings('-47.37000000000001,20.1234567891234,41.06,30');
    expect(startDraw().addFeatures([feature(ring, 1)])[0].valid).toBe(true);
  });

  it('produces rings Terra Draw accepts for a box across the antimeridian', () => {
    const results = startDraw().addFeatures(
      bboxToRings('172.45,9.82,-137.92,32.2').map((ring, i) => feature(ring, i + 2)),
    );
    expect(results.map((r) => r.valid)).toEqual([true, true]);
  });

  it('rejects the unrounded or past-180 shapes the helper avoids', () => {
    const td = startDraw();
    const unrounded = [[-47.37000000000001, 20], [41, 20], [41, 30], [-47.37000000000001, 30], [-47.37000000000001, 20]];
    const past180 = [[172, 9], [222, 9], [222, 30], [172, 30], [172, 9]];
    expect(td.addFeatures([feature(unrounded, 4)])[0].valid).toBe(false);
    expect(td.addFeatures([feature(past180, 5)])[0].valid).toBe(false);
  });
});
