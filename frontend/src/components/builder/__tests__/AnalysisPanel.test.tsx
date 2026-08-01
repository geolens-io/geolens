import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TerraDraw } from 'terra-draw';
import { render } from '@/test/test-utils';
import { AnalysisPanel } from '../AnalysisPanel';
import { ApiError } from '@/api/client';
import { materializeAnalysis, previewAnalysis } from '@/api/analysis';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import { useAnalysisAddedStore, useAnalysisJobStore } from '@/stores/analysis-job-store';
import { useAuthStore } from '@/stores/auth-store';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse, UserResponse } from '@/types/api';

// fix(#760): the rehydration tests need a controllable job status; the real
// hook would fire a network fetch for any non-null id. `value` applies only
// when the panel holds a jobId, mirroring the enabled-gate of the real hook.
const mockJobStatus = vi.hoisted(() => ({
  value: null as Record<string, unknown> | null,
  error: null as unknown,
}));
vi.mock('@/components/import/hooks/use-ingest', () => ({
  useJobStatus: (jobId: string | null) => ({
    data: jobId ? mockJobStatus.value : undefined,
    error: jobId ? mockJobStatus.error : null,
  }),
}));

// fix(#793 review): a controllable TerraDraw so the mask-restore error path
// can be exercised. Only tests that mount with a saved mask AND a map ref
// ever construct it; everything else never touches the mock.
const mockTerraDraw = vi.hoisted(() => ({
  instance: {
    start: vi.fn(),
    stop: vi.fn(),
    addFeatures: vi.fn(),
    setMode: vi.fn(),
    on: vi.fn(),
    getSnapshotFeature: vi.fn(),
  },
}));
vi.mock('terra-draw', () => ({
  // Constructible (`new`) — an arrow implementation throws at construction.
  TerraDraw: vi.fn(function () {
    return mockTerraDraw.instance;
  }),
  TerraDrawPolygonMode: vi.fn(function () {
    return {};
  }),
}));
vi.mock('terra-draw-maplibre-gl-adapter', () => ({
  TerraDrawMapLibreGLAdapter: vi.fn(function () {
    return {};
  }),
}));

// Radix Select needs pointer-capture APIs jsdom lacks (DataDrivenStyleEditor
// precedent).
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

// A spy rather than a bare arrow, with the SAME return contract (defaultValue
// or the key), so tests can assert which key a branch chose and what it
// interpolated. Interpolation itself stays unapplied — several assertions in
// this file match the raw `{{...}}` templates.
const mockT = vi.hoisted(() =>
  vi.fn(
    (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  ),
);
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: mockT,
    i18n: { language: 'en' },
  }),
}));

// fix(#700 review): the save half is gated on can('upload'); default to a
// role that has it so the existing save-path tests keep their controls.
let mockCanUpload = true;
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: () => mockCanUpload,
    permissions: { upload: mockCanUpload },
    isLoading: false,
  }),
}));

const mockToast = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  info: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: mockToast }));

vi.mock('@/api/analysis', () => ({
  previewAnalysis: vi.fn().mockResolvedValue({
    geojson: {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [0, 0] },
          properties: { gid: 1 },
        },
      ],
    },
    feature_count: 1,
    truncated: false,
    bbox: [0, 0, 1, 1],
  }),
  materializeAnalysis: vi
    .fn()
    .mockResolvedValue({ job_id: 'job1', status: 'pending' }),
}));

const SHARED_COLUMNS = [
  { name: 'name', type: 'text' },
  // Must be filtered out — collides with the generated output column.
  { name: 'source_count', type: 'integer' },
  // fix(#1097 review): every remaining shape the server refuses. GDAL
  // launders only case, '-' and '#', so ingested tables hold names like
  // these routinely; they are carried into analysis output but cannot be
  // NAMED in a request, because _SAFE_COLUMN_RE gates group keys and
  // transferred fields.
  { name: 'Área', type: 'text' },
  { name: '2020_pop', type: 'integer' },
  // Prefixes to the generated join_count column.
  { name: 'count', type: 'integer' },
  // No equality operator, so it cannot be a group key.
  { name: 'props', type: 'json' },
  // Transferable on its own; the SOURCE below is what makes it collide.
  { name: 'zone', type: 'text' },
];

// fix(#1097 review): keyed on the dataset id. A join field's collision is a
// relationship between the two layers, so a mock that hands both the same
// columns cannot express it — ds1 is the source and already carries a
// join_zone (routine, since it is what an earlier spatial join leaves behind),
// while ds2 is the join layer offering a plain `zone`.
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDataset: vi.fn((datasetId?: string) => ({
    data: {
      column_info:
        datasetId === 'ds1'
          ? [...SHARED_COLUMNS, { name: 'join_zone', type: 'text' }]
          : SHARED_COLUMNS,
    },
  })),
}));

const datasetLayer = {
  id: 'l1',
  dataset_id: 'ds1',
  dataset_name: 'Parcels',
  display_name: null,
  is_dem: false,
  dataset_geometry_type: 'MultiPolygon',
} as unknown as MapLayerResponse;

const groupLayer = {
  id: 'l2',
  dataset_id: null,
  dataset_name: null,
  display_name: 'Group',
  is_dem: false,
} as unknown as MapLayerResponse;

const datasetLayer2 = {
  id: 'l3',
  dataset_id: 'ds2',
  dataset_name: 'Roads',
  display_name: null,
  is_dem: false,
  // Polygonal so it stays eligible as a clip mask (ux(#698) filter).
  dataset_geometry_type: 'MultiPolygon',
} as unknown as MapLayerResponse;

// ux(#698): a non-polygon layer the server would reject as a clip mask.
const pointLayer = {
  id: 'l4',
  dataset_id: 'ds4',
  dataset_name: 'Bus stops',
  display_name: null,
  is_dem: false,
  dataset_geometry_type: 'Point',
} as unknown as MapLayerResponse;

// ux(#720): an ordinary (non-DEM) raster layer. It carries a dataset_id, so the
// old `!is_dem` filter offered it, and the server 422s on it.
const rasterLayer = {
  id: 'l5',
  dataset_id: 'ds5',
  dataset_name: 'Sentinel-2 TCI',
  display_name: null,
  is_dem: false,
  layer_type: 'raster_geolens',
  dataset_record_type: 'raster_dataset',
  dataset_geometry_type: null,
} as unknown as MapLayerResponse;

// fix(#720 review): the same raster, but reporting a geometry type. Every
// raster dataset stores NULL there today, which is what made a geometry-only
// test appear to work — but nothing enforces it, and LayerLegend already has a
// fixture where a raster reports 'POINT'.
const rasterLayerWithGeometryType = {
  ...rasterLayer,
  id: 'l6',
  dataset_id: 'ds6',
  dataset_name: 'Ortho tile with stale geometry_type',
  dataset_geometry_type: 'POINT',
} as unknown as MapLayerResponse;

// fix(#720 review): layer_type picks a RENDERER and the API validates it
// against nothing — add_layer defaults it to 'vector_geolens' whatever the
// dataset is. A classifier keyed on layer_type calls this vector.
const rasterLayerWithVectorLayerType = {
  ...rasterLayerWithGeometryType,
  id: 'l7',
  dataset_id: 'ds7',
  dataset_name: 'Raster with the default layer_type',
  layer_type: 'vector_geolens',
} as unknown as MapLayerResponse;

// The mirror case: a genuine vector dataset whose layer_type was overridden to
// the raster renderer. The analysis endpoint accepts it, so hiding it would be
// a false negative.
const vectorLayerWithRasterLayerType = {
  id: 'l8',
  dataset_id: 'ds8',
  dataset_name: 'Parcels rendered oddly',
  display_name: null,
  is_dem: false,
  layer_type: 'raster_geolens',
  dataset_record_type: 'vector_dataset',
  dataset_geometry_type: 'MultiPolygon',
} as unknown as MapLayerResponse;

function renderPanel(
  layers: MapLayerResponse[],
  props: Partial<React.ComponentProps<typeof AnalysisPanel>> = {},
) {
  const qc = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AnalysisPanel layers={layers} {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockCanUpload = true;
});

describe('AnalysisPanel', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null });
    // fix(#833): the add-to-map single-use marker is a module-level store now.
    useAnalysisAddedStore.setState({ addedDatasetIds: [], pendingAddIds: [] });
  });

  it('treats a raster-only map as having no analysable layers (#720)', () => {
    renderPanel([rasterLayer, groupLayer]);
    // Was: a fully enabled form with the raster pre-selected, whose Preview
    // 422'd into a generic "The submitted values are invalid." toast.
    expect(
      screen.getByText('Add a dataset layer to use analysis tools'),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Preview' }),
    ).not.toBeInTheDocument();
  });

  it('does not offer a raster layer alongside vector ones (#720)', () => {
    renderPanel([rasterLayer, datasetLayer]);
    // The vector layer is selected rather than the raster that comes first.
    expect(screen.getByRole('button', { name: 'Preview' })).not.toBeDisabled();
    expect(screen.getAllByText('Parcels').length).toBeGreaterThan(0);
    expect(screen.queryByText('Sentinel-2 TCI')).not.toBeInTheDocument();
  });

  it('excludes a raster that reports a geometry type (#720 review)', () => {
    renderPanel([rasterLayerWithGeometryType, groupLayer]);
    expect(
      screen.getByText('Add a dataset layer to use analysis tools'),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Preview' }),
    ).not.toBeInTheDocument();
  });

  it('excludes a raster carrying the default vector layer_type (#720 review)', () => {
    renderPanel([rasterLayerWithVectorLayerType, groupLayer]);
    expect(
      screen.getByText('Add a dataset layer to use analysis tools'),
    ).toBeInTheDocument();
  });

  it('still offers a vector dataset rendered as raster (#720 review)', () => {
    renderPanel([vectorLayerWithRasterLayerType]);
    // The analysis endpoint accepts this, so hiding it would be a false
    // negative — the failure mode of classifying by renderer instead of source.
    expect(screen.getByRole('button', { name: 'Preview' })).not.toBeDisabled();
    expect(screen.getAllByText('Parcels rendered oddly').length).toBeGreaterThan(0);
  });

  it('does not offer Dissolve to viewers (fix #779)', async () => {
    mockCanUpload = false;
    const user = userEvent.setup();
    renderPanel([datasetLayer]);
    // Dissolve is materialize-only and the materialize block is hidden
    // without upload permission — offering it was a dead end with a hint
    // naming an invisible button.
    await user.click(screen.getAllByRole('combobox')[1]);
    expect(await screen.findByRole('option', { name: 'Clip' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Dissolve' })).toBeNull();
  });

  it('hides the dataset-creation half without the upload permission (#700)', () => {
    mockCanUpload = false;
    renderPanel([datasetLayer]);
    expect(
      screen.queryByRole('button', { name: 'Create dataset' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText('New dataset name')).not.toBeInTheDocument();
    // The read-only preview stays available.
    expect(screen.getByRole('button', { name: 'Preview' })).not.toBeDisabled();
  });

  it('shows a hint when no dataset layers are available', () => {
    renderPanel([groupLayer]);
    expect(
      screen.getByText('Add a dataset layer to use analysis tools'),
    ).toBeInTheDocument();
  });

  it('auto-selects the first dataset layer and runs a buffer preview', async () => {
    const onPreviewResult = vi.fn();
    renderPanel([groupLayer, datasetLayer], { onPreviewResult });

    const runButton = screen.getByRole('button', { name: 'Preview' });
    expect(runButton).not.toBeDisabled();
    fireEvent.click(runButton);

    await waitFor(() => {
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 500,
      }, expect.any(AbortSignal));
    });
    await waitFor(() => {
      expect(onPreviewResult).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'FeatureCollection' }),
        [0, 0, 1, 1],
        { source: 'analysis-panel' },
      );
    });
  });

  it('disables Preview when the buffer distance is invalid', () => {
    renderPanel([datasetLayer]);
    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '0' },
    });
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
  });

  it('says why an out-of-range distance disabled the buttons (#723)', () => {
    renderPanel([datasetLayer]);
    const input = screen.getByLabelText('Distance');

    // Over the 100 km ceiling, in metres.
    fireEvent.change(input, { target: { value: '250000' } });
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(
      'Enter a distance greater than 0 and no more than {{max}} {{unit}}.',
    );
    // The field points at the message, so a screen reader reads it on focus
    // rather than announcing a bare "invalid".
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAttribute('aria-describedby', alert.id);
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();

    // fix(#723 review): exactly 0 is rejected by distanceValid (> 0), so the
    // message must not describe it as accepted.
    fireEvent.change(input, { target: { value: '0' } });
    expect(screen.getByRole('alert')).toHaveTextContent('greater than 0');
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();

    // Back in range: message gone, describedby dropped, buttons live again.
    fireEvent.change(input, { target: { value: '500' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(input).not.toHaveAttribute('aria-describedby');
    expect(screen.getByRole('button', { name: 'Preview' })).not.toBeDisabled();
  });

  it('shows Clear preview only when a preview is active', () => {
    const onClearPreview = vi.fn();
    renderPanel([datasetLayer], { hasPreview: true, onClearPreview });
    const clearButton = screen.getByRole('button', { name: 'Clear preview' });
    fireEvent.click(clearButton);
    expect(onClearPreview).toHaveBeenCalled();
  });

  it('clears a stale overlay when the preview returns no features (#676 parity)', async () => {
    vi.mocked(previewAnalysis).mockResolvedValueOnce({
      geojson: { type: 'FeatureCollection', features: [] },
      feature_count: 0,
      truncated: false,
      bbox: null,
    });
    const onPreviewResult = vi.fn();
    const onClearPreview = vi.fn();
    renderPanel([datasetLayer], { onPreviewResult, onClearPreview });

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(onClearPreview).toHaveBeenCalled());
    expect(onPreviewResult).not.toHaveBeenCalled();
  });

  it('passes truncation and the source total through to the overlay', async () => {
    vi.mocked(previewAnalysis).mockResolvedValueOnce({
      geojson: {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [0, 0] },
            properties: { gid: 1 },
          },
        ],
      },
      feature_count: 500,
      truncated: true,
      bbox: [0, 0, 1, 1],
      source_feature_count: 10651,
    });
    const onPreviewResult = vi.fn();
    renderPanel([datasetLayer], { onPreviewResult });

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() =>
      expect(onPreviewResult).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'FeatureCollection' }),
        [0, 0, 1, 1],
        { truncated: true, totalCount: 10651, source: 'analysis-panel' },
      ),
    );
  });

  // fix(#699): the two tests above set `truncated: true` and then assert only
  // on the overlay handoff — nothing pinned which notice the user actually
  // reads, so the count-only fallback and the "of N source features" branch
  // were interchangeable.
  it('names the source total in the truncation notice when the API reports one', async () => {
    vi.mocked(previewAnalysis).mockResolvedValueOnce({
      geojson: { type: 'FeatureCollection', features: [] },
      feature_count: 500,
      truncated: true,
      bbox: [0, 0, 1, 1],
      source_feature_count: 10651,
    });
    renderPanel([datasetLayer]);
    mockT.mockClear();
    mockToast.info.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(mockToast.info).toHaveBeenCalled());

    expect(mockToast.info).toHaveBeenCalledWith(
      'Showing the first {{count, number}} of {{total, number}} source features',
      // ux(#686): the capped preview names its own remedy, and the user here
      // has the Create dataset button to follow it to.
      {
        description: 'Use Create dataset to run the operation over every feature.',
      },
    );
    // fix(#788): both numbers go through raw so `count` still drives plural
    // selection while the locale string groups them. Passing a preformatted
    // string would render correctly in English and break plurals elsewhere.
    expect(mockT).toHaveBeenCalledWith(
      'analysisTools.truncatedNoticeTotal',
      expect.objectContaining({ count: 500, total: 10651 }),
    );
  });

  it('falls back to the count-only truncation notice when there is no source total', async () => {
    // source_feature_count is null for row-filtering operations (clip), where
    // the source total says nothing about how much output was withheld.
    vi.mocked(previewAnalysis).mockResolvedValueOnce({
      geojson: { type: 'FeatureCollection', features: [] },
      feature_count: 500,
      truncated: true,
      bbox: [0, 0, 1, 1],
      source_feature_count: null,
    });
    renderPanel([datasetLayer]);
    mockT.mockClear();
    mockToast.info.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(mockToast.info).toHaveBeenCalled());

    expect(mockToast.info).toHaveBeenCalledWith(
      'Preview capped at {{count, number}} features',
      expect.anything(),
    );
    expect(mockT).toHaveBeenCalledWith(
      'analysisTools.truncatedNotice',
      expect.objectContaining({ count: 500 }),
    );
    expect(mockT).not.toHaveBeenCalledWith(
      'analysisTools.truncatedNoticeTotal',
      expect.anything(),
    );
  });

  it('names the exact OUTPUT total for a row-filtering preview (#1097 review)', async () => {
    // select_by_location and intersect send source_feature_count: null (the
    // source count cannot describe how many rows survive) and the exact output
    // total as match_count. Before this the panel read only
    // source_feature_count, so the server paid for an uncapped count and the
    // user still got the generic cap message.
    const user = userEvent.setup();
    vi.mocked(previewAnalysis).mockResolvedValueOnce({
      geojson: { type: 'FeatureCollection', features: [] },
      feature_count: 500,
      truncated: true,
      bbox: [0, 0, 1, 1],
      source_feature_count: null,
      match_count: 2838,
    });
    renderPanel([datasetLayer, datasetLayer2]);
    // fix(#1097 review): the operation is now what selects match_count, so
    // this test has to run one. It previously proved less than it read: with
    // the panel on its default buffer, the assertion passed on the null
    // source count alone and would have passed for EVERY operation.
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Select by location' }));
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    mockT.mockClear();
    mockToast.info.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(mockToast.info).toHaveBeenCalled());

    // A distinct string, not truncatedNoticeTotal with a different number:
    // this total is output rows, and for intersect one source feature can
    // produce several, so "source features" would misdescribe it.
    expect(mockT).toHaveBeenCalledWith(
      'analysisTools.truncatedNoticeMatched',
      expect.objectContaining({ count: 500, total: 2838 }),
    );
    expect(mockT).not.toHaveBeenCalledWith(
      'analysisTools.truncatedNotice',
      expect.anything(),
    );
  });

  it('keeps the SOURCE total for spatial join, which also sends match_count (#1097 review)', async () => {
    // The guard on the fix above. spatial_join sends BOTH: it keeps every
    // source row, and its match_count counts matched PAIRS.
    // Preferring match_count wherever present would relabel 10,651 source
    // features as 30,712 "matching" ones.
    const user = userEvent.setup();
    vi.mocked(previewAnalysis).mockResolvedValueOnce({
      geojson: { type: 'FeatureCollection', features: [] },
      feature_count: 500,
      truncated: true,
      bbox: [0, 0, 1, 1],
      source_feature_count: 10651,
      match_count: 30712,
    });
    renderPanel([datasetLayer, datasetLayer2]);
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Spatial join' }));
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    mockT.mockClear();
    mockToast.info.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(mockToast.info).toHaveBeenCalled());

    expect(mockT).toHaveBeenCalledWith(
      'analysisTools.truncatedNoticeTotal',
      expect.objectContaining({ count: 500, total: 10651 }),
    );
    expect(mockT).not.toHaveBeenCalledWith(
      'analysisTools.truncatedNoticeMatched',
      expect.anything(),
    );
  });

  it('reports NO total for a spatial join whose source count is missing (#1097 review)', async () => {
    // The case that made keying off `source_feature_count == null` wrong.
    // Null has a second cause that has nothing to do with the operation: the
    // dataset's cached feature_count snapshot is absent (legacy imports,
    // register_existing_table). A spatial join on such a dataset sends null
    // AND a match_count, and that match_count counts PAIRS — 30,712 of them
    // behind a 1:1 result whose real total is the source row count. Inferring
    // from null announced and stored 30,712 as the output total, a number
    // larger than the result can possibly be.
    //
    // No total is the honest answer here: the server could not supply one.
    const user = userEvent.setup();
    vi.mocked(previewAnalysis).mockResolvedValueOnce({
      geojson: { type: 'FeatureCollection', features: [] },
      feature_count: 500,
      truncated: true,
      bbox: [0, 0, 1, 1],
      source_feature_count: null,
      match_count: 30712,
    });
    const onPreviewResult = vi.fn();
    renderPanel([datasetLayer, datasetLayer2], { onPreviewResult });
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Spatial join' }));
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    mockT.mockClear();
    mockToast.info.mockClear();
    onPreviewResult.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(mockToast.info).toHaveBeenCalled());

    // The generic cap notice, which names no total at all.
    expect(mockT).toHaveBeenCalledWith(
      'analysisTools.truncatedNotice',
      expect.objectContaining({ count: 500 }),
    );
    expect(mockT).not.toHaveBeenCalledWith(
      'analysisTools.truncatedNoticeMatched',
      expect.anything(),
    );
    expect(mockT).not.toHaveBeenCalledWith(
      'analysisTools.truncatedNoticeTotal',
      expect.anything(),
    );
    // And the pair count is not stored on the overlay either, where it would
    // outlive the toast as a badge.
    expect(onPreviewResult).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      expect.objectContaining({ truncated: true, totalCount: undefined }),
    );
  });

  it('raises no truncation notice for a complete preview', async () => {
    // fix(#699 codex P2): wait on a signal belonging to THIS request. The
    // `previewAnalysis` mock is shared and never cleared between tests, so
    // waiting for it to have been called at all resolves instantly on an
    // earlier test's call — and the negative assertion below would then run
    // before this preview's onSuccess, passing even if that branch regressed.
    // `onPreviewResult` is a fresh spy per test and fires in the same
    // synchronous success handler that raises the notice, so once it has been
    // called, a toast would already have been raised.
    const onPreviewResult = vi.fn();
    renderPanel([datasetLayer], { onPreviewResult });
    mockToast.info.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(onPreviewResult).toHaveBeenCalled());
    expect(mockToast.info).not.toHaveBeenCalled();
  });

  it('notifies the watcher of the materialize job id and title', async () => {
    const onAnalysisJobChange = vi.fn();
    renderPanel([datasetLayer], { onAnalysisJobChange });

    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Buffered parcels' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));

    await waitFor(() =>
      expect(onAnalysisJobChange).toHaveBeenCalledWith('job1', 'Buffered parcels'),
    );
  });

  it('blocks a second Create while an earlier job is still running', () => {
    // fix(#682 review): the API allows one active analysis job per user.
    // Clicking through would 429 AND orphan the running job's notification.
    useAnalysisJobStore.setState({
      job: { jobId: 'j-earlier', title: 'Earlier', mapId: 'm1' },
    });
    renderPanel([datasetLayer]);

    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Second run' },
    });
    expect(screen.getByRole('button', { name: 'Create dataset' })).toBeDisabled();
  });

  it('sends mask_dataset_id when clipping to a layer', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);

    // Combobox order: layer, operation.
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Clip' }));

    // Mask-layer select excludes the source layer itself.
    await user.click(screen.getAllByRole('combobox')[2]);
    expect(screen.queryByRole('option', { name: 'Parcels' })).toBeNull();
    await user.click(await screen.findByRole('option', { name: 'Roads' }));

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() =>
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'clip',
        mask_dataset_id: 'ds2',
      }, expect.any(AbortSignal)),
    );
  });

  it('offers only polygonal layers as a clip mask (#698)', async () => {
    // The server rejects a non-polygon mask dataset with a 422; offering one
    // here would only buy the user a failed request.
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2, pointLayer]);

    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Clip' }));

    await user.click(screen.getAllByRole('combobox')[2]);
    expect(await screen.findByRole('option', { name: 'Roads' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Bus stops' })).toBeNull();
  });

  it('clip action buttons keep their own accessible names (#754)', async () => {
    // The section label used htmlFor pointed at the state-dependent action
    // buttons, and a <label for> aimed at a button OVERRIDES the button's own
    // text — Cancel and Clear were both announced as "Draw clip area".
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);

    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Clip' }));

    const label = screen.getByText('Draw clip area', { selector: 'label' });
    expect(label).not.toHaveAttribute('for');
    // The draw button is named by its own text, not by the label element.
    const drawButton = screen.getByRole('button', { name: 'Draw clip area' });
    expect(drawButton).not.toHaveAttribute('id');
  });

  it('aborts a preview still on the wire when the panel closes (#787 item 3)', async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(previewAnalysis).mockImplementationOnce(
      ((_id: string, _body: unknown, s?: AbortSignal) => {
        signal = s;
        // Never settles, so the request is still in flight at unmount.
        return new Promise(() => {});
      }) as never,
    );
    const { unmount } = renderPanel([datasetLayer]);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(signal?.aborted).toBe(false);

    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it('closing the panel mid-preview raises no error toast (#787 item 3)', async () => {
    // The unmount abort rejects the fetch, but the rejection lands a microtask
    // later — after React has finished the commit that unsubscribed TanStack's
    // observer, which is what suppresses the option callbacks. Pinned because
    // the alternative is an "Analysis failed" toast over a panel the user
    // deliberately closed.
    vi.mocked(previewAnalysis).mockImplementationOnce(
      ((_id: string, _body: unknown, signal?: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          );
        })) as never,
    );
    mockToast.error.mockClear();
    const { unmount } = renderPanel([datasetLayer]);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());

    unmount();
    // Let the rejection and any queued callbacks run.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it('aborts a preview whose inputs changed under it (#787 item 3)', async () => {
    // The sequence guard only stops the response being drawn. Preview stays
    // disabled while the mutation is pending, so an un-aborted request also
    // blocks the replacement the user is reaching for.
    let signal: AbortSignal | undefined;
    vi.mocked(previewAnalysis).mockImplementationOnce(
      ((_id: string, _body: unknown, s?: AbortSignal) => {
        signal = s;
        return new Promise(() => {});
      }) as never,
    );
    renderPanel([datasetLayer]);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '750' },
    });
    expect(signal?.aborted).toBe(true);
  });

  it('picks up a map that arrives after mount (#787 item 10)', async () => {
    // The panel mounts before the lazy map finishes loading, and the ref it
    // is handed is filled in by assignment — which re-renders nothing. The
    // button has to follow the instance the panel holds in state.
    const user = userEvent.setup();
    const mapRef = { current: null as MaplibreMap | null };
    const qc = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    // A fresh element each time: rerendering the same reference hits React's
    // same-element bailout and skips the subtree.
    const renderTree = () => (
      <QueryClientProvider client={qc}>
        <AnalysisPanel layers={[datasetLayer]} mapInstanceRef={mapRef} />
      </QueryClientProvider>
    );
    const view = render(renderTree());
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Clip' }));
    expect(screen.getByRole('button', { name: 'Draw clip area' })).toBeDisabled();

    mapRef.current = { on: vi.fn(), off: vi.fn() } as unknown as MaplibreMap;
    view.rerender(renderTree());
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Draw clip area' }),
      ).not.toBeDisabled(),
    );
  });

  it('converts the buffer distance from the selected unit to meters (#686)', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer]);

    // ux(#773): pick the unit FIRST — changing it now converts the number to
    // preserve the physical distance, so typing after the switch is how a
    // user enters "2 miles".
    // Combobox order under buffer: layer, operation, distance unit.
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'miles' }));
    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '2' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() =>
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 2 * 1609.344,
      }, expect.any(AbortSignal)),
    );
  });

  it('converts the displayed number on a unit switch, preserving the distance (#773)', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer]);

    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '100' },
    });
    // 100 m → km converts to 0.1 instead of silently meaning 100 km.
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'kilometers' }));
    expect(screen.getByLabelText('Distance')).toHaveValue(0.1);

    // The wire value is the same physical distance as before the switch.
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() =>
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 100,
      }, expect.any(AbortSignal)),
    );

    // And back — a clean round trip, no drift.
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'meters' }));
    expect(screen.getByLabelText('Distance')).toHaveValue(100);
  });

  it('rounds converted distances instead of leaving float tails (#773)', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer]);

    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '500' },
    });
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'feet' }));
    // 500 / 0.3048 = 1640.419947506… — trimmed to 6 significant digits.
    expect(screen.getByLabelText('Distance')).toHaveValue(1640.42);
  });

  it('leaves an empty distance field alone on a unit switch (#773)', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer]);

    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '' },
    });
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'kilometers' }));
    // Nothing to convert — no NaN materializes in the field.
    expect(screen.getByLabelText('Distance')).toHaveValue(null);
  });

  it('sends by_field when a dissolve group column is chosen', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer]);

    // Combobox order: layer, operation.
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Dissolve' }));

    // The group-by select appears; source_count is filtered from the options.
    await user.click(screen.getAllByRole('combobox')[2]);
    expect(screen.queryByRole('option', { name: 'source_count' })).toBeNull();
    await user.click(await screen.findByRole('option', { name: 'name' }));

    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Dissolved by name' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));

    await waitFor(() =>
      expect(materializeAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'dissolve',
        title: 'Dissolved by name',
        by_field: 'name',
      }),
    );
  });

  it('offers no dissolve group column the server would refuse (#1097 review)', async () => {
    // The review named the JOIN picker, but the gap was in what the pickers
    // know about the server's rules, and dissolve had the same hole: it
    // filtered source_count and nothing else, so a json column (no equality
    // operator, so it cannot be a group key) and the identifier-shape
    // rejections were all offered and then refused on submit.
    const user = userEvent.setup();
    renderPanel([datasetLayer]);
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Dissolve' }));

    await user.click(screen.getAllByRole('combobox')[2]);
    expect(await screen.findByRole('option', { name: 'name' })).toBeInTheDocument();
    for (const refused of ['source_count', 'props', 'Área', '2020_pop']) {
      expect(screen.queryByRole('option', { name: refused })).toBeNull();
    }
  });

  it('resets the dissolve group field when the source layer changes (fix(#680))', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);

    // Combobox order: layer, operation.
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Dissolve' }));
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'name' }));

    // Switching datasets must not carry the field along.
    await user.click(screen.getAllByRole('combobox')[0]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));

    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Dissolved roads' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));

    await waitFor(() =>
      expect(materializeAnalysis).toHaveBeenCalledWith('ds2', {
        operation: 'dissolve',
        title: 'Dissolved roads',
      }),
    );
  });
});

describe('AnalysisPanel — chat handoff prefill (#675)', () => {
  it('initializes layer, operation, and distance from the prefill', async () => {
    renderPanel([datasetLayer, datasetLayer2], {
      prefill: { layerId: 'l3', operation: 'buffer', distanceMeters: 750 },
    });
    expect(screen.getByLabelText('Distance')).toHaveValue(750);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => {
      expect(previewAnalysis).toHaveBeenCalledWith('ds2', {
        operation: 'buffer',
        distance_meters: 750,
      }, expect.any(AbortSignal));
    });
  });

  it('prefills a centroid preview without a distance field', async () => {
    renderPanel([datasetLayer], {
      prefill: { layerId: 'l1', operation: 'centroid' },
    });
    expect(screen.queryByLabelText('Distance')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => {
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'centroid',
      }, expect.any(AbortSignal));
    });
  });

  it('falls back to the first eligible layer when the prefill layer left the map', async () => {
    renderPanel([datasetLayer], {
      prefill: { layerId: 'gone', operation: 'buffer', distanceMeters: 250 },
    });
    expect(screen.getByLabelText('Distance')).toHaveValue(250);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => {
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 250,
      }, expect.any(AbortSignal));
    });
  });

  describe('state lifecycle (fix #757/#758/#760/#764)', () => {
    beforeEach(() => {
      mockJobStatus.value = null;
      mockJobStatus.error = null;
      useAnalysisFormStore.setState({ forms: {} });
      useAnalysisJobStore.setState({ job: null });
      useAuthStore.setState({ token: null, refreshToken: null, user: null });
    });

    it('clears a stale preview when the operation changes (#758)', async () => {
      const user = userEvent.setup();
      const onClearPreview = vi.fn();
      renderPanel([datasetLayer], {
        hasPreview: true,
        previewSource: 'analysis-panel',
        onClearPreview,
      });
      await user.click(screen.getAllByRole('combobox')[1]);
      await user.click(await screen.findByRole('option', { name: 'Centroids' }));
      expect(onClearPreview).toHaveBeenCalled();
    });

    it('clears a stale preview when the source layer changes (#758)', async () => {
      const user = userEvent.setup();
      const onClearPreview = vi.fn();
      renderPanel([datasetLayer, datasetLayer2], {
        hasPreview: true,
        previewSource: 'analysis-panel',
        onClearPreview,
      });
      await user.click(screen.getAllByRole('combobox')[0]);
      await user.click(await screen.findByRole('option', { name: 'Roads' }));
      expect(onClearPreview).toHaveBeenCalled();
    });

    it('drops an in-flight preview whose inputs were superseded (#758)', async () => {
      let resolvePreview!: (v: unknown) => void;
      vi.mocked(previewAnalysis).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolvePreview = resolve;
          }) as never,
      );
      const onPreviewResult = vi.fn();
      renderPanel([datasetLayer], { onPreviewResult });

      fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
      await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
      // The inputs change while the request is on the wire.
      fireEvent.change(screen.getByLabelText('Distance'), {
        target: { value: '750' },
      });
      resolvePreview({
        geojson: {
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [0, 0] },
              properties: { gid: 1 },
            },
          ],
        },
        feature_count: 1,
        truncated: false,
        bbox: [0, 0, 1, 1],
      });
      // Let the resolved mutation settle; the superseded result must not draw.
      await new Promise((r) => setTimeout(r, 0));
      expect(onPreviewResult).not.toHaveBeenCalled();
    });

    it('resets the post-run state on an input change (#764)', async () => {
      const user = userEvent.setup();
      mockJobStatus.value = { status: 'complete', dataset_id: 'out1' };
      renderPanel([datasetLayer]);

      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'QA Lakes Buffer' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
      await waitFor(() =>
        expect(screen.getByText('Dataset created')).toBeInTheDocument(),
      );

      // Switching the operation must clear the completed-run affordances AND
      // the stale name — one more click used to create an identically-named
      // dataset from different parameters.
      await user.click(screen.getAllByRole('combobox')[1]);
      await user.click(await screen.findByRole('option', { name: 'Centroids' }));
      expect(screen.queryByText('Dataset created')).not.toBeInTheDocument();
      expect(screen.getByLabelText('New dataset name')).toHaveValue('');
    });

    it('clears the name when inputs change during an in-flight run (#793 review)', async () => {
      const user = userEvent.setup();
      let resolveMaterialize!: (v: unknown) => void;
      vi.mocked(materializeAnalysis).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveMaterialize = resolve;
          }) as never,
      );
      renderPanel([datasetLayer]);

      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'Old params name' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
      await waitFor(() => expect(materializeAnalysis).toHaveBeenCalled());

      // jobId is not set yet (the POST is still on the wire), but the run —
      // and its name — already belong to the old parameters.
      await user.click(screen.getAllByRole('combobox')[1]);
      await user.click(await screen.findByRole('option', { name: 'Centroids' }));
      expect(screen.getByLabelText('New dataset name')).toHaveValue('');

      resolveMaterialize({ job_id: 'job-superseded', status: 'pending' });
      await new Promise((r) => setTimeout(r, 0));
      // The superseded response must not resurrect the run state either.
      expect(screen.queryByText('Dataset created')).not.toBeInTheDocument();
    });

    it('renders the job status in a persistent role="status" region (#784)', async () => {
      mockJobStatus.value = { status: 'complete', dataset_id: 'out1' };
      renderPanel([datasetLayer]);

      // Mounted EMPTY with the form — a live region that mounts already
      // populated is not announced, so the first message must arrive as a
      // mutation inside an existing region.
      const region = screen.getByRole('status');
      expect(region).toBeEmptyDOMElement();

      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'Walkshed' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
      await waitFor(() => expect(region).toHaveTextContent('Dataset created'));
    });

    it('clears the typed name once the run completes (#793 review)', async () => {
      mockJobStatus.value = { status: 'complete', dataset_id: 'out1' };
      renderPanel([datasetLayer]);
      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'Walkshed' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
      await waitFor(() =>
        expect(screen.getByText('Dataset created')).toBeInTheDocument(),
      );
      // The completed-state UI stays, but the field must not hold the
      // finished run's name — the unmount snapshot would re-save it over
      // the value the watcher clears in the form store.
      expect(screen.getByLabelText('New dataset name')).toHaveValue('');
    });

    it('keeps the typed name when the run fails (#793 review)', async () => {
      mockJobStatus.value = {
        status: 'failed',
        dataset_id: null,
        error_message: 'no features',
      };
      renderPanel([datasetLayer]);
      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'Walkshed' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
      await waitFor(() =>
        // The test i18n mock returns the raw template, uninterpolated.
        expect(screen.getByText(/Analysis job failed/)).toBeInTheDocument(),
      );
      // Nothing was created — clearing would force re-typing the name to retry.
      expect(screen.getByLabelText('New dataset name')).toHaveValue('Walkshed');
    });

    it('does not toast a rejection from a superseded preview (#793 review)', async () => {
      let rejectPreview!: (e: Error) => void;
      vi.mocked(previewAnalysis).mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectPreview = reject;
          }) as never,
      );
      renderPanel([datasetLayer]);
      fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
      await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
      // Inputs change; the in-flight request now belongs to abandoned params.
      fireEvent.change(screen.getByLabelText('Distance'), {
        target: { value: '750' },
      });
      rejectPreview(new Error('boom from abandoned params'));
      await new Promise((r) => setTimeout(r, 0));
      expect(mockToast.error).not.toHaveBeenCalled();
    });

    it('rehydrates a tracked job for this map after a remount (#760)', () => {
      mockJobStatus.value = { status: 'running', current_step: null };
      useAnalysisJobStore.setState({
        job: { jobId: 'job9', title: 'Walkshed', mapId: 'm1' },
      });
      renderPanel([datasetLayer], { mapId: 'm1' });
      expect(screen.getByText('Creating dataset…')).toBeInTheDocument();
    });

    it('clears the run and its title when the tracked job is unreadable (#793 review)', async () => {
      // The remembered form holds the run's own name, and the tracked job
      // rehydrates lastRunTitle to match — the duplicate-creation setup.
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
        mask: null, maskLayerId: '__none__', byField: '__none__',
        joinLayerId: '__none__', joinField: '__none__',
        outputTitle: 'Walkshed',
      });
      useAnalysisJobStore.setState({
        job: { jobId: 'swept', title: 'Walkshed', mapId: 'm1' },
      });
      mockJobStatus.error = new ApiError('Not Found', 404);
      renderPanel([datasetLayer], { mapId: 'm1' });

      // A definitive 404 (retention sweep) must clear the local run id and
      // the field's copy of the run name, not just the store's.
      await waitFor(() =>
        expect(screen.getByLabelText('New dataset name')).toHaveValue(''),
      );
      expect(screen.queryByText('Creating dataset…')).not.toBeInTheDocument();
    });

    it('invalidates when the selected source layer is deleted (#793 review)', async () => {
      const onClearPreview = vi.fn();
      const qc = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      const view = render(
        <QueryClientProvider client={qc}>
          <AnalysisPanel
            layers={[datasetLayer, datasetLayer2]}
            mapId="m1"
            onClearPreview={onClearPreview}
            hasPreview
            previewSource="analysis-panel"
          />
        </QueryClientProvider>,
      );
      // Parcels is selected by default; delete it from the map.
      view.rerender(
        <QueryClientProvider client={qc}>
          <AnalysisPanel
            layers={[datasetLayer2]}
            mapId="m1"
            onClearPreview={onClearPreview}
            hasPreview
            previewSource="analysis-panel"
          />
        </QueryClientProvider>,
      );
      // The overlay still depicted the removed layer's preview.
      await waitFor(() => expect(onClearPreview).toHaveBeenCalled());
      // The selection falls back exactly as a fresh mount would.
      expect(screen.getAllByText('Roads').length).toBeGreaterThan(0);
    });

    it('clears a stale overlay when the remembered layer left the map (#793 review)', async () => {
      const onClearPreview = vi.fn();
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'deleted-layer', operation: 'buffer', distance: '750',
        distanceUnit: 'm', mask: null, maskLayerId: '__none__',
        byField: '__none__', joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
      });
      renderPanel([datasetLayer], {
        mapId: 'm1',
        onClearPreview,
        hasPreview: true,
        previewSource: 'analysis-panel',
      });
      // The restore is ignored wholesale (defaults shown), and the overlay
      // from the vanished layer's preview must go with it.
      await waitFor(() => expect(onClearPreview).toHaveBeenCalled());
      expect(screen.getByLabelText('Distance')).toHaveValue(500);
    });

    it("keeps a chat-drawn overlay through a stale restore (#793 review)", async () => {
      const onClearPreview = vi.fn();
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'deleted-layer', operation: 'buffer', distance: '750',
        distanceUnit: 'm', mask: null, maskLayerId: '__none__',
        byField: '__none__', joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
      });
      // The slot holds a NEWER chat result (no analysis-panel provenance) —
      // opening Analysis must not wipe it just because the remembered layer
      // is gone.
      renderPanel([datasetLayer], {
        mapId: 'm1',
        onClearPreview,
        hasPreview: true,
      });
      await waitFor(() =>
        expect(screen.getByLabelText('Distance')).toHaveValue(500),
      );
      expect(onClearPreview).not.toHaveBeenCalled();
    });

    it('keeps the store current while mounted, not only at unmount (#793 review)', () => {
      renderPanel([datasetLayer], { mapId: 'm1' });
      fireEvent.change(screen.getByLabelText('Distance'), {
        target: { value: '750' },
      });
      // The responsive breakpoint swap mounts the replacement panel in the
      // same commit that removes this one, and the replacement initializes
      // from the store during render — it can only see what is already there.
      expect(useAnalysisFormStore.getState().forms['m1']?.distance).toBe('750');
    });

    it('does not re-save the form when the user logged out before unmount (#793 review)', () => {
      useAuthStore.setState({ user: { id: 'u1' } as UserResponse, token: 't1' });
      const first = renderPanel([datasetLayer], { mapId: 'm1' });
      fireEvent.change(screen.getByLabelText('Distance'), {
        target: { value: '750' },
      });
      // Logout clears the slot; the unmount that follows must not write the
      // previous user's snapshot back for the next login to restore.
      act(() => {
        useAuthStore.getState().logout();
      });
      first.unmount();
      expect(useAnalysisFormStore.getState().forms['m1']).toBeUndefined();
    });

    it('adopts a job that lands in the store after mount (#793 review)', async () => {
      mockJobStatus.value = { status: 'running', current_step: null };
      // No tracked job at mount — the previous panel instance's POST is still
      // on the wire.
      renderPanel([datasetLayer], { mapId: 'm1' });
      expect(screen.queryByText('Creating dataset…')).not.toBeInTheDocument();

      // The old instance's mutation resolves and registers the job globally.
      act(() => {
        useAnalysisJobStore.setState({
          job: { jobId: 'late-job', title: 'Walkshed', mapId: 'm1' },
        });
      });
      // The panel adopts the run instead of reporting a foreign job.
      await waitFor(() =>
        expect(screen.getByText('Creating dataset…')).toBeInTheDocument(),
      );
      expect(
        screen.queryByText(
          'Another analysis is still running — wait for it to finish.',
        ),
      ).not.toBeInTheDocument();
    });

    it('does not adopt a late job after the form changed (#793 review)', async () => {
      mockJobStatus.value = { status: 'running', current_step: null };
      renderPanel([datasetLayer], { mapId: 'm1' });
      // The user edits before the old instance's POST resolves — the run now
      // belongs to abandoned parameters.
      fireEvent.change(screen.getByLabelText('Distance'), {
        target: { value: '750' },
      });
      act(() => {
        useAnalysisJobStore.setState({
          job: { jobId: 'late-job', title: 'Walkshed', mapId: 'm1' },
        });
      });
      // Ambient, not adopted: the reason line shows, no run status resurrects.
      expect(
        await screen.findByText(
          'Another analysis is still running — wait for it to finish.',
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText('Creating dataset…')).not.toBeInTheDocument();
    });

    it('retries mask restoration once the map instance is ready (#793 review)', async () => {
      mockTerraDraw.instance.addFeatures.mockClear();
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'l1', operation: 'clip', distance: '500', distanceUnit: 'm',
        mask: {
          type: 'Polygon',
          coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        },
        maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
      });
      // The lazy BuilderMap has not loaded yet — the ref is empty at mount.
      const mapRef = { current: null as unknown };
      const qc = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      // A fresh element each time — rerendering the SAME element reference
      // hits React's same-element bailout and skips the subtree entirely.
      const renderTree = () => (
        <QueryClientProvider client={qc}>
          <AnalysisPanel
            layers={[datasetLayer]}
            mapId="m1"
            mapInstanceRef={mapRef as never}
          />
        </QueryClientProvider>
      );
      const view = render(renderTree());
      expect(mockTerraDraw.instance.addFeatures).not.toHaveBeenCalled();

      // The map arrives by REF assignment; the load re-renders the parent.
      // on/off: the fix(#775) style.load subscription attaches while a mask
      // is set.
      mapRef.current = { on: vi.fn(), off: vi.fn() };
      view.rerender(renderTree());
      await waitFor(() =>
        expect(mockTerraDraw.instance.addFeatures).toHaveBeenCalled(),
      );
    });

    it('stops a partially started draw when mask restore fails (#793 review)', async () => {
      mockTerraDraw.instance.addFeatures.mockImplementationOnce(() => {
        throw new Error('unsupported geometry');
      });
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'l1', operation: 'clip', distance: '500', distanceUnit: 'm',
        mask: {
          type: 'Polygon',
          coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        },
        maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
      });
      renderPanel([datasetLayer], {
        mapId: 'm1',
        mapInstanceRef: { current: { on: vi.fn(), off: vi.fn() } as never },
      });
      // The failed restore must stop the instance it started — the ref was
      // never assigned, so stopping via the ref would leak its map layers.
      await waitFor(() =>
        expect(mockTerraDraw.instance.stop).toHaveBeenCalled(),
      );
    });

    it('re-adds the drawn mask overlay after a basemap style reload (#775)', async () => {
      mockTerraDraw.instance.addFeatures.mockClear();
      mockTerraDraw.instance.setMode.mockClear();
      mockTerraDraw.instance.stop.mockClear();
      const mask: GeoJSON.Polygon = {
        type: 'Polygon',
        coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
      };
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'l1', operation: 'clip', distance: '500', distanceUnit: 'm',
        mask, maskLayerId: '__none__', byField: '__none__', joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
      });
      // A map that actually tracks its style.load handlers: the fix
      // subscribes for the lifetime of the mask, and the unsubscribe half
      // (mask cleared → no resurrect) is only observable through a registry.
      const styleLoadHandlers = new Set<() => void>();
      const mockMap = {
        on: vi.fn((event: string, fn: () => void) => {
          if (event === 'style.load') styleLoadHandlers.add(fn);
        }),
        off: vi.fn((event: string, fn: () => void) => {
          if (event === 'style.load') styleLoadHandlers.delete(fn);
        }),
      };
      renderPanel([datasetLayer], {
        mapId: 'm1',
        mapInstanceRef: { current: mockMap as never },
      });
      // The #793 mount restore drew the static overlay once.
      await waitFor(() =>
        expect(mockTerraDraw.instance.addFeatures).toHaveBeenCalledTimes(1),
      );

      // A basemap switch: setStyle wiped TerraDraw's layers (the mask state
      // survives), then the new style announced itself via style.load.
      const constructionsBefore = vi.mocked(TerraDraw).mock.calls.length;
      act(() => {
        [...styleLoadHandlers].forEach((fn) => fn());
      });
      // The orphaned instance is stopped and the overlay rebuilt from mask.
      expect(mockTerraDraw.instance.stop).toHaveBeenCalled();
      expect(vi.mocked(TerraDraw).mock.calls.length).toBe(
        constructionsBefore + 1,
      );
      expect(mockTerraDraw.instance.addFeatures).toHaveBeenCalledTimes(2);
      expect(mockTerraDraw.instance.addFeatures).toHaveBeenLastCalledWith([
        expect.objectContaining({ geometry: mask }),
      ]);
      expect(mockTerraDraw.instance.setMode).toHaveBeenLastCalledWith('static');

      // Clearing the mask drops the subscription — a later style reload must
      // not resurrect the cleared overlay.
      fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
      await waitFor(() => expect(styleLoadHandlers.size).toBe(0));
      const constructionsAfterClear = vi.mocked(TerraDraw).mock.calls.length;
      act(() => {
        [...styleLoadHandlers].forEach((fn) => fn());
      });
      expect(vi.mocked(TerraDraw).mock.calls.length).toBe(
        constructionsAfterClear,
      );
    });

    it('a chat prefill stays disowned from an existing tracked run (#793 review)', () => {
      mockJobStatus.value = { status: 'complete', dataset_id: 'old-ds' };
      useAnalysisJobStore.setState({
        job: { jobId: 'old-job', title: 'Old run', mapId: 'm1' },
      });
      renderPanel([datasetLayer], {
        mapId: 'm1',
        prefill: { operation: 'buffer', layerId: 'l1', distanceMeters: 500 },
      });
      // The old run is ambient — not rehydrated into the new draft, and its
      // completion must not surface actions over (or clear) the handed-off
      // form.
      expect(screen.queryByText('Dataset created')).not.toBeInTheDocument();
      expect(
        screen.getByText(
          'Another analysis is still running — wait for it to finish.',
        ),
      ).toBeInTheDocument();
      expect(screen.getByLabelText('New dataset name')).toHaveValue(
        'Parcels — Buffer',
      );
    });

    it('keeps a name typed while the run is pending (#793 review)', async () => {
      mockJobStatus.value = { status: 'running', current_step: null };
      renderPanel([datasetLayer], { mapId: 'm1' });
      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'First run' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
      await waitFor(() =>
        expect(screen.getByText('Creating dataset…')).toBeInTheDocument(),
      );
      // The NEXT draft's name, typed while the job is still running.
      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'Second run' },
      });
      mockJobStatus.value = { status: 'complete', dataset_id: 'out1' };
      // Mimic the run registering globally; the resulting re-render lets the
      // panel observe the completed status.
      act(() => {
        useAnalysisJobStore.setState({
          job: { jobId: 'job1', title: 'First run', mapId: 'm1' },
        });
      });
      await waitFor(() =>
        expect(screen.getByText('Dataset created')).toBeInTheDocument(),
      );
      expect(screen.getByLabelText('New dataset name')).toHaveValue('Second run');
    });

    it('does not rehydrate a run the restored draft disowned (#793 review)', () => {
      mockJobStatus.value = { status: 'running', current_step: null };
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'l1', operation: 'buffer', distance: '750',
        distanceUnit: 'm', mask: null, maskLayerId: '__none__',
        byField: '__none__', joinLayerId: '__none__', joinField: '__none__', outputTitle: 'New draft', runDisowned: true,
      });
      useAnalysisJobStore.setState({
        job: { jobId: 'old-job', title: 'Old run', mapId: 'm1' },
      });
      renderPanel([datasetLayer], { mapId: 'm1' });
      // The mount-time initializer applies the same disowning the adoption
      // effect does: the abandoned run stays ambient, under the newer draft.
      expect(screen.queryByText('Creating dataset…')).not.toBeInTheDocument();
      expect(
        screen.getByText(
          'Another analysis is still running — wait for it to finish.',
        ),
      ).toBeInTheDocument();
      expect(screen.getByLabelText('New dataset name')).toHaveValue('New draft');
    });

    it('keeps a late job disowned across a remount (#793 review)', async () => {
      mockJobStatus.value = { status: 'running', current_step: null };
      // The previous instance edited mid-flight and persisted the disowning;
      // this remount restores the edited draft.
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'l1', operation: 'buffer', distance: '750',
        distanceUnit: 'm', mask: null, maskLayerId: '__none__',
        byField: '__none__', joinLayerId: '__none__', joinField: '__none__', outputTitle: 'New draft', runDisowned: true,
      });
      renderPanel([datasetLayer], { mapId: 'm1' });
      act(() => {
        useAnalysisJobStore.setState({
          job: { jobId: 'late-job', title: 'Old params', mapId: 'm1' },
        });
      });
      // Still ambient — the remount must not launder the disowning.
      expect(
        await screen.findByText(
          'Another analysis is still running — wait for it to finish.',
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText('Creating dataset…')).not.toBeInTheDocument();
      expect(screen.getByLabelText('New dataset name')).toHaveValue('New draft');
    });

    it("says why Create is disabled when the running job is another map's (#760)", () => {
      useAnalysisJobStore.setState({
        job: { jobId: 'job9', title: 'Elsewhere', mapId: 'other-map' },
      });
      renderPanel([datasetLayer], { mapId: 'm1' });
      expect(
        screen.getByText(
          'Another analysis is still running — wait for it to finish.',
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Create dataset' }),
      ).toBeDisabled();
    });

    it('remembers the form for the same map across unmounts (#757)', () => {
      const first = renderPanel([datasetLayer], { mapId: 'm1' });
      fireEvent.change(screen.getByLabelText('Distance'), {
        target: { value: '750' },
      });
      fireEvent.change(screen.getByLabelText('New dataset name'), {
        target: { value: 'Draft name' },
      });
      first.unmount();

      renderPanel([datasetLayer], { mapId: 'm1' });
      expect(screen.getByLabelText('Distance')).toHaveValue(750);
      expect(screen.getByLabelText('New dataset name')).toHaveValue('Draft name');
    });

    it('starts fresh on a different map (#757)', () => {
      const first = renderPanel([datasetLayer], { mapId: 'm1' });
      fireEvent.change(screen.getByLabelText('Distance'), {
        target: { value: '750' },
      });
      first.unmount();

      renderPanel([datasetLayer], { mapId: 'm2' });
      expect(screen.getByLabelText('Distance')).toHaveValue(500);
    });
  });
});

describe('AnalysisPanel — stack-selected layer (#772)', () => {
  beforeEach(() => {
    mockJobStatus.value = null;
    mockJobStatus.error = null;
    useAnalysisFormStore.setState({ forms: {} });
    useAnalysisJobStore.setState({ job: null });
    useAnalysisAddedStore.setState({ addedDatasetIds: [], pendingAddIds: [] });
    useAuthStore.setState({ token: null, refreshToken: null, user: null });
    vi.mocked(previewAnalysis).mockClear();
    vi.mocked(materializeAnalysis).mockClear();
  });

  it('targets the stack-selected layer instead of the first eligible one', async () => {
    renderPanel([datasetLayer, datasetLayer2], { selectedLayerId: 'l3' });
    expect(screen.getAllByText('Roads').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() =>
      expect(previewAnalysis).toHaveBeenCalledWith('ds2', {
        operation: 'buffer',
        distance_meters: 500,
      }, expect.any(AbortSignal)),
    );
  });

  it('ignores a selection that is not an analysable layer', () => {
    // The selection slot also carries raster layers, folder groups, and
    // sentinel ids like 'settings' — none of them may hijack the default.
    renderPanel([datasetLayer, rasterLayer], { selectedLayerId: 'l5' });
    expect(screen.getAllByText('Parcels').length).toBeGreaterThan(0);
  });

  it('yields to an explicit chat prefill', async () => {
    renderPanel([datasetLayer, datasetLayer2], {
      selectedLayerId: 'l3',
      prefill: { layerId: 'l1', operation: 'buffer', distanceMeters: 750 },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() =>
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 750,
      }, expect.any(AbortSignal)),
    );
  });

  it("beats the remembered form's layer while the rest of the form restores", () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '750', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Draft name',
    });
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      selectedLayerId: 'l3',
    });
    expect(screen.getAllByText('Roads').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Distance')).toHaveValue(750);
    expect(screen.getByLabelText('New dataset name')).toHaveValue('Draft name');
  });

  it("drops the displaced layer's remembered group-by (#680 parity)", async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'dissolve', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: 'col:name',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Dissolved',
    });
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      selectedLayerId: 'l3',
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
    // No by_field: the remembered column belonged to the displaced layer.
    await waitFor(() =>
      expect(materializeAnalysis).toHaveBeenCalledWith('ds2', {
        operation: 'dissolve',
        title: 'Dissolved',
      }),
    );
  });

  it('clears a remembered mask layer the selection displaces into the source slot', () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'clip', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: 'l3', byField: '__none__', joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
    });
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      selectedLayerId: 'l3',
    });
    // A mask layer can't clip itself, so the clip params are incomplete again.
    expect(screen.getAllByRole('combobox')[2]).toHaveTextContent(
      'None — draw on the map',
    );
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
  });

  it('leaves a tracked run ambient when the selection displaces its form (#793 semantics)', () => {
    mockJobStatus.value = { status: 'running', current_step: null };
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Run name',
    });
    useAnalysisJobStore.setState({
      job: { jobId: 'job9', title: 'Run name', mapId: 'm1' },
    });
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      selectedLayerId: 'l3',
    });
    // The run's blessed form is known to differ from this mount — adopting it
    // would surface (and later clear) state over a different draft.
    expect(screen.queryByText('Creating dataset…')).not.toBeInTheDocument();
    expect(
      screen.getByText(
        'Another analysis is still running — wait for it to finish.',
      ),
    ).toBeInTheDocument();
  });

  it('still rehydrates the run when the selection matches the remembered layer', () => {
    mockJobStatus.value = { status: 'running', current_step: null };
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Run name',
    });
    useAnalysisJobStore.setState({
      job: { jobId: 'job9', title: 'Run name', mapId: 'm1' },
    });
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      selectedLayerId: 'l1',
    });
    expect(screen.getByText('Creating dataset…')).toBeInTheDocument();
  });

  it('marks the clear-preview and add-to-map controls with explicit button types', () => {
    // The panel is a <form> now — an unmarked <button> inside it submits.
    renderPanel([datasetLayer], { hasPreview: true });
    expect(
      screen.getByRole('button', { name: 'Clear preview' }),
    ).toHaveAttribute('type', 'button');
    expect(
      screen.getByRole('button', { name: 'Create dataset' }),
    ).toHaveAttribute('type', 'button');
  });

  it('clears a panel-owned overlay when the selection displaces the remembered layer', async () => {
    const onClearPreview = vi.fn();
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '750', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__', joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
    });
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      selectedLayerId: 'l3',
      onClearPreview,
      hasPreview: true,
      previewSource: 'analysis-panel',
    });
    // The overlay depicts the displaced layer's preview — stale for the same
    // reason a vanished layer's would be.
    await waitFor(() => expect(onClearPreview).toHaveBeenCalled());
  });
});

describe('AnalysisPanel — audit remediation (v1.6.0)', () => {
  beforeEach(() => {
    mockJobStatus.value = null;
    mockJobStatus.error = null;
    useAnalysisFormStore.setState({ forms: {} });
    useAnalysisJobStore.setState({ job: null });
    useAnalysisAddedStore.setState({ addedDatasetIds: [], pendingAddIds: [] });
    useAuthStore.setState({ token: null, refreshToken: null, user: null });
    vi.mocked(previewAnalysis).mockClear();
    vi.mocked(materializeAnalysis).mockClear();
    mockToast.error.mockClear();
    mockTerraDraw.instance.stop.mockClear();
    mockTerraDraw.instance.addFeatures.mockClear();
  });

  it("does not warn 'another analysis' during its own run's tracking gaps", async () => {
    // onAnalysisJobChange fires inside the mutationFn, setJobId only in
    // onSuccess, and the first poll lands later still — during both gaps the
    // tracked job is OURS, so the foreign-job banner must stay silent.
    let resolveMaterialize!: (v: unknown) => void;
    vi.mocked(materializeAnalysis).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveMaterialize = resolve;
        }) as never,
    );
    renderPanel([datasetLayer], { mapId: 'm1' });
    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Own run' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
    await waitFor(() => expect(materializeAnalysis).toHaveBeenCalled());

    // The page registers the job globally while the POST is still pending.
    act(() => {
      useAnalysisJobStore.setState({
        job: { jobId: 'own-job', title: 'Own run', mapId: 'm1' },
      });
    });
    expect(
      screen.queryByText(
        'Another analysis is still running — wait for it to finish.',
      ),
    ).not.toBeInTheDocument();

    resolveMaterialize({ job_id: 'own-job', status: 'pending' });
    await new Promise((r) => setTimeout(r, 0));
    // onSuccess → first poll: jobId set, no status observed yet.
    expect(
      screen.queryByText(
        'Another analysis is still running — wait for it to finish.',
      ),
    ).not.toBeInTheDocument();
  });

  it('Escape during a clip draw cancels the draw, not the panel', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer], {
      mapInstanceRef: { current: { on: vi.fn(), off: vi.fn() } as never },
    });
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Clip' }));
    await user.click(screen.getByRole('button', { name: 'Draw clip area' }));

    // The Draw→Cancel swap moves focus onto Cancel — without this the
    // keystroke below lands on <body> and never reaches the panel.
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    expect(cancel).toHaveFocus();

    // fireEvent returns false when preventDefault fired — the consumed
    // Escape is what keeps BuilderRail's handler from closing the panel.
    const notPrevented = fireEvent.keyDown(cancel, { key: 'Escape' });
    expect(notPrevented).toBe(false);
    expect(mockTerraDraw.instance.stop).toHaveBeenCalled();

    // Back to the idle state, focus returned to the Draw button.
    const draw = await screen.findByRole('button', { name: 'Draw clip area' });
    expect(draw).toHaveFocus();
  });

  it('Escape without a pending draw is left for the rail to handle', () => {
    renderPanel([datasetLayer]);
    const notPrevented = fireEvent.keyDown(screen.getByLabelText('Distance'), {
      key: 'Escape',
    });
    // Not consumed: closing the panel on Escape is BuilderRail's job.
    expect(notPrevented).toBe(true);
  });

  it('keeps the cap attainable across a unit switch (100 000 m → feet)', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer]);
    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '100000' },
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'feet' }));
    // Was 328 084 ft (6-significant-digit round UP = 100 000.0032 m), which
    // the panel then flagged invalid against its own stated maximum. The
    // conversion now rounds DOWN to the cap in the target unit.
    expect(screen.getByLabelText('Distance')).toHaveValue(328083.98);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview' })).not.toBeDisabled();
  });

  it('caps the distance input at an attainable stated maximum', () => {
    renderPanel([datasetLayer]);
    // The max attribute matches the floored, attainable cap the range
    // message states — 100 000 m is exact in metres.
    expect(screen.getByLabelText('Distance')).toHaveAttribute('max', '100000');
  });

  it('submits Preview on Enter via the form (D10)', async () => {
    renderPanel([datasetLayer]);
    fireEvent.submit(screen.getByTestId('analysis-panel'));
    await waitFor(() =>
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 500,
      }, expect.any(AbortSignal)),
    );
  });

  it('ignores a form submit while the inputs are invalid (D10)', () => {
    renderPanel([datasetLayer]);
    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '0' },
    });
    fireEvent.submit(screen.getByTestId('analysis-panel'));
    expect(previewAnalysis).not.toHaveBeenCalled();
  });

  it('explains the disabled Create button via a static hint (D6)', () => {
    renderPanel([datasetLayer]);
    const createButton = screen.getByRole('button', { name: 'Create dataset' });
    expect(createButton).toBeDisabled();
    expect(createButton).toHaveAttribute(
      'aria-describedby',
      'analysis-save-hint',
    );
    const hint = document.getElementById('analysis-save-hint');
    expect(hint).toHaveTextContent(
      'Enter a name for the new dataset to enable Create dataset.',
    );
    // Deliberately OUTSIDE the polite status region — a live region would
    // narrate the hint on every keystroke.
    expect(screen.getByRole('status')).not.toContainElement(hint);

    // With the name typed, the reason (and describedby) go away.
    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Named' },
    });
    expect(createButton).not.toBeDisabled();
    expect(createButton).not.toHaveAttribute('aria-describedby');
  });

  it('points the hint at the invalid parameters once a name exists (D6)', () => {
    renderPanel([datasetLayer]);
    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Named' },
    });
    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '0' },
    });
    expect(document.getElementById('analysis-save-hint')).toHaveTextContent(
      'Complete the operation settings above to enable Create dataset.',
    );
  });

  it('marks the panel Add to map used after one click', async () => {
    mockJobStatus.value = { status: 'complete', dataset_id: 'out1' };
    const onAddDataset = vi.fn();
    renderPanel([datasetLayer], {
      mapId: 'm1',
      layerActions: { onAddDataset } as never,
    });
    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Out' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));

    // The test i18n mock returns the raw template, uninterpolated.
    const addButton = await screen.findByRole('button', {
      name: 'Add "{{name}}" to map',
    });
    fireEvent.click(addButton);
    expect(onAddDataset).toHaveBeenCalledTimes(1);

    // Completion also raises the watcher's toast action — the click claims a
    // PENDING guard entry (confirmed only when the add mutation succeeds), so
    // the pair can't add the layer twice while the request is in flight.
    const usedButton = screen.getByRole('button', { name: 'Add "{{name}}" to map' });
    expect(usedButton).toBeDisabled();
    fireEvent.click(usedButton);
    expect(onAddDataset).toHaveBeenCalledTimes(1);
  });

  // fix(#833): the single-use marker is shared with the watcher's toast
  // action — each affordance used to dedupe only against itself, so clicking
  // the toast action and then this button added the layer twice.
  it('disables the panel Add to map when the toast action already added', async () => {
    mockJobStatus.value = { status: 'complete', dataset_id: 'out1' };
    const onAddDataset = vi.fn();
    // The watcher's toast action performed the add.
    useAnalysisAddedStore.getState().confirmAdded('out1');
    renderPanel([datasetLayer], {
      mapId: 'm1',
      layerActions: { onAddDataset } as never,
    });
    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Out' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));

    const usedButton = await screen.findByRole('button', { name: 'Added to map' });
    expect(usedButton).toBeDisabled();
    fireEvent.click(usedButton);
    expect(onAddDataset).not.toHaveBeenCalled();
  });

  // fix(#833 codex P2): the guard is claimed (pending) before the add
  // mutation starts, so a failed add must clear the pending claim
  // (handleAddDataset's onError) or the affordances stay retired with no
  // retry path. A confirmed entry is NOT cleared by failures — a failed
  // catalog/chat/drag re-add of the same dataset can't un-retire the guard.
  it('re-arms the panel Add to map when a failed add clears the pending claim', async () => {
    mockJobStatus.value = { status: 'complete', dataset_id: 'out1' };
    const onAddDataset = vi.fn();
    useAnalysisAddedStore.getState().markPending('out1');
    renderPanel([datasetLayer], {
      mapId: 'm1',
      layerActions: { onAddDataset } as never,
    });
    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Out' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
    expect(
      await screen.findByRole('button', { name: 'Add "{{name}}" to map' }),
    ).toBeDisabled();

    // The add mutation failed — its onError clears the pending claim.
    act(() => {
      useAnalysisAddedStore.getState().clearPending('out1');
    });

    const retryButton = await screen.findByRole('button', {
      name: 'Add "{{name}}" to map',
    });
    expect(retryButton).toBeEnabled();
    fireEvent.click(retryButton);
    expect(onAddDataset).toHaveBeenCalledTimes(1);
  });

  // fix(#833 codex round 6): clearPending only touches the pending claim — a
  // failed NON-analysis add of the same dataset (which never claims one) must
  // not un-retire a confirmed analysis add.
  it('keeps a confirmed add retired when an unrelated add of the same dataset fails', () => {
    const guard = useAnalysisAddedStore.getState();
    guard.markPending('out1');
    guard.confirmAdded('out1');
    // handleAddDataset's onError for a failed catalog/chat/drag add.
    useAnalysisAddedStore.getState().clearPending('out1');
    expect(useAnalysisAddedStore.getState().addedDatasetIds).toContain('out1');
    expect(useAnalysisAddedStore.getState().pendingAddIds).not.toContain('out1');
  });

  it('sets aria-busy on the pending Preview button', async () => {
    let resolvePreview!: (v: unknown) => void;
    vi.mocked(previewAnalysis).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePreview = resolve;
        }) as never,
    );
    renderPanel([datasetLayer]);
    const previewButton = screen.getByRole('button', { name: 'Preview' });
    expect(previewButton).not.toHaveAttribute('aria-busy');
    fireEvent.click(previewButton);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Running…' })).toHaveAttribute(
        'aria-busy',
        'true',
      ),
    );
    resolvePreview({
      geojson: { type: 'FeatureCollection', features: [] },
      feature_count: 0,
      truncated: false,
      bbox: null,
    });
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Preview' }),
      ).not.toHaveAttribute('aria-busy'),
    );
  });

  it('sets aria-busy on the pending Create dataset button', async () => {
    vi.mocked(materializeAnalysis).mockImplementationOnce(
      () => new Promise(() => {}) as never,
    );
    renderPanel([datasetLayer]);
    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Busy' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Creating…' }),
      ).toHaveAttribute('aria-busy', 'true'),
    );
  });

  it('retries a failed mask restore on a later commit', async () => {
    // The latch used to be set BEFORE the attempt, so one failure left the
    // mask applied but never visible, with no retry — mirrors
    // use-ephemeral-layers' retry-until-attached idiom now.
    mockTerraDraw.instance.addFeatures.mockImplementationOnce(() => {
      throw new Error('unsupported geometry');
    });
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'clip', distance: '500', distanceUnit: 'm',
      mask: {
        type: 'Polygon',
        coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
      },
      maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
    });
    const qc = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const mapRef = { current: { on: vi.fn(), off: vi.fn() } };
    // A fresh element each time — rerendering the SAME element reference
    // hits React's same-element bailout and skips the subtree entirely.
    const renderTree = () => (
      <QueryClientProvider client={qc}>
        <AnalysisPanel
          layers={[datasetLayer]}
          mapId="m1"
          mapInstanceRef={mapRef as never}
        />
      </QueryClientProvider>
    );
    const view = render(renderTree());
    // First attempt failed and tore itself down.
    await waitFor(() =>
      expect(mockTerraDraw.instance.addFeatures).toHaveBeenCalledTimes(1),
    );
    expect(mockTerraDraw.instance.stop).toHaveBeenCalled();

    // The next commit retries and succeeds.
    view.rerender(renderTree());
    await waitFor(() =>
      expect(mockTerraDraw.instance.addFeatures).toHaveBeenCalledTimes(2),
    );
    expect(mockTerraDraw.instance.setMode).toHaveBeenLastCalledWith('static');
  });
});

describe('AnalysisPanel spatial join (feat(#953))', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null });
    useAnalysisAddedStore.setState({ addedDatasetIds: [], pendingAddIds: [] });
    useAnalysisFormStore.setState({ forms: {} });
    vi.clearAllMocks();
  });

  async function pickSpatialJoin(user: ReturnType<typeof userEvent.setup>) {
    // Combobox order: layer, operation.
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Spatial join' }));
  }

  /** The (datasetId, body) of the first preview call.
   *
   * Deliberately the first TWO arguments rather than toHaveBeenCalledWith:
   * #787 item 3 adds a third AbortSignal argument on a separate branch, and
   * these tests are about the request body, which is the same either way.
   */
  function previewRequest() {
    return vi.mocked(previewAnalysis).mock.calls[0].slice(0, 2);
  }

  it('offers every other layer as a join target, not only polygons', async () => {
    const user = userEvent.setup();
    // pointLayer is excluded from the CLIP mask picker by the ux(#698) filter;
    // a join counts in any direction, so it must be offered here.
    renderPanel([datasetLayer, datasetLayer2, pointLayer]);
    await pickSpatialJoin(user);

    await user.click(screen.getAllByRole('combobox')[2]);
    expect(await screen.findByRole('option', { name: 'Bus stops' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Roads' })).toBeInTheDocument();
    // The source layer cannot join against itself.
    expect(screen.queryByRole('option', { name: 'Parcels' })).toBeNull();
  });

  it('offers no join field the server would refuse (#1097 review)', async () => {
    // The picker used to list every column of the join layer. Three classes of
    // them can never run: `count` prefixes onto the generated join_count
    // column, and `Área`/`2020_pop` fail _SAFE_COLUMN_RE. Offering them meant
    // the only way to learn a field was unusable was to submit and read a 422.
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickSpatialJoin(user);
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));

    await user.click(screen.getAllByRole('combobox')[3]);
    // The one usable column is still offered — this filters, it does not empty.
    expect(await screen.findByRole('option', { name: 'name' })).toBeInTheDocument();
    for (const refused of ['count', 'Área', '2020_pop']) {
      expect(screen.queryByRole('option', { name: refused })).toBeNull();
    }
    // fix(#1097 review): and the one that depends on the OTHER layer. `zone`
    // is transferable in itself; it is refused because the source already has
    // a join_zone, so the transfer would arrive twice. A picker that reads
    // only the join layer cannot see this.
    expect(screen.queryByRole('option', { name: 'zone' })).toBeNull();
  });

  it('does not keep a join field the new source makes invalid (#1097 review)', async () => {
    // The field belongs to the JOIN layer, so a source change leaves it
    // intact — but whether it is USABLE depends on the source, since
    // join_<name> must not collide with a source column. ds1 has join_zone and
    // the others do not, so picking `zone` against a ds2 source and then
    // switching the source to ds1 left the menu filtering `zone` out while the
    // state still held it. The request went anyway and earned a 422.
    //
    // The join layer is a THIRD layer on purpose: switching the source onto
    // the join layer also clears it (nothing joins against itself), which
    // would mask whether the FIELD was cleared on its own.
    const user = userEvent.setup();
    renderPanel([datasetLayer2, pointLayer, datasetLayer]);
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Spatial join' }));
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Bus stops' }));
    await user.click(screen.getAllByRole('combobox')[3]);
    await user.click(await screen.findByRole('option', { name: 'zone' }));

    // Switch the SOURCE to the layer that already carries join_zone.
    await user.click(screen.getAllByRole('combobox')[0]);
    await user.click(await screen.findByRole('option', { name: 'Parcels' }));

    vi.mocked(previewAnalysis).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    const body = vi.mocked(previewAnalysis).mock.calls[0][1] as {
      join_fields?: string[];
    };
    expect(body.join_fields ?? []).not.toContain('zone');
  });

  it('cannot preview until a join layer is picked', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickSpatialJoin(user);

    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();

    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled(),
    );
  });

  it('sends join_dataset_id alone when no field is transferred', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickSpatialJoin(user);

    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual([
      'ds1',
      { operation: 'spatial_join', join_dataset_id: 'ds2' },
    ]);
  });

  it('sends join_fields when a column is chosen', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickSpatialJoin(user);

    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    // Third combobox is the field picker, populated from the JOIN layer.
    await user.click(screen.getAllByRole('combobox')[3]);
    await user.click(await screen.findByRole('option', { name: 'name' }));

    fireEvent.change(screen.getByLabelText('New dataset name'), {
      target: { value: 'Parcels with road names' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create dataset' }));

    await waitFor(() =>
      expect(materializeAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'spatial_join',
        title: 'Parcels with road names',
        join_dataset_id: 'ds2',
        join_fields: ['name'],
      }),
    );
  });

  it('drops the chosen field when the join layer changes', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2, pointLayer]);
    await pickSpatialJoin(user);

    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    await user.click(screen.getAllByRole('combobox')[3]);
    await user.click(await screen.findByRole('option', { name: 'name' }));

    // Switching layers must not carry a column that belonged to the old one.
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Bus stops' }));

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual([
      'ds1',
      { operation: 'spatial_join', join_dataset_id: 'ds4' },
    ]);
  });

  it('restores the join layer and field after a remount (#1097 review)', async () => {
    const user = userEvent.setup();
    // mapId is what keys the remembered form — without it the panel persists
    // nothing and this test would pass against any implementation.
    const layerSet = [datasetLayer, datasetLayer2, pointLayer];
    const { unmount } = renderPanel(layerSet, { mapId: 'm1' });
    await pickSpatialJoin(user);
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    await user.click(screen.getAllByRole('combobox')[3]);
    await user.click(await screen.findByRole('option', { name: 'name' }));

    // Closing the rail (or crossing the responsive breakpoint) unmounts the
    // panel. Before this both inputs came back as their sentinels, so the
    // restored spatial-join form was unrunnable with its required layer
    // silently cleared — while the mask layer next to it survived.
    unmount();
    renderPanel(layerSet, { mapId: 'm1' });

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual([
      'ds1',
      {
        operation: 'spatial_join',
        join_dataset_id: 'ds2',
        join_fields: ['name'],
      },
    ]);
  });
});

describe('AnalysisPanel select by location (feat(#955))', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null });
    useAnalysisAddedStore.setState({ addedDatasetIds: [], pendingAddIds: [] });
    useAnalysisFormStore.setState({ forms: {} });
    vi.clearAllMocks();
  });

  async function pickOperation(
    user: ReturnType<typeof userEvent.setup>,
    name: string,
  ) {
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name }));
  }

  function previewRequest() {
    return vi.mocked(previewAnalysis).mock.calls[0].slice(0, 2);
  }

  it('names the selection, not the clip, in the shared mask controls', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickOperation(user, 'Select by location');

    // The controls are clip's; the wording must not be.
    expect(screen.getByRole('button', { name: 'Draw selection area' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Draw clip area' })).toBeNull();
    expect(screen.getByLabelText('Or select against a layer')).toBeInTheDocument();
  });

  it('offers only polygon layers to select against', async () => {
    const user = userEvent.setup();
    // The selection geometry has to be an area, so this keeps clip's ux(#698)
    // filter rather than spatial_join's any-direction rule.
    renderPanel([datasetLayer, datasetLayer2, pointLayer]);
    await pickOperation(user, 'Select by location');

    await user.click(screen.getByLabelText('Or select against a layer'));
    expect(await screen.findByRole('option', { name: 'Roads' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Bus stops' })).toBeNull();
  });

  it('cannot preview until an area is drawn or a layer is picked', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickOperation(user, 'Select by location');

    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();

    await user.click(screen.getByLabelText('Or select against a layer'));
    await user.click(await screen.findByRole('option', { name: 'Roads' }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled(),
    );
  });

  it('sends mask_dataset_id on the same two fields clip uses', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickOperation(user, 'Select by location');

    await user.click(screen.getByLabelText('Or select against a layer'));
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual([
      'ds1',
      { operation: 'select_by_location', mask_dataset_id: 'ds2' },
    ]);
  });

  // The DRAWN mask, not the layer picker: only the drawn one is cleared by the
  // operation switch, so it is the only one these two tests can tell apart.
  const drawnMask = {
    type: 'Polygon' as const,
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
  };
  function seedDrawnClipMask() {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'clip', distance: '500', distanceUnit: 'm',
      mask: drawnMask,
      maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
    });
  }

  it('keeps a drawn area when switching between clip and select', async () => {
    const user = userEvent.setup();
    seedDrawnClipMask();
    // mapId is what keys the saved form; without it there is nothing to restore.
    renderPanel([datasetLayer, datasetLayer2], { mapId: 'm1' });

    // Both operations take the same geometry, so switching must not make the
    // user redraw the polygon they already have.
    await pickOperation(user, 'Select by location');
    expect(screen.getByText('Selection area set')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual([
      'ds1',
      { operation: 'select_by_location', mask: drawnMask },
    ]);
  });

  it('still tears the drawn area off the map when leaving for centroid', async () => {
    const user = userEvent.setup();
    mockTerraDraw.instance.stop.mockClear();
    seedDrawnClipMask();
    // A map ref is required for BOTH halves: it is what makes the restore
    // construct a TerraDraw instance, and therefore what makes the teardown
    // observable at all.
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      mapInstanceRef: { current: { on: vi.fn(), off: vi.fn() } as never },
    });
    await waitFor(() =>
      expect(mockTerraDraw.instance.addFeatures).toHaveBeenCalled(),
    );

    // fix(#680)'s rule survives the widening: the retained polygon's TerraDraw
    // layers must come off the map when the next operation ignores them.
    // Asserted through stop() rather than through the request body — the body
    // omits `mask` for centroid anyway, so it cannot tell the two apart.
    await pickOperation(user, 'Centroids');
    await waitFor(() => expect(mockTerraDraw.instance.stop).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual(['ds1', { operation: 'centroid' }]);
  });
});

describe('AnalysisPanel intersect (feat(#956))', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null });
    useAnalysisAddedStore.setState({ addedDatasetIds: [], pendingAddIds: [] });
    useAnalysisFormStore.setState({ forms: {} });
    vi.clearAllMocks();
  });

  async function pickIntersect(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Intersect' }));
  }

  function previewRequest() {
    return vi.mocked(previewAnalysis).mock.calls[0].slice(0, 2);
  }

  it('offers a layer picker and no way to draw', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickIntersect(user);

    // A drawn polygon carries no attributes to overlay with, so the API takes
    // a layer only and the panel must not offer the alternative.
    expect(screen.getByLabelText('Overlay with layer')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Draw clip area' })).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Draw selection area' }),
    ).toBeNull();
  });

  it('cannot preview until a layer is picked', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickIntersect(user);

    // No drawn fallback exists, so the empty picker is genuinely blocking.
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();

    await user.click(screen.getByLabelText('Overlay with layer'));
    await user.click(await screen.findByRole('option', { name: 'Roads' }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled(),
    );
  });

  it('sends mask_dataset_id and never a drawn mask', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2]);
    await pickIntersect(user);

    await user.click(screen.getByLabelText('Overlay with layer'));
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual([
      'ds1',
      { operation: 'intersect', mask_dataset_id: 'ds2' },
    ]);
  });

  it('tears a drawn area carried over from clip off the map', async () => {
    const user = userEvent.setup();
    mockTerraDraw.instance.stop.mockClear();
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'clip', distance: '500', distanceUnit: 'm',
      mask: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
      maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__', outputTitle: '',
    });
    renderPanel([datasetLayer, datasetLayer2], {
      mapId: 'm1',
      mapInstanceRef: { current: { on: vi.fn(), off: vi.fn() } as never },
    });
    await waitFor(() =>
      expect(mockTerraDraw.instance.addFeatures).toHaveBeenCalled(),
    );

    // Unlike clip -> select_by_location, this switch has to clear the polygon:
    // intersect ignores a drawn mask, so a retained one would sit on the map
    // depicting nothing. The request body cannot prove it (usesMask already
    // excludes intersect), so assert the teardown itself.
    await pickIntersect(user);
    await waitFor(() => expect(mockTerraDraw.instance.stop).toHaveBeenCalled());

    await user.click(screen.getByLabelText('Overlay with layer'));
    await user.click(await screen.findByRole('option', { name: 'Roads' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(previewAnalysis).toHaveBeenCalled());
    expect(previewRequest()).toEqual([
      'ds1',
      { operation: 'intersect', mask_dataset_id: 'ds2' },
    ]);
  });

  it('offers only polygon layers to overlay with', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer, datasetLayer2, pointLayer]);
    await pickIntersect(user);

    // _load_mask_dataset requires a polygonal layer, so filter here rather
    // than let the pick earn a 422.
    await user.click(screen.getByLabelText('Overlay with layer'));
    expect(await screen.findByRole('option', { name: 'Roads' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Bus stops' })).toBeNull();
  });
});
