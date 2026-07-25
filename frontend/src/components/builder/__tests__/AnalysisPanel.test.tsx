import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@/test/test-utils';
import { AnalysisPanel } from '../AnalysisPanel';
import { materializeAnalysis, previewAnalysis } from '@/api/analysis';
import { useAnalysisJobStore } from '@/stores/analysis-job-store';
import type { MapLayerResponse } from '@/types/api';

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
      );
    });
  });

  it('disables Preview when the buffer distance is invalid', () => {
    renderPanel([datasetLayer]);
    fireEvent.change(screen.getByLabelText('Distance (meters)'), {
      target: { value: '0' },
    });
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
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
        { truncated: true, totalCount: 10651 },
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
    expect(screen.getByLabelText('Distance (meters)')).toHaveValue(750);

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
    expect(screen.queryByLabelText('Distance (meters)')).toBeNull();

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
    expect(screen.getByLabelText('Distance (meters)')).toHaveValue(250);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => {
      expect(previewAnalysis).toHaveBeenCalledWith('ds1', {
        operation: 'buffer',
        distance_meters: 250,
      });
    });
  });
});
