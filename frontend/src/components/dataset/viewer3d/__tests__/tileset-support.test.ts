import { describe, expect, it } from 'vitest';
import type { TilesetMetadata } from '@/types/api';
import { canViewTileset } from '../tileset-support';

const base: TilesetMetadata = { url: '/api/datasets/x/tiles3d/tileset.json' };

describe('canViewTileset', () => {
  it('views a tileset with unrecorded facts', () => {
    expect(canViewTileset({ ...base, content_types: null, extensions_required: null })).toBe(true);
  });

  it.each([['b3dm'], ['glb'], ['b3dm', 'cmpt', 'subtree']])('views content %s', (...types) => {
    expect(canViewTileset({ ...base, content_types: types, extensions_required: [] })).toBe(true);
  });

  it.each(['vctr', 'geom', 'voxl'])('refuses %s content', (type) => {
    expect(canViewTileset({ ...base, content_types: ['b3dm', type] })).toBe(false);
  });

  it.each(['KHR_texture_basisu', '3DTILES_content_voxels'])('refuses the %s extension', (name) => {
    expect(canViewTileset({ ...base, extensions_required: ['KHR_draco_mesh_compression', name] })).toBe(false);
  });

  it('views Draco and meshopt tilesets', () => {
    expect(
      canViewTileset({ ...base, extensions_required: ['KHR_draco_mesh_compression', 'EXT_meshopt_compression'] }),
    ).toBe(true);
  });

  it('has nothing to view without a published tileset', () => {
    expect(canViewTileset(null)).toBe(false);
    expect(canViewTileset(undefined)).toBe(false);
  });
});
