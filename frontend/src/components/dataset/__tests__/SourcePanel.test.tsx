import { render, screen } from '@/test/test-utils';
import { useDatasetVersions } from '@/components/dataset/hooks/use-dataset';
import { useVrtGenerations, useVrtSources, useVrtStatus } from '@/components/import/hooks/use-vrt';
import { useAuthStore } from '@/stores/auth-store';
import { SourcePanel } from '../SourcePanel';
import type { DatasetResponse } from '@/types/api';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetVersions: vi.fn(),
}));

vi.mock('@/components/import/hooks/use-vrt', () => ({
  useVrtSources: vi.fn(),
  useVrtStatus: vi.fn(),
  useVrtGenerations: vi.fn(),
}));

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'dataset-1',
    record_id: 'record-1',
    table_name: 'ds_parks',
    title: 'Parks',
    summary: null,
    srid: 4326,
    geometry_type: 'Polygon',
    feature_count: 1234,
    extent_bbox: null,
    column_info: null,
    license: null,
    source_organization: null,
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: 'geojson',
    source_filename: 'parks.geojson',
    tile_columns: null,
    original_srid: 4326,
    visibility: 'public',
    created_by: null,
    created_by_display: 'admin',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    last_edited_by_display: null,
    last_edited_at: null,
    record_status: 'published',
    lineage_summary: null,
    update_frequency: 'monthly',
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    theme_category: null,
    owner_org: null,
    published_at: null,
    updated_by: null,
    current_version: 2,
    source_url: null,
    origin: 'upload',
    origin_uri: null,
    origin_ref: { kind: 'upload', filename: 'parks.geojson', file_hash: 'sha256:abc123' },
    last_refreshed_at: '2026-08-01T14:30:00Z',
    last_checked_at: '2026-08-02T14:30:00Z',
    source_health: 'healthy',
    source_health_detail: null,
    schema_drift_status: 'none',
    source_freshness: 'fresh',
    quality_statement: null,
    collections: null,
    record_type: 'vector_dataset',
    raster: null,
    ...overrides,
  };
}

beforeEach(() => {
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  vi.mocked(useDatasetVersions).mockReturnValue({
    data: {
      versions: [{
        id: 'version-2',
        dataset_id: 'dataset-1',
        version_number: 2,
        source_filename: 'parks-v2.geojson',
        source_format: 'geojson',
        feature_count: 1234,
        srid: 4326,
        geometry_type: 'Polygon',
        file_hash: 'sha256:def456',
        uploaded_by: null,
        uploaded_at: '2026-08-01T14:30:00Z',
      }],
      total: 1,
    },
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useDatasetVersions>);
  vi.mocked(useVrtSources).mockReturnValue({
    data: { sources: [] },
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useVrtSources>);
  vi.mocked(useVrtStatus).mockReturnValue({
    data: { status: 'ready', last_generation_at: null, source_count: 0, active_generation: null, source_health: [] },
  } as unknown as ReturnType<typeof useVrtStatus>);
  vi.mocked(useVrtGenerations).mockReturnValue({
    data: { generations: [], total: 0 },
  } as unknown as ReturnType<typeof useVrtGenerations>);
});

describe('SourcePanel', () => {
  it('renders source state, pointer details, history, and the optional action seam', () => {
    render(
      <SourcePanel
        dataset={makeDataset()}
        actions={<button type="button">Future source action</button>}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Source' })).toBeInTheDocument();
    expect(screen.getByTestId('origin-badge')).toHaveAttribute('data-origin', 'upload');
    expect(screen.getByText('Owned copy')).toBeInTheDocument();
    expect(screen.getByText('parks.geojson')).toBeInTheDocument();
    expect(screen.getByText('sha256:abc123')).toBeInTheDocument();
    expect(screen.getByText('1,234')).toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
    expect(screen.getByText('Fresh')).toBeInTheDocument();
    expect(screen.getByText('No drift')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Source history' })).toBeInTheDocument();
    expect(screen.getByText(/parks-v2\.geojson/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Future source action' })).toBeInTheDocument();
  });

  it('does not reconstruct the initial source from current fields after a reupload', () => {
    render(<SourcePanel dataset={makeDataset()} />);

    const initialVersion = screen.getByText('Version 1').closest('li');
    expect(initialVersion).not.toBeNull();
    expect(initialVersion).toHaveTextContent('Catalog source');
    expect(initialVersion).not.toHaveTextContent('parks.geojson');
    expect(initialVersion).not.toHaveTextContent('1,234 features');
  });

  it('pluralizes a single feature in source history', () => {
    vi.mocked(useDatasetVersions).mockReturnValue({
      data: {
        versions: [{
          id: 'version-1',
          dataset_id: 'dataset-1',
          version_number: 1,
          source_filename: 'parks.geojson',
          source_format: 'geojson',
          feature_count: 1,
          srid: 4326,
          geometry_type: 'Polygon',
          file_hash: null,
          uploaded_by: null,
          uploaded_at: '2026-08-01T14:30:00Z',
        }],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetVersions>);

    render(<SourcePanel dataset={makeDataset({ current_version: 1 })} />);

    expect(screen.getByText(/parks\.geojson · 1 feature$/)).toBeInTheDocument();
    expect(screen.queryByText(/1 features/)).not.toBeInTheDocument();
  });

  it.each([
    {
      name: 'registered PostGIS table',
      overrides: {
        origin: 'postgis' as const,
        source_format: null,
        origin_ref: { kind: 'postgis', table_name: 'data.parks' },
      },
      storage: 'Registered in place',
      pointer: 'data.parks',
    },
    {
      name: 'STAC asset',
      overrides: {
        origin: 'stac' as const,
        source_format: 'stac',
        origin_ref: { kind: 'stac', collection_id: 'landsat', asset_key: 'visual' },
      },
      storage: 'Remote reference',
      pointer: 'landsat',
    },
    {
      name: 'created dataset',
      overrides: {
        origin: 'created' as const,
        source_format: 'created',
        origin_ref: null,
      },
      storage: 'Owned copy',
      pointer: null,
    },
  ])('uses type-appropriate storage copy for a $name', ({ overrides, storage, pointer }) => {
    render(<SourcePanel dataset={makeDataset(overrides)} />);

    expect(screen.getByText(storage)).toBeInTheDocument();
    if (pointer) expect(screen.getByText(pointer)).toBeInTheDocument();
  });

  it('shows only allowlisted, credential-free service pointer information', () => {
    const { container } = render(
      <SourcePanel
        dataset={makeDataset({
          origin: 'service',
          source_format: 'arcgis_featureserver',
          origin_uri: 'https://fallback:password@origin.test/FeatureServer/7?token=fallback-secret',
          origin_ref: {
            kind: 'service',
            service_type: 'arcgis_featureserver',
            layer_id: '7',
            url: 'https://user:password@origin.test/FeatureServer?token=secret#private',
            token: 'must-never-render',
            authorization: 'Bearer hidden',
          },
          source_health: 'inaccessible',
          source_health_detail: 'unauthorized',
          schema_drift_status: 'drifted',
          source_freshness: 'overdue',
        })}
      />,
    );

    expect(screen.getByText('Owned copy')).toBeInTheDocument();
    expect(screen.getByText('arcgis_featureserver')).toBeInTheDocument();
    expect(screen.getByText('https://origin.test/FeatureServer')).toBeInTheDocument();
    expect(screen.getByText('The source now requires access GeoLens does not have.')).toBeInTheDocument();
    expect(screen.getByText('Drift detected')).toBeInTheDocument();
    expect(screen.getByText('Overdue')).toBeInTheDocument();
    expect(container.innerHTML).not.toContain('password');
    expect(container.innerHTML).not.toContain('token=');
    expect(container.innerHTML).not.toContain('must-never-render');
    expect(container.innerHTML).not.toContain('Bearer hidden');
  });

  it('suppresses an origin_ref whose discriminator does not match the dataset origin', () => {
    const { container } = render(
      <SourcePanel
        dataset={makeDataset({
          origin: 'postgis',
          source_format: null,
          origin_ref: { kind: 'service', table_name: 'secret_table', token: 'secret' },
        })}
      />,
    );

    expect(container.innerHTML).not.toContain('secret_table');
    expect(container.innerHTML).not.toContain('secret');
  });

  it('absorbs VRT members and generation history without mutation controls', () => {
    useAuthStore.setState({ token: 'viewer-token' });
    vi.mocked(useVrtSources).mockReturnValue({
      data: {
        sources: [{
          dataset_id: 'member-1',
          title: 'Elevation tile',
          position: 0,
          band_count: 1,
          resolution_x: 0.25,
          resolution_y: 0.25,
          crs_epsg: 4326,
          extent_bbox: null,
        }],
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useVrtSources>);
    vi.mocked(useVrtStatus).mockReturnValue({
      data: {
        status: 'ready',
        last_generation_at: '2026-08-02T00:00:00Z',
        source_count: 1,
        active_generation: null,
        source_health: [{ dataset_id: 'member-1', title: 'Elevation tile', status: 'healthy' }],
      },
    } as unknown as ReturnType<typeof useVrtStatus>);
    vi.mocked(useVrtGenerations).mockReturnValue({
      data: {
        generations: [
          {
            id: 'generation-1',
            status: 'failed',
            started_at: '2026-08-02T00:00:00Z',
            completed_at: '2026-08-02T00:00:01Z',
            duration_seconds: 1,
            error_message: 'https://source.test/?token=must-not-render',
            source_count: 1,
            triggered_by: 'system',
          },
          {
            id: 'generation-2',
            status: 'pending',
            started_at: '2026-08-03T00:00:00Z',
            completed_at: null,
            duration_seconds: null,
            error_message: null,
            source_count: 1,
            triggered_by: 'user',
          },
        ],
        total: 2,
      },
    } as unknown as ReturnType<typeof useVrtGenerations>);

    const { container } = render(
      <SourcePanel
        dataset={makeDataset({
          origin: null,
          origin_ref: null,
          source_format: null,
          record_type: 'vrt_dataset',
          feature_count: null,
          raster: {
            epsg: 4326,
            res_x: 0.25,
            res_y: 0.25,
            band_count: 1,
            nodata: null,
            compression: null,
            width: 10,
            height: 10,
            size_bytes: null,
            tile_url: null,
            bands: [],
            connect: null,
            status: 'ready',
            vrt_type: 'mosaic',
            source_count: 1,
            resolution_strategy: 'finest',
          },
        })}
      />,
    );

    expect(screen.getByRole('heading', { name: 'VRT members' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'VRT member sources' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Elevation tile' })).toHaveAttribute('href', '/datasets/member-1');
    expect(screen.getByRole('region', { name: 'Generation history' })).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/refresh now|regenerate|add source|remove source/i);
    expect(container.innerHTML).not.toContain('must-not-render');
    expect(useVrtSources).toHaveBeenCalledWith('dataset-1');
    expect(useVrtStatus).toHaveBeenCalledWith('dataset-1', false);
    expect(useVrtGenerations).toHaveBeenCalledWith('dataset-1');
  });

  it('keeps the universal panel visible but disables authenticated VRT queries for anonymous readers', () => {
    render(
      <SourcePanel
        dataset={makeDataset({
          origin: null,
          origin_ref: null,
          record_type: 'vrt_dataset',
          raster: null,
        })}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Source' })).toBeInTheDocument();
    expect(screen.getByText('Sign in to view VRT member details.')).toBeInTheDocument();
    expect(useVrtSources).toHaveBeenCalledWith('');
    expect(useVrtStatus).toHaveBeenCalledWith('', false);
    expect(useVrtGenerations).toHaveBeenCalledWith('');
  });
});
