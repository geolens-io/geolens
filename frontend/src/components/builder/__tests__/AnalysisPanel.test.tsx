import { fireEvent, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@/test/test-utils';
import { AnalysisPanel } from '../AnalysisPanel';
import { previewAnalysis } from '@/api/analysis';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? _key,
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

describe('AnalysisPanel', () => {
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
});
