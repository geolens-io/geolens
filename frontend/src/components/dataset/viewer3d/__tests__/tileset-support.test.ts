import { describe, expect, it } from 'vitest';
import type { TilesetMetadata } from '@/types/api';
import { viewableTilesetUrl } from '../tileset-support';

const base: TilesetMetadata = { url: '/api/datasets/x/tiles3d/tileset.json' };

describe('viewableTilesetUrl', () => {
  it('views a tileset with unrecorded facts', () => {
    expect(viewableTilesetUrl({ ...base, content_types: null, extensions_required: null })).toBe(base.url);
  });

  it.each([['b3dm'], ['glb'], ['b3dm', 'i3dm', 'subtree']])('views content %s', (...types) => {
    expect(viewableTilesetUrl({ ...base, content_types: types, extensions_required: [] })).toBe(base.url);
  });

  it.each(['vctr', 'geom', 'voxl', 'cmpt', 'gltf'])('refuses %s content', (type) => {
    expect(viewableTilesetUrl({ ...base, content_types: ['b3dm', type] })).toBeNull();
  });

  it.each([
    'KHR_texture_basisu',
    '3DTILES_content_voxels',
    '3DTILES_multiple_contents',
    '3DTILES_implicit_tiling',
  ])('refuses the %s extension', (name) => {
    expect(viewableTilesetUrl({ ...base, extensions_required: ['KHR_draco_mesh_compression', name] })).toBeNull();
  });

  it('views Draco and meshopt tilesets', () => {
    expect(
      viewableTilesetUrl({ ...base, extensions_required: ['KHR_draco_mesh_compression', 'EXT_meshopt_compression'] }),
    ).toBe(base.url);
  });

  it('has nothing to view without a published tileset', () => {
    expect(viewableTilesetUrl(null)).toBeNull();
    expect(viewableTilesetUrl(undefined)).toBeNull();
  });
});
