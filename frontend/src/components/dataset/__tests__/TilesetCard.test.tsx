import { render, screen } from '@/test/test-utils';
import { TilesetCard } from '../TilesetCard';
import type { TilesetMetadata } from '@/types/api';

const TILESET: TilesetMetadata = {
  url: '/api/datasets/ds-1/tiles3d/tileset.json',
  size_bytes: 2 * 1024 * 1024,
  version: '1.1',
  geometric_error: 512,
  bounding_volume: 'region',
};

describe('TilesetCard', () => {
  it('shows the version, geometric error, bounding volume, size and a region extent', () => {
    render(<TilesetCard tileset={TILESET} extentBbox={[179.5, -17, -179.5, -16]} />);

    expect(screen.getByText('1.1')).toBeInTheDocument();
    expect(screen.getByText('512')).toBeInTheDocument();
    expect(screen.getByText('Region')).toBeInTheDocument();
    expect(screen.getByText('2 MB')).toBeInTheDocument();
    expect(screen.getByText('(179.5000, -17.0000) to (-179.5000, -16.0000)')).toBeInTheDocument();
  });

  it('says why a box or sphere tileset has no extent', () => {
    render(<TilesetCard tileset={{ ...TILESET, bounding_volume: 'sphere' }} extentBbox={null} />);

    expect(screen.getByText('Sphere')).toBeInTheDocument();
    expect(
      screen.getByText('Not available. GeoLens reads the extent only from a region bounding volume.'),
    ).toBeInTheDocument();
  });

  it('marks facts the tileset does not give as not available', () => {
    render(
      <TilesetCard
        tileset={{ ...TILESET, version: null, geometric_error: null, bounding_volume: null, size_bytes: null }}
        extentBbox={null}
      />,
    );

    expect(screen.getAllByText('N/A')).toHaveLength(5);
  });

  it('lists the content types and required extensions', () => {
    render(
      <TilesetCard
        tileset={{ ...TILESET, content_types: ['b3dm', 'pnts'], extensions_required: ['3DTILES_implicit_tiling'] }}
        extentBbox={null}
      />,
    );

    expect(screen.getByText('Content types')).toBeInTheDocument();
    expect(screen.getByText('b3dm, pnts')).toBeInTheDocument();
    expect(screen.getByText('Required extensions')).toBeInTheDocument();
    expect(screen.getByText('3DTILES_implicit_tiling')).toBeInTheDocument();
  });

  it('says none when the tileset requires no extension', () => {
    render(
      <TilesetCard tileset={{ ...TILESET, content_types: ['glb'], extensions_required: [] }} extentBbox={null} />,
    );

    expect(screen.getByText('None')).toBeInTheDocument();
  });

  it('leaves both lists out for a tileset published before they were recorded', () => {
    render(
      <TilesetCard tileset={{ ...TILESET, content_types: null, extensions_required: null }} extentBbox={null} />,
    );

    expect(screen.queryByText('Content types')).not.toBeInTheDocument();
    expect(screen.queryByText('Required extensions')).not.toBeInTheDocument();
  });
});
