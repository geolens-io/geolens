import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import type { OGCRecordResponse } from '@/types/api';
import { VrtCreatorForm } from '../VrtCreatorForm';

const mockMutateAsync = vi.fn();
vi.mock('@/hooks/use-ingest', () => ({
  useCreateVrt: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
  useJobStatus: () => ({
    data: null,
    isLoading: true,
  }),
  useRetryJob: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock('@/api/search', () => ({
  searchDatasets: vi.fn(),
}));

const mockApiFetch = vi.fn();
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, apiFetch: (...args: unknown[]) => mockApiFetch(...args) };
});

// Mock react-i18next to return keys (standard approach)
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts) return `${key}:${JSON.stringify(opts)}`;
      return key;
    },
  }),
}));

function makeCogSource(
  overrides: Partial<{
    id: string;
    title: string;
    epsg: number;
    band_count: number;
    dtype: string;
    nodata: string;
    width: number;
    height: number;
    res_x: number;
    res_y: number;
  }>,
): OGCRecordResponse {
  return {
    type: 'Feature',
    id: overrides.id ?? 'ds-1',
    geometry: null,
    properties: {
      type: 'Feature',
      title: overrides.title ?? 'Test COG',
      description: null,
      keywords: null,
      created: null,
      updated: null,
      updated_by_display: null,
      never_edited: true,
      crs: `EPSG:${overrides.epsg ?? 4326}`,
      geometry_type: null,
      feature_count: null,
      contact: null,
      license: null,
      source_organization: null,
      record_type: 'raster_dataset',
      epsg: overrides.epsg ?? 4326,
      band_count: overrides.band_count ?? 1,
      dtype: overrides.dtype ?? 'float32',
      nodata: overrides.nodata ?? '-9999',
      width: overrides.width ?? 1000,
      height: overrides.height ?? 1000,
      res_x: overrides.res_x ?? 0.001,
      res_y: overrides.res_y ?? 0.001,
    },
    links: [],
  };
}

import { searchDatasets } from '@/api/search';

const mockSearchDatasets = vi.mocked(searchDatasets);

/**
 * Helper: search for and click a result in the dropdown.
 * Requires the mock to be set up to return the result before calling.
 */
async function selectSource(
  user: ReturnType<typeof userEvent.setup>,
  searchInput: HTMLElement,
  title: string,
) {
  await user.clear(searchInput);
  await user.type(searchInput, 'cog');
  await waitFor(
    () => {
      expect(screen.getByText(title)).toBeInTheDocument();
    },
    { timeout: 2000 },
  );
  await user.click(screen.getByText(title));
}

describe('VrtCreatorForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: return empty results
    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 0,
      numberReturned: 0,
      features: [],
    });
  });

  it('renders mode selector with Spatial Mosaic selected by default', () => {
    render(<VrtCreatorForm />);

    // Mode toggle is rendered
    expect(screen.getByText('vrt.modeMosaic')).toBeInTheDocument();
    expect(screen.getByText('vrt.modeBandStack')).toBeInTheDocument();

    // Resolution strategy dropdown is visible (mosaic is default)
    expect(screen.getByText('vrt.resolutionStrategy')).toBeInTheDocument();
  });

  it('spatial mosaic form submits vrt_type=mosaic with correct payload', async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-1', title: 'Alpha COG', epsg: 4326 });
    const source2 = makeCogSource({ id: 'ds-2', title: 'Beta COG', epsg: 4326 });

    // After source1 is selected it's filtered out; source2 remains
    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    mockMutateAsync.mockResolvedValue({ job_id: 'job-123', status: 'pending', message: 'ok' });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');

    // Select source 1 (both appear in dropdown, we click source1)
    await selectSource(user, searchInput, 'Alpha COG');

    // Select source 2 (source1 is now filtered out; source2 is still in the mock response)
    await selectSource(user, searchInput, 'Beta COG');

    // Fill in title
    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Test Mosaic');

    // Submit
    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          vrt_type: 'mosaic',
          resolution_strategy: 'finest',
          source_dataset_ids: expect.any(Array),
          title: 'Test Mosaic',
        }),
      );
    });
  });

  it('band stack mode hides resolution dropdown and shows bandStackHelp', async () => {
    const user = userEvent.setup();
    render(<VrtCreatorForm />);

    // Resolution is visible in mosaic mode
    expect(screen.getByText('vrt.resolutionStrategy')).toBeInTheDocument();

    // Switch to Band Stack
    const bandStackToggle = screen.getByText('vrt.modeBandStack');
    await user.click(bandStackToggle);

    // Resolution strategy is now hidden
    expect(screen.queryByText('vrt.resolutionStrategy')).not.toBeInTheDocument();

    // Band stack note is shown
    expect(screen.getByText('vrt.bandStackHelp')).toBeInTheDocument();
  });

  it('incompatible CRS sources disable submit button', async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-crs-a', title: 'CRS Source A', epsg: 4326 });
    const source2 = makeCogSource({ id: 'ds-crs-b', title: 'CRS Source B', epsg: 32617 });

    // Return both sources; component filters out already-selected ones
    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');

    // Select source 1
    await selectSource(user, searchInput, 'CRS Source A');

    // Select source 2 (different CRS)
    await selectSource(user, searchInput, 'CRS Source B');

    // Fill in title
    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Mismatched CRS VRT');

    // Submit button should be disabled due to CRS mismatch
    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).toBeDisabled();
  });

  it('submit button disabled when fewer than 2 sources selected', () => {
    render(<VrtCreatorForm />);

    // No sources selected
    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).toBeDisabled();
  });

  it('pre-selects raster source when initialSourceId is provided', async () => {
    const rasterSource = makeCogSource({ id: 'ds-init', title: 'Pre-selected COG' });
    mockApiFetch.mockResolvedValue(rasterSource);

    render(<VrtCreatorForm initialSourceId="ds-init" />);

    await waitFor(() => {
      expect(screen.getByText('Pre-selected COG')).toBeInTheDocument();
    });
  });

  it('does not pre-select non-raster source from initialSourceId', async () => {
    const vectorSource = makeCogSource({ id: 'ds-vec', title: 'Vector Dataset' });
    vectorSource.properties.record_type = 'feature' as never;
    mockApiFetch.mockResolvedValue(vectorSource);

    render(<VrtCreatorForm initialSourceId="ds-vec" />);

    // Wait for the query to resolve, then verify it was NOT added
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalled();
    });
    expect(screen.queryByText('Vector Dataset')).not.toBeInTheDocument();
  });

  it('submit button disabled when title is empty', async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-t-1', title: 'Title Test Source 1', epsg: 4326 });
    const source2 = makeCogSource({ id: 'ds-t-2', title: 'Title Test Source 2', epsg: 4326 });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');

    // Select both sources
    await selectSource(user, searchInput, 'Title Test Source 1');
    await selectSource(user, searchInput, 'Title Test Source 2');

    // Title is empty — submit should be disabled
    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).toBeDisabled();
  });
});
