import { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { SharedLayerResponse } from '@/types/api';
import { AccessibleMapDataPanel } from '../AccessibleMapDataPanel';
import type { AccessibleMapFeatureResult } from '../accessible-map-data';

const LAYER: SharedLayerResponse = {
  id: 'layer-1',
  dataset_id: 'dataset-1',
  dataset_name: 'Roads',
  display_name: 'Public roads',
  table_name: 'roads',
  geometry_type: 'POINT',
  column_info: null,
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: {},
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
  feature_count: 12,
};

const RESULT: AccessibleMapFeatureResult = {
  total: 1,
  truncated: false,
  features: [{
    key: 'feature-1',
    layerName: 'Public roads',
    title: 'City Hall',
    clusterCount: null,
    geometryType: 'Point',
    bounds: [-76.6122, 39.2904, -76.6122, 39.2904],
    properties: [['street_name', 'Fayette Street'], ['lanes', 2]],
  }],
};

function Harness({ onRefresh = vi.fn() }: { onRefresh?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <AccessibleMapDataPanel
      layers={[LAYER]}
      visibleLayers={new Set(['layer-1'])}
      featureResult={RESULT}
      open={open}
      onOpenChange={setOpen}
      onRefresh={onRefresh}
    />
  );
}

describe('AccessibleMapDataPanel', () => {
  it('offers a keyboard-operable structured alternative to the map canvas', () => {
    render(<Harness />);

    fireEvent.click(screen.getByRole('button', { name: 'Map data' }));

    const dialog = screen.getByRole('dialog', { name: 'Map data' });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByRole('heading', { name: 'Layers', level: 3 })).toBeInTheDocument();
    expect(within(dialog).getAllByText('Public roads')).toHaveLength(2);
    expect(within(dialog).getByText('Visible')).toBeInTheDocument();
    expect(within(dialog).getByRole('heading', { name: 'City Hall', level: 4 })).toBeInTheDocument();
    expect(within(dialog).getByText('Street Name')).toBeInTheDocument();
    expect(within(dialog).getByText('Fayette Street')).toBeInTheDocument();
    expect(within(dialog).getByRole('region', { name: 'Map layer and feature data' })).toHaveAttribute('tabindex', '0');
  });

  it('refreshes the viewport-derived feature list on demand', () => {
    const onRefresh = vi.fn();
    render(<Harness onRefresh={onRefresh} />);

    fireEvent.click(screen.getByRole('button', { name: 'Map data' }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh view' }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('keeps the layer inventory useful when no vector features are queryable', () => {
    render(
      <AccessibleMapDataPanel
        layers={[LAYER]}
        visibleLayers={new Set()}
        featureResult={{ features: [], total: 0, truncated: false }}
        open
        onOpenChange={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('Hidden')).toBeInTheDocument();
    expect(screen.getByText(/No queryable vector features/)).toBeInTheDocument();
  });

  it('identifies cluster rows and exposes their aggregate count', () => {
    render(
      <AccessibleMapDataPanel
        layers={[LAYER]}
        visibleLayers={new Set(['layer-1'])}
        featureResult={{
          features: [{
            ...RESULT.features[0],
            key: 'cluster-1',
            title: null,
            clusterCount: 42,
          }],
          total: 1,
          truncated: false,
        }}
        open
        onOpenChange={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Feature cluster 1', level: 4 })).toBeInTheDocument();
    expect(screen.getByText('Cluster containing 42 features')).toBeInTheDocument();
  });
});
