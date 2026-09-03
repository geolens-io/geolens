import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import type { OGCRecordResponse } from '@/types/api';
import { VrtCreatorForm } from '../VrtCreatorForm';

const mockMutateAsync = vi.fn();
vi.mock('@/components/import/hooks/use-ingest', () => ({
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

// fix(#1778): rebuilt to the shape service_records.py actually serializes
// (proj:code / proj:shape / raster:bands / gsd), not the flat
// epsg/dtype/nodata/width/height/res_x/res_y fields the API never returned.
// fix(#1805 review round 2): `nodata` now distinguishes three real JSON
// shapes -- omitted entirely (default '-9999' when unset, or forced via
// `omitNodataKey` to simulate the remote-COG shape where band stats never
// carry a nodata key), explicitly `null` (a band that HAS nodata metadata
// and says there is none), and a defined string value.
function makeCogSource(
  overrides: Partial<{
    id: string;
    title: string;
    epsg: number;
    band_count: number;
    dtype: string;
    nodata: string | null;
    /** Omit the raster:bands[0].nodata key entirely, simulating a remote
     * COG whose band-level stats (cog_info.py) carry only min/max/mean --
     * the backend's RasterAsset.nodata can still be defined even though
     * this source's band metadata says nothing about it. */
    omitNodataKey: boolean;
    width: number;
    height: number;
    gsd: number;
    crs: string | null;
  }>,
): OGCRecordResponse {
  const nodataValue = overrides.nodata !== undefined ? overrides.nodata : '-9999';
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
      crs: overrides.crs === null ? null : (overrides.crs ?? `EPSG:${overrides.epsg ?? 4326}`),
      geometry_type: null,
      feature_count: null,
      contacts: null,
      license: null,
      source_organization: null,
      record_type: 'raster_dataset',
      'proj:code': `EPSG:${overrides.epsg ?? 4326}`,
      'proj:shape': [overrides.height ?? 1000, overrides.width ?? 1000],
      band_count: overrides.band_count ?? 1,
      'raster:bands': [
        {
          data_type: overrides.dtype ?? 'float32',
          ...(overrides.omitNodataKey ? {} : { nodata: nodataValue }),
        },
      ],
      gsd: overrides.gsd ?? 0.001,
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
  // The production VrtCreatorForm queues a 150ms onBlur timer that closes the
  // results dropdown (`setIsDropdownOpen(false)`) and a 300ms search debounce.
  // After clearing, poll for both observable side-effects so the next
  // user.click → onFocus opens a clean dropdown rather than racing a stale
  // close-timer.
  await waitFor(
    () => {
      // Input value must reflect the clear synchronously
      expect(searchInput).toHaveValue('');
      // Prior result item must be gone from the dropdown card. The selected
      // chip uses the same title, so check the dropdown's button (which is
      // distinguishable from the chip by its enclosing list).
      expect(screen.queryByRole('button', { name: new RegExp(title) })).not.toBeInTheDocument();
    },
    { timeout: 1_000 },
  );
  await user.click(searchInput);
  await user.type(searchInput, 'cog');
  await waitFor(
    () => {
      expect(screen.getByText(title)).toBeInTheDocument();
    },
    { timeout: 5000 },
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

  it('spatial mosaic form submits vrt_type=mosaic with correct payload', { timeout: 15000 }, async () => {
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

  it('incompatible CRS sources disable submit button', { timeout: 15000 }, async () => {
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

  // fix(#1805 review round 1): _check_crs picks the reference CRS as the
  // first source in the list with a KNOWN crs, not unconditionally the
  // first selected source. With the first-selected source having no CRS,
  // the previous code (comparing everything to sources[0]) silently
  // skipped this check entirely even though the other two sources
  // disagree with each other.
  it('detects a CRS mismatch between later sources when the first-selected source has no CRS', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-crs-none', title: 'CRS Source None', crs: null });
    const source2 = makeCogSource({ id: 'ds-crs-x', title: 'CRS Source X', epsg: 4326 });
    const source3 = makeCogSource({ id: 'ds-crs-y', title: 'CRS Source Y', epsg: 32617 });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 3,
      numberReturned: 3,
      features: [source1, source2, source3],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'CRS Source None');
    await selectSource(user, searchInput, 'CRS Source X');
    await selectSource(user, searchInput, 'CRS Source Y');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'First Source No CRS VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).toBeDisabled();
  });

  // fix(#1778): these three checks read epsg/dtype/nodata/width/height/
  // res_x/res_y off OGCRecordProperties, none of which the API ever
  // returned, so the operands were always undefined and every branch below
  // was dead code -- the fixture agreed with the (wrong) hand-typed mirror
  // and both disagreed with the server. Now sourced from raster:bands,
  // proj:shape, and gsd, the shape the API actually serializes.
  it('mismatched dtype across mosaic sources disables submit (#1778)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-dtype-a', title: 'Dtype Source A', dtype: 'uint8' });
    const source2 = makeCogSource({ id: 'ds-dtype-b', title: 'Dtype Source B', dtype: 'float32' });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'Dtype Source A');
    await selectSource(user, searchInput, 'Dtype Source B');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Mismatched Dtype VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).toBeDisabled();
  });

  // fix(#1805 review round 2 P1): round 1 fixed the VALUE-vs-PRESENCE bug
  // but still inferred presence from a single `!= null` read, conflating
  // "unknown" (no band metadata for nodata at all -- the remote-COG shape,
  // since cog_info.py's band stats carry only min/max/mean) with "absent"
  // (a band that explicitly has no nodata). Pinned per the review: a
  // remote-COG-shaped source (no nodata key on its bands) paired with a
  // locally-probed source that defines one is NOT flagged -- the client
  // cannot tell, so it defers to the backend's authoritative check.
  it('remote-COG-shaped nodata (unknown) paired with a defined value is not flagged (#1805 P1 round 2)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-nodata-a', title: 'Nodata Source A', nodata: '-9999' });
    const source2 = makeCogSource({ id: 'ds-nodata-b', title: 'Nodata Source B', omitNodataKey: true });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'Nodata Source A');
    await selectSource(user, searchInput, 'Nodata Source B');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Unknown Nodata Not Flagged VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).not.toBeDisabled();
  });

  // Pinned per the review: two sources that both carry nodata metadata but
  // disagree on PRESENCE (one explicitly null, one a defined value) is the
  // real inconsistency and must still be flagged.
  it('explicit nodata:null vs a defined value is flagged (#1805 P1 round 2)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-nodata-e', title: 'Nodata Source E', nodata: null });
    const source2 = makeCogSource({ id: 'ds-nodata-f', title: 'Nodata Source F', nodata: '0' });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'Nodata Source E');
    await selectSource(user, searchInput, 'Nodata Source F');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Explicit Null Vs Defined VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).toBeDisabled();
  });

  // Pinned per the review: two sources both with unknown nodata metadata
  // (remote-COG shape on both sides) is not flagged.
  it('two unknown-nodata sources are not flagged (#1805 P1 round 2)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-nodata-g', title: 'Nodata Source G', omitNodataKey: true });
    const source2 = makeCogSource({ id: 'ds-nodata-h', title: 'Nodata Source H', omitNodataKey: true });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'Nodata Source G');
    await selectSource(user, searchInput, 'Nodata Source H');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Two Unknowns VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).not.toBeDisabled();
  });

  it('different nodata VALUES across mosaic sources remain valid when both define one (#1805 P1)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-nodata-c', title: 'Nodata Source C', nodata: '-9999' });
    const source2 = makeCogSource({ id: 'ds-nodata-d', title: 'Nodata Source D', nodata: '0' });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'Nodata Source C');
    await selectSource(user, searchInput, 'Nodata Source D');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Different Nodata Values VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).not.toBeDisabled();
  });

  it('misaligned grid across band-stack sources disables submit (#1778)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-grid-a', title: 'Grid Source A', width: 1000, height: 1000, gsd: 0.001 });
    const source2 = makeCogSource({ id: 'ds-grid-b', title: 'Grid Source B', width: 2000, height: 2000, gsd: 0.002 });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    // Switch to band-stack mode, where the grid-alignment check applies.
    await user.click(screen.getByRole('radio', { name: 'vrt.modeBandStack' }));

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'Grid Source A');
    await selectSource(user, searchInput, 'Grid Source B');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Misaligned Grid VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).toBeDisabled();
  });

  // fix(#1805 review round 1 P2): the backend compares res_x/res_y (which
  // gsd derives from) with a 1e-10 absolute tolerance, not strict equality.
  // Pinned per the review: 0.30000000000000004 vs 0.3 is aligned;
  // 0.3 vs 0.31 is misaligned.
  it('grid alignment tolerates floating-point noise in gsd (#1805 P2)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-gsd-a', title: 'GSD Source A', gsd: 0.30000000000000004 });
    const source2 = makeCogSource({ id: 'ds-gsd-b', title: 'GSD Source B', gsd: 0.3 });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    await user.click(screen.getByRole('radio', { name: 'vrt.modeBandStack' }));

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'GSD Source A');
    await selectSource(user, searchInput, 'GSD Source B');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Floating Point Noise VRT');

    const submitButton = screen.getByRole('button', { name: 'vrt.submit' });
    expect(submitButton).not.toBeDisabled();
  });

  it('grid misalignment beyond tolerance still disables submit (#1805 P2)', { timeout: 15000 }, async () => {
    const user = userEvent.setup({ delay: null });
    const source1 = makeCogSource({ id: 'ds-gsd-c', title: 'GSD Source C', gsd: 0.3 });
    const source2 = makeCogSource({ id: 'ds-gsd-d', title: 'GSD Source D', gsd: 0.31 });

    mockSearchDatasets.mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [source1, source2],
    });

    render(<VrtCreatorForm />);

    await user.click(screen.getByRole('radio', { name: 'vrt.modeBandStack' }));

    const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');
    await selectSource(user, searchInput, 'GSD Source C');
    await selectSource(user, searchInput, 'GSD Source D');

    const titleInput = screen.getByPlaceholderText('vrt.titlePlaceholder');
    await user.type(titleInput, 'Beyond Tolerance VRT');

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

  it('submit button disabled when title is empty', { timeout: 15000 }, async () => {
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

  it('clears the search blur timer on unmount so it cannot fire into a torn-down tree', () => {
    // fix(#1758): the 150 ms blur delay used to outlive the component. Nothing
    // cleared it, so unmounting inside its window left it queued, and on the CI
    // runner it fired after jsdom teardown and threw `window is not defined`
    // out of react-dom's scheduler. That failed the whole vitest run while
    // every test in it passed, which is the shape of failure hardest to
    // attribute to the file that caused it.
    vi.useFakeTimers();
    try {
      const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
      const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout');
      const { unmount } = render(<VrtCreatorForm />);
      const searchInput = screen.getByPlaceholderText('vrt.searchPlaceholder');

      // The blur delay is the only 150 ms timer this component schedules.
      const blurTimerIds = () =>
        setTimeoutSpy.mock.calls
          .map(
            (call, index) => [call[1], setTimeoutSpy.mock.results[index]?.value] as const,
          )
          .filter(([delay]) => delay === 150)
          .map(([, id]) => id);

      fireEvent.focusOut(searchInput);
      expect(blurTimerIds()).toHaveLength(1);

      // A second blur replaces the pending timer rather than queuing a second.
      fireEvent.focusOut(searchInput);
      const [first, second] = blurTimerIds();
      expect(second).not.toBe(first);
      expect(clearTimeoutSpy).toHaveBeenCalledWith(first);

      unmount();

      // The survivor is cleared on the way out, so the callback never runs.
      expect(clearTimeoutSpy).toHaveBeenCalledWith(second);
      expect(() => vi.advanceTimersByTime(1000)).not.toThrow();
    } finally {
      vi.restoreAllMocks();
      vi.useRealTimers();
    }
  });
});
