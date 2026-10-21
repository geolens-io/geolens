import { Copc, type Hierarchy } from 'copc';
import proj4 from 'proj4';
// The worker build of laz-perf; the default (web) build refuses to start in a worker.
import { createLazPerf } from 'laz-perf/lib/worker/index.js';
import lazPerfWasmUrl from 'laz-perf/lib/worker/laz-perf.wasm?url';
import { colorShiftFor } from './copc-color';
import { checkDecodeLimits } from './copc-decode-limits';
import { MAX_NODE_POINTS } from './copc-limits';

export interface DecodeRequest {
  id: number;
  copc: Copc;
  node: Hierarchy.Node;
  bytes: ArrayBuffer;
  horizontalWkt: string;
  zToMeters: number;
  origin: [number, number];
}

export interface DecodeResponse {
  id: number;
  count: number;
  positions?: Float32Array;
  colors?: Uint8Array;
  error?: string;
}

// The app's tsconfig has no webworker lib, and adding one retypes every global.
const scope = self as unknown as {
  onmessage: ((event: MessageEvent<DecodeRequest>) => void) | null;
  postMessage(message: DecodeResponse, transfer?: Transferable[]): void;
};

// Served from the app origin under the 'wasm-unsafe-eval' CSP; never a CDN.
const lazPerfPromise = createLazPerf({
  locateFile: (path: string) => (path.endsWith('.wasm') ? lazPerfWasmUrl : path),
});

const CLASS_COLORS: Record<number, [number, number, number]> = {
  2: [166, 124, 82], // ground
  3: [120, 190, 90],
  4: [70, 160, 60],
  5: [30, 120, 40], // vegetation
  6: [220, 80, 60], // building
  9: [60, 120, 220], // water
};

/** Low to high: blue, green, yellow, red. */
function elevationColor(t: number): [number, number, number] {
  const stops: [number, number, number][] = [
    [60, 90, 200],
    [60, 180, 120],
    [240, 220, 70],
    [210, 60, 50],
  ];
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const i = Math.min(Math.floor(x), stops.length - 2);
  const f = x - i;
  return [0, 1, 2].map((c) => Math.round(stops[i][c] + (stops[i + 1][c] - stops[i][c]) * f)) as [number, number, number];
}

scope.onmessage = async (event: MessageEvent<DecodeRequest>) => {
  const request = event.data;
  const { id, copc, node, bytes, horizontalWkt, zToMeters, origin } = request;
  try {
    checkDecodeLimits(request);
    const lazPerf = await lazPerfPromise;
    const buffer = new Uint8Array(bytes);
    const getter = async (begin: number, end: number) =>
      buffer.subarray(begin - node.pointDataOffset, end - node.pointDataOffset);
    const view = await Copc.loadPointDataView(getter, copc, node, { lazPerf });
    const count = view.pointCount;
    if (count > MAX_NODE_POINTS) throw new Error('decoded point count outside the cap');
    const x = view.getter('X');
    const y = view.getter('Y');
    const z = view.getter('Z');
    const hasRgb = 'Red' in view.dimensions;
    const r = hasRgb ? view.getter('Red') : null;
    const g = hasRgb ? view.getter('Green') : null;
    const b = hasRgb ? view.getter('Blue') : null;
    const cls = view.getter('Classification');
    const toLngLat = proj4(horizontalWkt, 'EPSG:4326');
    const zMin = copc.header.min[2];
    const zRange = Math.max(copc.header.max[2] - zMin, Number.EPSILON);
    // LAS colour is 16-bit, but some writers store 8-bit values in the fields.
    let colorMax = 0;
    if (r && g && b) {
      for (let i = 0; i < count; i++) colorMax = Math.max(colorMax, r(i), g(i), b(i));
    }
    const colorShift = colorShiftFor(colorMax);
    const positions = new Float32Array(count * 3);
    const colors = new Uint8Array(count * 4);
    for (let i = 0; i < count; i++) {
      const [lng, lat] = toLngLat.forward([x(i), y(i)]);
      positions[i * 3] = lng - origin[0];
      positions[i * 3 + 1] = lat - origin[1];
      positions[i * 3 + 2] = (z(i) - zMin) * zToMeters;
      if (r && g && b && (r(i) || g(i) || b(i))) {
        colors[i * 4] = r(i) >> colorShift;
        colors[i * 4 + 1] = g(i) >> colorShift;
        colors[i * 4 + 2] = b(i) >> colorShift;
      } else {
        colors.set(CLASS_COLORS[cls(i)] ?? elevationColor((z(i) - zMin) / zRange), i * 4);
      }
      colors[i * 4 + 3] = 255;
    }
    const response: DecodeResponse = { id, count, positions, colors };
    scope.postMessage(response, [positions.buffer, colors.buffer]);
  } catch (error) {
    scope.postMessage({ id, count: 0, error: String(error) } satisfies DecodeResponse);
  }
};
