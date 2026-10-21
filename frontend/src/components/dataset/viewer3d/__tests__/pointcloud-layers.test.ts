import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const copcMock = vi.hoisted(() => ({
  create: vi.fn(),
  loadHierarchyPage: vi.fn(),
  loadCompressedPointDataBuffer: vi.fn(),
}));
vi.mock('copc', () => ({ Copc: copcMock }));
vi.mock('proj4', () => ({ default: () => ({ forward: ([x, y]: number[]) => [x / 1e5, y / 1e5] }) }));
vi.mock('@deck.gl/core', () => ({ COORDINATE_SYSTEM: { LNGLAT_OFFSETS: 2 } }));
vi.mock('@deck.gl/layers', () => ({
  PointCloudLayer: class {
    props: { id: string };
    constructor(props: { id: string }) {
      this.props = props;
    }
  },
}));
vi.mock('../copc-crs', () => ({ parseCopcCrs: () => ({ horizontalWkt: 'PROJCS["x"]', zToMeters: 1 }) }));

import { loadPointCloud } from '../pointcloud-layers';

interface Posted {
  id: number;
  colorShift?: 0 | 8;
  copc: { eb: unknown[] };
}

describe('loadPointCloud', () => {
  const posted: Posted[] = [];

  beforeEach(() => {
    posted.length = 0;
    copcMock.create.mockResolvedValue({
      header: { min: [0, 0, 0], max: [10, 10, 5], pointDataRecordLength: 34 },
      info: { rootHierarchyPage: {} },
      wkt: 'x',
      eb: new Array(5000).fill({}),
    });
    const node = (offset: number) => ({ pointCount: 100, pointDataOffset: offset, pointDataLength: 50 });
    copcMock.loadHierarchyPage.mockResolvedValue({
      nodes: { '0-0-0-0': node(100), '1-0-0-0': node(200), '1-1-0-0': node(300) },
    });
    copcMock.loadCompressedPointDataBuffer.mockImplementation(async () => new Uint8Array(8));
    vi.stubGlobal(
      'Worker',
      class {
        onmessage: ((event: { data: unknown }) => void) | null = null;
        onerror: unknown = null;
        postMessage(request: Posted) {
          posted.push(request);
          // The first node (no shift given) detects 8-bit colour.
          queueMicrotask(() =>
            this.onmessage?.({
              data: { id: request.id, count: 1, positions: new Float32Array(3), colors: new Uint8Array(4), colorShift: request.colorShift ?? 0 },
            }),
          );
        }
        terminate() {}
      },
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  const run = () =>
    new Promise<string[]>((resolve) => {
      const ids: string[] = [];
      loadPointCloud('/api/datasets/d1/copc/a/data.copc.laz', null, async () => new Response(), {
        onLayer: (layer) => {
          ids.push((layer as unknown as { props: { id: string } }).props.id);
          if (ids.length === 3) resolve(ids);
        },
        onError: (message) => {
          throw new Error(message);
        },
      });
    });

  it('decodes the coarsest node alone first, and the rest with the colour depth it found', async () => {
    const ids = await run();
    expect(ids[0]).toBe('copc-0-0-0-0');
    expect(posted[0].colorShift).toBeUndefined();
    expect(posted.slice(1).map((p) => p.colorShift)).toEqual([0, 0]);
  });

  it('posts the COPC object to the workers without its untrusted extra-bytes table', async () => {
    await run();
    expect(posted.every((p) => p.copc.eb.length === 0)).toBe(true);
  });
});
