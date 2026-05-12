import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import { DatasetSearchPanel } from '../DatasetSearchPanel';
import { searchDatasets } from '@/api/search';
import type { BasemapEntry } from '@/api/settings';
import type { MapLayerResponse, OGCRecordResponse, RecordType } from '@/types/api';

vi.mock('@/api/search', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/search')>();
  return { ...actual, searchDatasets: vi.fn() };
});

const mockBasemaps: BasemapEntry[] = [
  { id: 'openfreemap-positron', label: 'Positron', url: 'https://example.com/positron', enabled: true, is_preset: true },
  { id: 'openfreemap-dark', label: 'Dark', url: 'https://example.com/dark', enabled: true, is_preset: true },
  { id: 'disabled', label: 'Disabled', url: 'https://example.com/disabled', enabled: false, is_preset: true },
];

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: vi.fn(() => ({ data: mockBasemaps })),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

const mockSearchDatasets = vi.mocked(searchDatasets);

function makeRecord(overrides: {
  id: string;
  title: string;
  recordType?: RecordType;
  geometryType?: OGCRecordResponse['properties']['geometry_type'];
  sourceOrganization?: string | null;
  keywords?: string[] | null;
  featureCount?: number | null;
  hasQuicklook?: boolean;
}): OGCRecordResponse {
  return {
    type: 'Feature',
    id: overrides.id,
    geometry: null,
    bbox: null,
    links: [],
    properties: {
      type: 'Feature',
      title: overrides.title,
      description: `${overrides.title} description`,
      keywords: overrides.keywords ?? ['transport'],
      created: '2026-01-01T00:00:00Z',
      updated: '2026-01-02T00:00:00Z',
      updated_by_display: null,
      never_edited: false,
      crs: 'EPSG:4326',
      geometry_type: overrides.geometryType ?? 'POLYGON',
      feature_count: overrides.featureCount ?? 100,
      contacts: null,
      license: null,
      source_organization: overrides.sourceOrganization ?? 'City GIS',
      quality_detail: null,
      record_status: 'published',
      record_type: overrides.recordType ?? 'vector_dataset',
      has_quicklook: overrides.hasQuicklook ?? false,
    },
  };
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'roads',
    dataset_name: overrides.dataset_name ?? 'Roads',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'LINESTRING',
    dataset_table_name: overrides.dataset_table_name ?? 'roads',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: overrides.display_name ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_3d: overrides.is_3d ?? false,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  };
}

function defaultProps(overrides: Partial<React.ComponentProps<typeof DatasetSearchPanel>> = {}) {
  return {
    onAddDataset: vi.fn(),
    onDuplicateRendering: vi.fn(),
    layers: [],
    isAdding: false,
    basemapStyle: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    onBasemapChange: vi.fn(),
    onBasemapLabelsChange: vi.fn(),
    onBasemapConfigChange: vi.fn(),
    ...overrides,
  } satisfies React.ComponentProps<typeof DatasetSearchPanel>;
}

const searchResponse = {
  type: 'FeatureCollection' as const,
  numberMatched: 2,
  numberReturned: 2,
  features: [
    makeRecord({
      id: 'roads',
      title: 'Roads',
      geometryType: 'LINESTRING',
      sourceOrganization: 'City GIS',
      keywords: ['transport', 'streets'],
    }),
    makeRecord({
      id: 'population',
      title: 'Population',
      geometryType: 'POLYGON',
      sourceOrganization: 'Census',
      keywords: ['demographics'],
      featureCount: 250,
    }),
  ],
};

describe('DatasetSearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchDatasets.mockResolvedValue(searchResponse);
  });

  it('uses search-first tabs and supported API filter chips', async () => {
    render(<DatasetSearchPanel {...defaultProps()} />);

    expect(await screen.findByText('Roads')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'All' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Vector' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Raster' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Basemap' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: 'Vector' }));
    await waitFor(() => {
      expect(mockSearchDatasets).toHaveBeenLastCalledWith(expect.objectContaining({
        record_type: 'vector_dataset',
      }));
    });

    fireEvent.click(await screen.findByRole('button', { name: 'City GIS' }));
    await waitFor(() => {
      expect(mockSearchDatasets).toHaveBeenLastCalledWith(expect.objectContaining({
        record_type: 'vector_dataset',
        source_organization: 'City GIS',
      }));
    });

    fireEvent.click(await screen.findByRole('button', { name: '#transport' }));
    await waitFor(() => {
      expect(mockSearchDatasets).toHaveBeenLastCalledWith(expect.objectContaining({
        keywords: 'transport',
      }));
    });
  });

  it('routes Add to map, added, and another rendering data row states', async () => {
    const onAddDataset = vi.fn();
    const onDuplicateRendering = vi.fn();
    const layers = [makeLayer({ id: 'roads-layer', dataset_id: 'roads' })];

    render(
      <DatasetSearchPanel
        {...defaultProps({ layers, onAddDataset, onDuplicateRendering })}
      />,
    );

    expect(await screen.findByText('Roads')).toBeInTheDocument();
    const roadsRow = screen.getByText('Roads').closest('.rounded-md');
    expect(roadsRow).not.toBeNull();
    expect(within(roadsRow as HTMLElement).getByText('Added')).toBeInTheDocument();

    fireEvent.click(within(roadsRow as HTMLElement).getByRole('button', { name: 'another rendering' }));
    expect(onDuplicateRendering).toHaveBeenCalledWith('roads-layer');

    fireEvent.click(screen.getByRole('button', { name: 'Add to map Population' }));
    expect(onAddDataset).toHaveBeenCalledWith('population');
  });

  it('routes basemap swap and in-use states through map-level handlers', async () => {
    const onBasemapChange = vi.fn();
    const onBasemapLabelsChange = vi.fn();
    const onBasemapConfigChange = vi.fn();

    render(
      <DatasetSearchPanel
        {...defaultProps({
          basemapConfig: {
            label_mode: 'subtle',
            road_visibility: 'hidden',
            boundary_visibility: 'full',
            building_visibility: false,
            land_water_tone: 'muted',
            relief_contrast: 'soft',
          },
          onBasemapChange,
          onBasemapLabelsChange,
          onBasemapConfigChange,
        })}
      />,
    );

    fireEvent.click(screen.getByRole('radio', { name: 'Basemap' }));
    expect(screen.getByText('Positron')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'in use' })).toBeDisabled();
    expect(screen.queryByText('Disabled')).not.toBeInTheDocument();

    const darkRow = screen.getByText('Dark').closest('.rounded-md');
    expect(darkRow).not.toBeNull();
    fireEvent.click(within(darkRow as HTMLElement).getByRole('button', { name: 'swap' }));

    expect(onBasemapChange).toHaveBeenCalledWith('openfreemap-dark');
    expect(onBasemapLabelsChange).toHaveBeenCalledWith(true);
    expect(onBasemapConfigChange).toHaveBeenCalledWith({
      label_mode: 'subtle',
      road_visibility: 'hidden',
      boundary_visibility: 'full',
      building_visibility: false,
      land_water_tone: 'muted',
      relief_contrast: 'soft',
    });
  });

  it('expands rows inline and links to the existing import page', async () => {
    render(<DatasetSearchPanel {...defaultProps()} />);

    expect(await screen.findByText('Population')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Expand Population' }));

    expect(screen.getByText('Population description')).toBeInTheDocument();
    expect(screen.getByText('Count')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Add to map Population' }).length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'Import data...' })).toHaveAttribute('href', '/import');
  });
});
