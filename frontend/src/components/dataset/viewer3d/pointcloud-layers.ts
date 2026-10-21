import { COORDINATE_SYSTEM, type Layer } from '@deck.gl/core';
import { PointCloudLayer } from '@deck.gl/layers';
import { Copc } from 'copc';
import proj4 from 'proj4';
import { makeRangeGetter } from './copc-getter';
import { parseCopcCrs } from './copc-crs';
import { POINT_BUDGET } from './copc-limits';
import { selectNodes } from './copc-select';
import type { DecodeRequest, DecodeResponse } from './copc-decode.worker';

type DatasetFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

const DECODE_WORKERS = 2;

interface PointCloudHandlers {
  onLayer: (layer: Layer) => void;
  onError: (message: string) => void;
}

/**
 * Reads a COPC file through the guarded fetch and hands its nodes, coarsest
 * first, to `onLayer` as deck.gl point layers. Returns a function that stops
 * the load and releases the decode workers.
 */
export function loadPointCloud(
  url: string,
  fileSize: number | null,
  datasetFetch: DatasetFetch,
  handlers: PointCloudHandlers,
): () => void {
  const abort = new AbortController();
  const workers: Worker[] = [];
  const stop = () => {
    abort.abort();
    workers.forEach((worker) => worker.terminate());
  };

  void (async () => {
    const getter = makeRangeGetter(datasetFetch, url, fileSize, abort.signal);
    const copc = await Copc.create(getter);
    const crs = parseCopcCrs(copc.wkt);
    if (!crs) throw new Error('COPC CRS is not supported');
    const [minX, minY] = copc.header.min;
    const [maxX, maxY] = copc.header.max;
    const toLngLat = proj4(crs.horizontalWkt, 'EPSG:4326');
    const origin = toLngLat.forward([(minX + maxX) / 2, (minY + maxY) / 2]) as [number, number];
    if (!origin.every(Number.isFinite)) throw new Error('COPC extent cannot be placed');

    const { nodes } = await Copc.loadHierarchyPage(getter, copc.info.rootHierarchyPage);
    const queue = selectNodes(nodes, POINT_BUDGET, copc.header.pointDataRecordLength, fileSize);
    if (queue.length === 0) throw new Error('COPC has no node the viewer can read');

    const pending = new Map<number, (response: DecodeResponse) => void>();
    for (let i = 0; i < DECODE_WORKERS; i++) {
      const worker = new Worker(new URL('./copc-decode.worker.ts', import.meta.url), { type: 'module' });
      worker.onmessage = (event: MessageEvent<DecodeResponse>) => pending.get(event.data.id)?.(event.data);
      worker.onerror = (event) => {
        handlers.onError(`worker: ${event.message}`);
        // A dead worker never answers; settle its requests so the load ends.
        pending.forEach((resolve, id) => resolve({ id, count: 0, error: 'worker failed' }));
      };
      workers.push(worker);
    }
    // The viewer reads core dimensions only; the extra-bytes table is untrusted
    // and its builders are quadratic in the entry count, so it stays behind.
    const workerCopc = { ...copc, eb: [] };
    let nextId = 0;
    const run = async (worker: Worker) => {
      for (let entry = queue.shift(); entry && !abort.signal.aborted; entry = queue.shift()) {
        const [key, node] = entry;
        const compressed = await Copc.loadCompressedPointDataBuffer(getter, node);
        const bytes = compressed.slice().buffer;
        const id = nextId++;
        const result = await new Promise<DecodeResponse>((resolve) => {
          pending.set(id, resolve);
          const request: DecodeRequest = { id, copc: workerCopc, node, bytes, horizontalWkt: crs.horizontalWkt, zToMeters: crs.zToMeters, origin };
          worker.postMessage(request, [bytes]);
        });
        pending.delete(id);
        if (abort.signal.aborted) return;
        if (result.error || !result.positions || !result.colors) {
          handlers.onError(`node ${key}: ${result.error}`);
          continue;
        }
        handlers.onLayer(
          new PointCloudLayer({
            id: `copc-${key}`,
            data: {
              length: result.count,
              attributes: {
                getPosition: { value: result.positions, size: 3 },
                getColor: { value: result.colors, size: 4 },
              },
            },
            coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
            coordinateOrigin: [origin[0], origin[1], 0],
            pointSize: 1.5,
            sizeUnits: 'pixels',
          }),
        );
      }
    };
    await Promise.all(workers.map(run));
    workers.forEach((worker) => worker.terminate());
  })().catch((error: unknown) => {
    if (!abort.signal.aborted) handlers.onError(String(error));
  });

  return stop;
}
