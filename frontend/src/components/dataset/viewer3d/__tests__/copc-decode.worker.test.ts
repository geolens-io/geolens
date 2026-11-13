import { beforeAll, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ channels: [] as number[] }));
vi.mock('copc', () => ({
  Copc: {
    loadPointDataView: async () => ({
      pointCount: 2,
      dimensions: { Red: {}, Green: {}, Blue: {} },
      getter: (name: string) => (i: number) =>
        ({ X: 0, Y: 0, Z: 0, Classification: 0, Red: h.channels[i], Green: h.channels[i], Blue: h.channels[i] })[name] ?? 0,
    }),
  },
}));
vi.mock('proj4', () => ({ default: () => ({ forward: ([x, y]: number[]) => [x, y] }) }));
vi.mock('laz-perf/lib/worker/index.js', () => ({ createLazPerf: async () => ({}) }));
vi.mock('laz-perf/lib/worker/laz-perf.wasm?url', () => ({ default: '/laz-perf.wasm' }));
vi.mock('../copc-decode-limits', () => ({ checkDecodeLimits: () => undefined }));

type Handler = (event: { data: unknown }) => Promise<void>;
const posted: { colors?: Uint8Array; colorShift?: number }[] = [];

describe('decode worker colour depth', () => {
  beforeAll(async () => {
    vi.stubGlobal('self', { onmessage: null, postMessage: (m: never) => posted.push(m) });
    await import('../copc-decode.worker');
  });

  it('reads 16-bit colour from the node itself even when the cloud answer so far is 8-bit', async () => {
    h.channels = [4096, 65535];
    const request = {
      id: 1,
      copc: { header: { min: [0, 0, 0], max: [1, 1, 1] } },
      node: { pointDataOffset: 0 },
      bytes: new ArrayBuffer(8),
      horizontalWkt: 'x',
      zToMeters: 1,
      origin: [0, 0],
      colorShift: 0,
    };
    await (self as unknown as { onmessage: Handler }).onmessage({ data: request });
    expect(posted[0].colorShift).toBe(8);
    expect([...posted[0].colors!]).toEqual([16, 16, 16, 255, 255, 255, 255, 255]);
  });
});
