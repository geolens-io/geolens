import type { Layer } from '@deck.gl/core';
import { Tile3DLayer } from '@deck.gl/geo-layers';
import { Tiles3DLoader } from '@loaders.gl/3d-tiles';
// The package entry also bundles the 370 kB encoder; the viewer only decodes.
import createDracoDecoderModule from 'draco3d/draco_decoder_nodejs.js';
import dracoWasmUrl from 'draco3d/draco_decoder.wasm?url';
import { separateMeshoptFallbackViews } from './glb-meshopt-layout';
import { requestUrl } from './dataset-fetch';

// A content-less root meets loaders.gl's default error budget of 8 px at the
// page's fit-to-extent zoom, so traversal would stop there and draw nothing.
const MAXIMUM_SCREEN_SPACE_ERROR = 2;

// loaders.gl's default Draco path starts a blob worker that imports from a CDN
// and evals; this module decodes on the main thread with the wasm served from
// the app origin.
const draco3dModule = {
  createDecoderModule: (options: Record<string, unknown> = {}) =>
    createDracoDecoderModule({
      ...options,
      locateFile: (path: string) => (path.endsWith('.wasm') ? dracoWasmUrl : path),
    }),
};

// loaders.gl reads the feature-ID extensions before meshopt and Draco decode,
// so they see compressed views. The viewer uses no per-feature data.
const gltf = { excludeExtensions: { EXT_mesh_features: false, EXT_structural_metadata: false } };

export interface TilesetViewport {
  cartographicCenter: [longitude: number, latitude: number, height: number];
  zoom: number;
}

async function startsWithGlbMagic(response: Response): Promise<boolean> {
  const reader = response.clone().body?.getReader();
  if (!reader) return false;
  try {
    const { value } = await reader.read();
    // "glTF", little-endian
    return !!value && value.length >= 4 && new DataView(value.buffer, value.byteOffset).getUint32(0, true) === 0x46546c67;
  } finally {
    void reader.cancel();
  }
}

export function createTilesetLayers(
  tilesetUrl: string,
  datasetFetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
  handlers: { onLoad: (viewport: TilesetViewport) => void; onError: (message: string) => void },
): Layer[] {
  // deck.gl rejects a failed or unparseable root tileset.json before any tile
  // exists, so onTileError never fires for it; the fetch reports it instead.
  const tileFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(requestUrl(input), window.location.origin).pathname;
    let response: Response;
    try {
      response = await datasetFetch(input, init);
    } catch (error) {
      handlers.onError(String(error));
      throw error;
    }
    if (!response.ok) {
      handlers.onError(`${path}: ${response.status}`);
      return response;
    }
    if (path === new URL(tilesetUrl, window.location.origin).pathname) {
      await response.clone().json().catch((error: unknown) => handlers.onError(String(error)));
      return response;
    }
    // Sniffed by content, so a GLB under any extension gets the fix, and any
    // other tile is left unread. loaders.gl resolves relative references
    // against response.url, which a new Response does not carry, so it is
    // copied over.
    if (!(await startsWithGlbMagic(response))) return response;
    const body = separateMeshoptFallbackViews(await response.arrayBuffer());
    const headers = new Headers(response.headers);
    headers.delete('content-length');
    const adapted = new Response(body, { status: response.status, statusText: response.statusText, headers });
    Object.defineProperty(adapted, 'url', { value: response.url });
    return adapted;
  };
  // Parse failures on the root tileset (valid JSON that does not normalise)
  // reject deck.gl's own load before onTileError exists.
  const loader = {
    ...Tiles3DLoader,
    parse: async (...args: Parameters<typeof Tiles3DLoader.parse>) => {
      try {
        return await Tiles3DLoader.parse(...args);
      } catch (error) {
        handlers.onError(String(error));
        throw error;
      }
    },
  };
  return [
    new Tile3DLayer({
      id: 'dataset-tileset',
      data: tilesetUrl,
      loader,
      loadOptions: {
        // CDN: null keeps loaders.gl from fetching decoders (KTX2's Basis
        // transcoder) from a public CDN; a tileset that needs one fails here.
        core: { fetch: tileFetch, worker: false, CDN: null },
        modules: { draco3d: draco3dModule },
        gltf,
        tileset: { maximumScreenSpaceError: MAXIMUM_SCREEN_SPACE_ERROR },
      },
      onTilesetLoad: (tileset) => handlers.onLoad(tileset as unknown as TilesetViewport),
      onTileError: (_tile, url, message) => handlers.onError(`${url}: ${message}`),
    }),
  ];
}
