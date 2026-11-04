import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { SharedLayerResponse } from '@/types/api';
import { AccessibleMapDataPanel } from '../AccessibleMapDataPanel';
import type { AccessibleMapFeatureResult } from '../accessible-map-data';

const mockUseDatasetRows = vi.fn((..._args: unknown[]): { data?: unknown; isError?: boolean; error?: unknown; isPlaceholderData?: boolean } => ({
  data: undefined,
}));
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: (...args: unknown[]) => mockUseDatasetRows(...args),
}));

const LAYER = {
  id: 'layer-1',
  dataset_id: 'dataset-1',
  dataset_name: 'Roads',
  display_name: 'Public roads',
  geometry_type: 'POINT',
  layer_type: 'vector_geolens',
} as SharedLayerResponse;

function result(fetchRow: boolean): AccessibleMapFeatureResult {
  return {
    total: 1,
    truncated: false,
    features: [{
      key: 'feature-1',
      layerName: 'Public roads',
      title: 'City Hall',
      clusterCount: null,
      geometryType: 'Point',
      bounds: [-76.6, 39.3, -76.6, 39.3],
      properties: [['street_name', 'Fayette Street']],
      ungroupedKeys: new Set(),
      datasetId: 'dataset-1',
      gid: 7,
      fetchRow,
    }],
  };
}

function panel(fetchRow: boolean, embedToken?: string) {
  return (
    <AccessibleMapDataPanel
      layers={[LAYER]}
      visibleLayers={new Set(['layer-1'])}
      featureResult={result(fetchRow)}
      onRefresh={vi.fn()}
      embedToken={embedToken}
    />
  );
}

const open = () => {
  const summary = screen.getByText('All fields');
  const details = summary.closest('details')!;
  details.open = true;
  fireEvent(details, new Event('toggle'));
};

describe('AccessibleMapDataPanel rows', () => {
  beforeEach(() => {
    mockUseDatasetRows.mockReset();
    mockUseDatasetRows.mockReturnValue({ data: undefined });
  });

  it('offers no extra fields when the item needs no fetch', () => {
    render(panel(false));
    expect(screen.queryByText('All fields')).not.toBeInTheDocument();
  });

  it('drops the no-attributes sentence above the disclosure when the tile carries no columns', () => {
    const empty = result(true);
    empty.features[0].properties = [];
    const { rerender } = render(
      <AccessibleMapDataPanel layers={[LAYER]} visibleLayers={new Set(['layer-1'])} featureResult={empty} onRefresh={vi.fn()} />,
    );
    expect(screen.getByText('All fields')).toBeInTheDocument();
    expect(screen.queryByText(/No public attributes/)).not.toBeInTheDocument();

    empty.features[0].fetchRow = false;
    rerender(
      <AccessibleMapDataPanel layers={[LAYER]} visibleLayers={new Set(['layer-1'])} featureResult={{ ...empty }} onRefresh={vi.fn()} />,
    );
    expect(screen.getByText(/No public attributes/)).toBeInTheDocument();
  });

  it('reads nothing until the item is opened', () => {
    render(panel(true));
    expect(mockUseDatasetRows).toHaveBeenCalledWith(
      '', 1, 0, undefined, undefined, undefined, 7, { embedToken: undefined },
    );
  });

  it('fetches the row by gid when opened and lists its fields', () => {
    const { rerender } = render(panel(true, 'et-1'));
    open();
    expect(mockUseDatasetRows).toHaveBeenLastCalledWith(
      'dataset-1', 1, 0, undefined, undefined, undefined, 7, { embedToken: 'et-1' },
    );
    expect(screen.getByText('Loading more fields…')).toBeInTheDocument();

    mockUseDatasetRows.mockReturnValue({ data: { rows: [{ gid: 7, mayor: 'Adams' }] } });
    rerender(panel(true, 'et-1'));
    expect(screen.getByText('Mayor')).toBeInTheDocument();
    expect(screen.getByText('Adams')).toBeInTheDocument();
    expect(screen.queryByText('Gid')).not.toBeInTheDocument();
  });

  it('hides the control once the server refuses the read', () => {
    mockUseDatasetRows.mockReturnValue({ data: undefined, isError: true, error: new ApiError('no', 403) });
    render(panel(true));
    open();
    expect(screen.queryByText('All fields')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows an error line when the fetch fails', () => {
    mockUseDatasetRows.mockReturnValue({ data: undefined, isError: true });
    render(panel(true));
    open();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the other fields');
  });
});
