import { beforeEach, describe, expect, it, vi } from 'vitest';

const captured = vi.hoisted(() => ({ props: null as null | Record<string, any> })); // eslint-disable-line @typescript-eslint/no-explicit-any

vi.mock('@deck.gl/geo-layers', () => ({
  Tile3DLayer: class {
    constructor(props: Record<string, unknown>) {
      captured.props = props;
    }
  },
}));
const parse = vi.hoisted(() => vi.fn());
vi.mock('@loaders.gl/3d-tiles', () => ({ Tiles3DLoader: { id: '3d-tiles', parse } }));
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

  it('fixes overlapping meshopt views in a GLB whatever its URL ends with', async () => {
    const { fetch } = captured.props!.loadOptions.core;
    const json = new TextEncoder().encode(
      JSON.stringify({
        buffers: [{ byteLength: 100, extensions: { EXT_meshopt_compression: { fallback: true } } }],
        bufferViews: [
          { buffer: 0, byteOffset: 0, byteLength: 40 },
          { buffer: 0, byteOffset: 0, byteLength: 24 },
        ],
      }),
    );
    const padded = Math.ceil(json.byteLength / 4) * 4;
    const glb = new Uint8Array(20 + padded);
    const view = new DataView(glb.buffer);
    view.setUint32(0, 0x46546c67, true);
    view.setUint32(8, glb.byteLength, true);
    view.setUint32(12, padded, true);
    view.setUint32(16, 0x4e4f534a, true);
    glb.set(json, 20);
    glb.fill(0x20, 20 + json.byteLength);
    const source = new Response(glb);
    Object.defineProperty(source, 'url', { value: 'http://localhost/api/datasets/d1/tiles3d/t/0.bin' });
    datasetFetch.mockResolvedValue(source);
    const adapted = await fetch('/api/datasets/d1/tiles3d/t/0.bin');
    // loaders.gl resolves relative references against response.url
    expect(adapted.url).toBe('http://localhost/api/datasets/d1/tiles3d/t/0.bin');
    const out = new Uint8Array(await adapted.arrayBuffer());
    const length = new DataView(out.buffer).getUint32(12, true);
    const fixed = JSON.parse(new TextDecoder().decode(out.subarray(20, 20 + length)));
    expect(fixed.bufferViews.map((v: { byteOffset: number }) => v.byteOffset)).toEqual([0, 48]);
  });

  it('reports a root tileset that parses as JSON but fails loaders.gl normalisation', async () => {
    parse.mockRejectedValue(new Error('bad tileset'));
    await expect(captured.props!.loader.parse({}, {}, {})).rejects.toThrow('bad tileset');
    expect(handlers.onError).toHaveBeenCalledTimes(1);
  });

  it('returns a non-GLB tile as it came, unread', async () => {
    const { fetch } = captured.props!.loadOptions.core;
    const source = new Response(new Uint8Array([0x62, 0x33, 0x64, 0x6d, 1, 2, 3, 4]));
    datasetFetch.mockResolvedValue(source);
    const out = await fetch('/api/datasets/d1/tiles3d/t/0.b3dm');
    expect(out).toBe(source);
    expect(source.bodyUsed).toBe(false);
  });
});
