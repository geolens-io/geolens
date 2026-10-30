import { act, fireEvent, render, screen } from '@testing-library/react';
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
  show_in_legend: true,
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
    ungroupedKeys: new Set(),
  }],
};

function Harness({
  onRefresh = vi.fn(),
  featureResult = RESULT,
}: { onRefresh?: () => void; featureResult?: AccessibleMapFeatureResult }) {
  return (
    <AccessibleMapDataPanel
      layers={[LAYER]}
      visibleLayers={new Set(['layer-1'])}
      featureResult={featureResult}
      onRefresh={onRefresh}
    />
  );
}

describe('AccessibleMapDataPanel', () => {
  it('offers a keyboard-operable structured alternative to the map canvas', () => {
    render(<Harness />);

    const region = screen.getByRole('region', { name: 'Map layer and feature data' });
    expect(region).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('heading', { name: 'Layers', level: 3 })).toBeInTheDocument();
    expect(screen.getAllByText('Public roads')).toHaveLength(2);
    expect(screen.getByText('Visible')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'City Hall', level: 4 })).toBeInTheDocument();
    expect(screen.getByText('Street Name')).toBeInTheDocument();
    expect(screen.getByText('Fayette Street')).toBeInTheDocument();
  });

  it('shows a year without digit grouping and a measure with it', () => {
    const [feature] = RESULT.features;
    render(
      <Harness
        featureResult={{
          ...RESULT,
          features: [{
            ...feature,
            properties: [['year_built', 1952], ['lane_feet', 1952]],
            ungroupedKeys: new Set(['year_built']),
          }],
        }}
      />,
    );

    expect(screen.getByText('1952')).toBeInTheDocument();
    expect(screen.getByText('1,952')).toBeInTheDocument();
  });

  it('refreshes the viewport-derived feature list on demand', () => {
    const onRefresh = vi.fn();
    render(<Harness onRefresh={onRefresh} />);

    fireEvent.click(screen.getByRole('button', { name: 'Refresh view' }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('keeps the layer inventory useful when no vector features are queryable', () => {
    render(
      <AccessibleMapDataPanel
        layers={[LAYER]}
        visibleLayers={new Set()}
        featureResult={{ features: [], total: 0, truncated: false }}
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
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Feature cluster 1', level: 4 })).toBeInTheDocument();
    expect(screen.getByText('Cluster containing 42 features')).toBeInTheDocument();
  });

  it('announces the result summary once the map settles, not on every refresh', () => {
    vi.useFakeTimers();
    try {
      const panel = (total: number) => (
        <AccessibleMapDataPanel
          layers={[LAYER]}
          visibleLayers={new Set(['layer-1'])}
          featureResult={{ ...RESULT, total }}
          onRefresh={vi.fn()}
        />
      );
      const { rerender } = render(panel(1));
      const live = screen.getByRole('status');
      // Opened with a summary already available: the region must start empty.
      expect(live).toBeEmptyDOMElement();

      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(live.textContent).toContain('1');

      const settled = live.textContent;
      rerender(panel(2));
      rerender(panel(3));
      expect(live.textContent).toBe(settled);

      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(live.textContent).toContain('3');
    } finally {
      vi.useRealTimers();
    }
  });

  describe('when the feature list is capped', () => {
    const RASTER: SharedLayerResponse = {
      ...LAYER,
      id: 'layer-2',
      dataset_id: 'dataset-2',
      dataset_name: 'Imagery',
      display_name: null,
      layer_type: 'raster_geolens',
    };
    const HIDDEN: SharedLayerResponse = {
      ...LAYER,
      id: 'layer-3',
      dataset_id: 'dataset-3',
      dataset_name: 'Parcels',
      display_name: 'Hidden parcels',
    };
    const CAPPED: AccessibleMapFeatureResult = { ...RESULT, total: 250, truncated: true };

    function renderCapped(
      datasetLinksAllowed?: boolean,
      featureResult = CAPPED,
      table?: { keys: ReadonlySet<string>; onOpen: (key: string) => void },
    ) {
      render(
        <AccessibleMapDataPanel
          layers={[LAYER, RASTER, HIDDEN]}
          visibleLayers={new Set(['layer-1', 'layer-2'])}
          featureResult={featureResult}
          onRefresh={vi.fn()}
          datasetLinksAllowed={datasetLinksAllowed}
          tableLayerKeys={table?.keys}
          onOpenTable={table?.onOpen}
        />,
      );
    }

    it('tells the visitor to zoom in, with no dataset links unless they are allowed', () => {
      renderCapped();

      expect(screen.getByText(/zoom in or pan the map/i)).toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
    });

    it('links each visible vector layer to its dataset data tab when allowed', () => {
      renderCapped(true);

      const link = screen.getByRole('link', { name: 'View all data for Public roads' });
      expect(link).toHaveAttribute('href', '/datasets/dataset-1#data');
      expect(link).toHaveAttribute('target', '_blank');
      expect(screen.getAllByRole('link')).toHaveLength(1);
    });

    it('offers each visible table layer in the table instead of dataset links', () => {
      const onOpen = vi.fn();
      renderCapped(true, CAPPED, { keys: new Set(['layer-1', 'layer-3']), onOpen });

      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      // The hidden layer is offered nowhere, even though it has a table.
      expect(screen.getAllByRole('button', { name: /in the table/ })).toHaveLength(1);
      fireEvent.click(screen.getByRole('button', { name: 'Open Public roads in the table' }));
      expect(onOpen).toHaveBeenCalledWith('layer-1');
    });

    it('shows no hint or links while every visible feature is listed', () => {
      renderCapped(true, RESULT);

      expect(screen.queryByText(/zoom in or pan the map/i)).not.toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
    });
  });
});
