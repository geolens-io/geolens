import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@/test/test-utils';
import { AnalysisPanel } from '../AnalysisPanel';
import { ApiError } from '@/api/client';
import { materializeAnalysis, previewAnalysis } from '@/api/analysis';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import { useAnalysisJobStore } from '@/stores/analysis-job-store';
import { useAuthStore } from '@/stores/auth-store';
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

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? _key,
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

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDataset: vi.fn(() => ({
    data: {
      column_info: [
        { name: 'name', type: 'text' },
        // Must be filtered out — collides with the generated output column.
        { name: 'source_count', type: 'integer' },
      ],
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
  beforeEach(() => useAnalysisJobStore.setState({ job: null }));

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
    expect(screen.getByText('Parcels')).toBeInTheDocument();
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
    expect(screen.getByText('Parcels rendered oddly')).toBeInTheDocument();
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
      });
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
      }),
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

  it('converts the buffer distance from the selected unit to meters (#686)', async () => {
    const user = userEvent.setup();
    renderPanel([datasetLayer]);

    fireEvent.change(screen.getByLabelText('Distance'), {
      target: { value: '2' },
    });
    // Combobox order under buffer: layer, operation, distance unit.
    await user.click(screen.getAllByRole('combobox')[2]);
    await user.click(await screen.findByRole('option', { name: 'miles' }));

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() =>
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 2 * 1609.344,
      }),
    );
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
      });
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
      });
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
      });
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
      expect(screen.getByText('Roads')).toBeInTheDocument();
    });

    it('clears a stale overlay when the remembered layer left the map (#793 review)', async () => {
      const onClearPreview = vi.fn();
      useAnalysisFormStore.getState().save('m1', {
        layerId: 'deleted-layer', operation: 'buffer', distance: '750',
        distanceUnit: 'm', mask: null, maskLayerId: '__none__',
        byField: '__none__', outputTitle: '',
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
        byField: '__none__', outputTitle: '',
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
        maskLayerId: '__none__', byField: '__none__', outputTitle: '',
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
      mapRef.current = {};
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
        maskLayerId: '__none__', byField: '__none__', outputTitle: '',
      });
      renderPanel([datasetLayer], {
        mapId: 'm1',
        mapInstanceRef: { current: {} as never },
      });
      // The failed restore must stop the instance it started — the ref was
      // never assigned, so stopping via the ref would leak its map layers.
      await waitFor(() =>
        expect(mockTerraDraw.instance.stop).toHaveBeenCalled(),
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
        byField: '__none__', outputTitle: 'New draft', runDisowned: true,
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
        byField: '__none__', outputTitle: 'New draft', runDisowned: true,
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
