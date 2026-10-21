import { beforeEach, describe, expect, it, vi } from 'vitest';

const captured = vi.hoisted(() => ({ props: null as null | Record<string, any> })); // eslint-disable-line @typescript-eslint/no-explicit-any

vi.mock('@deck.gl/geo-layers', () => ({
  Tile3DLayer: class {
    constructor(props: Record<string, unknown>) {
      captured.props = props;
    }
  },
}));
vi.mock('@loaders.gl/3d-tiles', () => ({ Tiles3DLoader: {} }));
vi.mock('draco3d/draco_decoder_nodejs.js', () => ({ default: vi.fn() }));
vi.mock('draco3d/draco_decoder.wasm?url', () => ({ default: '/assets/draco_decoder.wasm' }));

import { createTilesetLayers } from '../tileset-layers';

const handlers = { onLoad: vi.fn(), onError: vi.fn() };
const URL_PATH = '/api/datasets/d1/tiles3d/tileset.json';

describe('createTilesetLayers', () => {
  const datasetFetch = vi.fn();
  beforeEach(() => {
    captured.props = null;
    handlers.onError.mockClear();
    datasetFetch.mockReset();
    datasetFetch.mockResolvedValue(new Response('{}'));
    createTilesetLayers(URL_PATH, datasetFetch, handlers);
  });

  it('keeps decoders on this origin: no CDN, no worker', () => {
    const core = captured.props!.loadOptions.core;
    expect(core.CDN).toBeNull();
    expect(core.worker).toBe(false);
  });

  it('routes every loader request through the dataset fetch', async () => {
    const { fetch } = captured.props!.loadOptions.core;
    await fetch(`${URL_PATH}`, { headers: { Range: 'bytes=0-1' } });
    expect(datasetFetch).toHaveBeenCalledWith(URL_PATH, { headers: { Range: 'bytes=0-1' } });
  });

  it('applies the meshopt layout fix to a .glb requested as a Request too', async () => {
    const { fetch } = captured.props!.loadOptions.core;
    const body = new Uint8Array([1, 2, 3]);
    datasetFetch.mockResolvedValue(new Response(body));
    const response = await fetch(new Request('http://localhost/api/datasets/d1/tiles3d/t/0.glb'));
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(body);
    expect(datasetFetch).toHaveBeenCalledTimes(1);
  });

  it('reports a failed or unparseable root tileset.json, which deck.gl rejects before any tile exists', async () => {
    const { fetch } = captured.props!.loadOptions.core;
    datasetFetch.mockResolvedValue(new Response('nope', { status: 404 }));
    await fetch(URL_PATH);
    expect(handlers.onError).toHaveBeenCalledTimes(1);
    datasetFetch.mockResolvedValue(new Response('<html>'));
    await fetch(URL_PATH);
    expect(handlers.onError).toHaveBeenCalledTimes(2);
    datasetFetch.mockRejectedValue(new Error('refused'));
    await expect(fetch(URL_PATH)).rejects.toThrow('refused');
    expect(handlers.onError).toHaveBeenCalledTimes(3);
  });

  it('does not report a readable root tileset.json', async () => {
    const { fetch } = captured.props!.loadOptions.core;
    await fetch(URL_PATH);
    expect(handlers.onError).not.toHaveBeenCalled();
  });
});
