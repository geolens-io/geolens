import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import { DatasetSearchPanel } from '../DatasetSearchPanel';
import { searchDatasets } from '@/api/search';
import type { BasemapEntry } from '@/api/settings';
import type { MapLayerResponse, OGCRecordResponse, RecordType } from '@/types/api';

vi.mock('@/api/search', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/search')>();
  return { ...actual, searchDatasets: vi.fn() };
});

// ---------------------------------------------------------------------------
// useQuery override state — used by Phase 1042-02 polish tests to simulate
// isLoading / isFetching states without relying on real promise timing.
// When null, the mock delegates to the real @tanstack/react-query useQuery.
// ---------------------------------------------------------------------------
let useQueryOverride: Record<string, unknown> | null = null;

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>();
  return {
    ...actual,
    useQuery: vi.fn((options: Parameters<typeof actual.useQuery>[0]) => {
      if (useQueryOverride !== null) {
        return useQueryOverride;
      }
      return actual.useQuery(options);
    }),
  };
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

  // =========================================================================
  // BSR-17 / BSR-18: initialQuery, raster filter removal, three-state UX
  // =========================================================================

  it('Test 1: initialQuery pre-fills search input and fires query with q=foo', async () => {
    render(<DatasetSearchPanel {...defaultProps({ initialQuery: 'foo' })} />);

    // Input should be pre-filled with 'foo'
    const input = screen.getByRole('textbox', { name: /search datasets/i });
    expect((input as HTMLInputElement).value).toBe('foo');

    // A search call should have been made with q=foo
    await waitFor(() => {
      expect(mockSearchDatasets).toHaveBeenCalledWith(expect.objectContaining({ q: 'foo' }));
    });
  });

  it('Test 2: initialQuery non-empty causes input to be auto-selected on mount', async () => {
    const selectSpy = vi.spyOn(HTMLInputElement.prototype, 'select');
    render(<DatasetSearchPanel {...defaultProps({ initialQuery: 'hello' })} />);

    // select() should be called because initialQuery is non-empty
    await waitFor(() => {
      expect(selectSpy).toHaveBeenCalled();
    });
    selectSpy.mockRestore();
  });

  it('Test 3: Raster tab fires backend query with record_type=raster_dataset and client filter is gone', async () => {
    // Backend returns a mix — the old client filter would hide the vector record
    const mixedResponse = {
      type: 'FeatureCollection' as const,
      numberMatched: 2,
      numberReturned: 2,
      features: [
        makeRecord({ id: 'sat-image', title: 'Satellite Image', recordType: 'raster_dataset' }),
        makeRecord({ id: 'roads2', title: 'Roads 2', recordType: 'vector_dataset' }),
      ],
    };
    mockSearchDatasets.mockResolvedValue(mixedResponse);

    render(<DatasetSearchPanel {...defaultProps()} />);

    fireEvent.click(screen.getByRole('radio', { name: 'Raster' }));

    await waitFor(() => {
      expect(mockSearchDatasets).toHaveBeenCalledWith(expect.objectContaining({
        record_type: 'raster_dataset',
      }));
    });

    // Both records are rendered — client-side filter is gone
    expect(await screen.findByText('Satellite Image')).toBeInTheDocument();
    expect(screen.getByText('Roads 2')).toBeInTheDocument();
  });

  it('Test 4: Unfiltered-empty state — catalog empty, no query — shows Inbox CTA with Upload link', async () => {
    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection' as const,
      numberMatched: 0,
      numberReturned: 0,
      features: [],
    });

    render(<DatasetSearchPanel {...defaultProps()} />);

    const statusEl = await screen.findByRole('status');
    expect(statusEl).toBeInTheDocument();
    expect(statusEl.textContent).toMatch(/Your catalog is empty/);

    // Upload CTA link
    const uploadLink = screen.getByRole('link', { name: /upload a file/i });
    expect(uploadLink).toHaveAttribute('href', '/import');
  });

  it('Test 5: Zero-result state — query entered, no matches — shows SearchX and Clear search button', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection' as const,
      numberMatched: 0,
      numberReturned: 0,
      features: [],
    });

    render(<DatasetSearchPanel {...defaultProps()} />);

    const input = screen.getByRole('textbox', { name: /search datasets/i });
    fireEvent.change(input, { target: { value: 'foo' } });

    // Advance past the 300ms debounce
    vi.advanceTimersByTime(400);
    vi.useRealTimers();

    const statusEl = await screen.findByRole('status');
    // i18n mock returns defaultValue without interpolation, so assert patterns separately
    expect(statusEl.textContent).toMatch(/No datasets match/);

    // Clear search button resets the query
    const clearBtn = screen.getByRole('button', { name: /clear search/i });
    fireEvent.click(clearBtn);
    expect((input as HTMLInputElement).value).toBe('');
  });

  it('Test 6: Error state — renders alert with connection error copy', async () => {
    mockSearchDatasets.mockRejectedValue(new Error('Network error'));

    render(<DatasetSearchPanel {...defaultProps()} />);

    const alertEl = await screen.findByRole('alert');
    expect(alertEl.textContent).toMatch(/Failed to load datasets/);
  });
});

// ---------------------------------------------------------------------------
// DatasetSearchPanel — Phase 1042-02 polish fixes (POL-15, AUD-10/12/13/15)
// ---------------------------------------------------------------------------

describe('DatasetSearchPanel — Phase 1042-02 polish fixes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useQueryOverride = null;
  });

  afterEach(() => {
    useQueryOverride = null;
  });

  it('Test 1 (AUD-10): isLoading=true shows 5 skeleton placeholders with h-[58px]', () => {
    useQueryOverride = {
      data: undefined,
      isLoading: true,
      isFetching: true,
      isError: false,
    };

    const { container } = render(<DatasetSearchPanel {...defaultProps()} />);

    // Skeletons rendered via Skeleton component which uses data-slot="skeleton"
    const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
    expect(skeletons.length).toBe(5);
    // Each skeleton should have h-[58px] class
    skeletons.forEach((skeleton) => {
      expect(skeleton.className).toContain('h-[58px]');
    });
    // No spinner present (Loader2 spin class)
    expect(container.querySelector('.animate-spin')).toBeNull();
  });

  it('Test 2 (AUD-13): isFetching=true && isLoading=false shows thin progress band above dimmed list', () => {
    useQueryOverride = {
      data: searchResponse,
      isLoading: false,
      isFetching: true,
      isError: false,
    };

    const { container } = render(<DatasetSearchPanel {...defaultProps()} />);

    // Progress band — h-0.5 element with animate-pulse
    const progressBand = container.querySelector('.h-0\\.5.animate-pulse');
    expect(progressBand).not.toBeNull();
    // The results list should be present but dimmed (pointer-events-none opacity-50)
    const dimmedList = container.querySelector('.pointer-events-none.opacity-50');
    expect(dimmedList).not.toBeNull();
    // No skeleton rows during refetch
    const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
    expect(skeletons.length).toBe(0);
  });

  it('Test 3 (AUD-15): disclosure caret is a single ChevronRight; rotates 90deg when expanded, does not swap icons', async () => {
    useQueryOverride = {
      data: searchResponse,
      isLoading: false,
      isFetching: false,
      isError: false,
    };

    render(<DatasetSearchPanel {...defaultProps()} />);

    // Expand the first row — button "Expand Roads"
    const expandBtn = screen.getByRole('button', { name: /Expand Roads/i });
    // Before expanding: caret button exists, uses transition-transform
    const caretIcon = expandBtn.querySelector('svg');
    expect(caretIcon).not.toBeNull();
    expect(caretIcon!.className.baseVal ?? caretIcon!.getAttribute('class') ?? '').toContain('transition-transform');
    // The rotate-90 class should NOT be present initially
    expect(caretIcon!.className.baseVal ?? caretIcon!.getAttribute('class') ?? '').not.toContain('rotate-90');

    // Click to expand
    fireEvent.click(expandBtn);

    // After expanding: same SVG node now has rotate-90 (not a different icon swapped in)
    await waitFor(() => {
      const expandedCaret = expandBtn.querySelector('svg');
      expect(expandedCaret).not.toBeNull();
      const cls = expandedCaret!.className.baseVal ?? expandedCaret!.getAttribute('class') ?? '';
      expect(cls).toContain('rotate-90');
    });
  });

  it('Test 4 (cursor-grab): DraggableDatasetRow outer div has cursor-grab when not dragging', () => {
    useQueryOverride = {
      data: searchResponse,
      isLoading: false,
      isFetching: false,
      isError: false,
    };

    const { container } = render(<DatasetSearchPanel {...defaultProps()} />);

    // The result list items are DraggableDatasetRow outer divs
    // They have class group/row rounded-md border... and cursor-grab when not dragging
    const rowOuterDivs = container.querySelectorAll('.group\\/row');
    expect(rowOuterDivs.length).toBeGreaterThan(0);
    // At least one row should have cursor-grab
    const withGrab = Array.from(rowOuterDivs).filter((div) =>
      div.className.includes('cursor-grab'),
    );
    expect(withGrab.length).toBeGreaterThan(0);
  });
});
