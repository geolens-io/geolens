import { render, screen } from '@/test/test-utils';
import { DatasetStatsBar } from '../DatasetStatsBar';
import type { DatasetResponse } from '@/types/api';
import type { RasterMetadata } from '@/types/api';

const BASE: DatasetResponse = {
  id: 'ds-1',
  record_id: 'rec-1',
  table_name: 'parks',
  title: 'Parks',
  summary: null,
  srid: 4326,
  geometry_type: 'Polygon',
  feature_count: 100,
  extent_bbox: [-74, 40, -73, 41],
  column_info: [
    { name: 'id', type: 'bigint' },
    { name: 'name', type: 'text' },
    { name: 'geom', type: 'geometry' },
  ],
  license: null,
  source_organization: null,
  data_vintage_start: null,
  data_vintage_end: null,
  source_format: null,
  source_filename: null,
  original_srid: null,
  visibility: 'public',
  created_by: null,
  created_by_display: 'admin',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
  last_edited_by_display: null,
  last_edited_at: null,
  record_status: 'published',
  lineage_summary: null,
  update_frequency: null,
  usage_constraints: null,
  access_constraints: null,
  sensitivity_classification: null,
  theme_category: null,
  owner_org: null,
  published_at: null,
  updated_by: null,
  current_version: 1,
  source_url: null,
  quality_statement: null,
  collections: null,
  tile_columns: null,
  record_type: 'vector_dataset',
  raster: null,
};

const RASTER_META: RasterMetadata = {
  epsg: 32618,
  res_x: 1.0,
  res_y: -1.0,
  band_count: 3,
  nodata: null,
  compression: 'deflate',
  width: 1024,
  height: 768,
  size_bytes: 5242880,
  tile_url: null,
  bands: [],
  connect: null,
  status: null,
  vrt_type: null,
  source_count: null,
  resolution_strategy: null,
};

describe('DatasetStatsBar', () => {
  it('renders vector dataset with feature count and CRS', () => {
    render(<DatasetStatsBar dataset={BASE} />);
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('EPSG:4326')).toBeInTheDocument();
  });

  it('renders raster dataset with EPSG and resolution', () => {
    const ds: DatasetResponse = {
      ...BASE,
      record_type: 'raster_dataset',
      geometry_type: null,
      feature_count: null,
      column_info: null,
      srid: null,
      extent_bbox: null,
      raster: RASTER_META,
    };
    render(<DatasetStatsBar dataset={ds} />);
    expect(screen.getByText('EPSG:32618')).toBeInTheDocument();
    expect(screen.getByText('1 m')).toBeInTheDocument();
  });

  it('renders VRT source count', () => {
    const ds: DatasetResponse = {
      ...BASE,
      record_type: 'vrt_dataset',
      geometry_type: null,
      feature_count: null,
      column_info: null,
      srid: null,
      extent_bbox: null,
      raster: { ...RASTER_META, source_count: 4, vrt_type: 'mosaic', compression: null, size_bytes: null },
    };
    render(<DatasetStatsBar dataset={ds} />);
    expect(screen.getByText('4')).toBeInTheDocument();
  });

  it('caps at 6 cells', () => {
    const { container } = render(<DatasetStatsBar dataset={BASE} />);
    const grid = container.firstElementChild!;
    expect(grid.children.length).toBeLessThanOrEqual(6);
  });
});
