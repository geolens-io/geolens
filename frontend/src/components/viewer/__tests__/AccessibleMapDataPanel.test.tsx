import { useState } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
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
  container,
}: { onRefresh?: () => void; featureResult?: AccessibleMapFeatureResult; container?: HTMLElement | null }) {
  const [open, setOpen] = useState(false);
  return (
    <AccessibleMapDataPanel
      layers={[LAYER]}
      visibleLayers={new Set(['layer-1'])}
      featureResult={featureResult}
      open={open}
      onOpenChange={setOpen}
      onRefresh={onRefresh}
      container={container}
    />
  );
}

describe('AccessibleMapDataPanel', () => {
  it('sits as a tab centered on the bottom edge', () => {
    render(<Harness />);

    const trigger = screen.getByRole('button', { name: 'Map data' });
    expect(trigger).toHaveClass('bottom-0', 'left-1/2', '-translate-x-1/2', 'rounded-b-none');
    // The label stays in the DOM (visually hidden when narrow) and doubles as a tooltip.
    expect(trigger).toHaveAccessibleName('Map data');
    expect(trigger).toHaveAttribute('title', 'Map data');
  });

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

    fireEvent.click(screen.getByRole('button', { name: 'Map data' }));

    const dialog = screen.getByRole('dialog', { name: 'Map data' });
    expect(within(dialog).getByText('1952')).toBeInTheDocument();
    expect(within(dialog).getByText('1,952')).toBeInTheDocument();
  });

  it('opens inside the map area it is given, not over the whole page', () => {
    const mapArea = document.createElement('div');
    document.body.append(mapArea);
    render(<Harness container={mapArea} />);

    fireEvent.click(screen.getByRole('button', { name: 'Map data' }));

    const dialog = screen.getByRole('dialog', { name: 'Map data' });
    expect(mapArea).toContainElement(dialog);
    // Over the map area from md up; a phone keeps the whole screen.
    expect(dialog).toHaveClass('absolute', 'max-md:fixed');
    expect(dialog).not.toHaveClass('fixed');
    const overlay = mapArea.querySelector('[data-slot="sheet-overlay"]');
    expect(overlay).toHaveClass('absolute', 'max-md:fixed');
    expect(overlay).not.toHaveClass('fixed');
    mapArea.remove();
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

  it('announces the result summary once the map settles, not on every refresh', () => {
    vi.useFakeTimers();
    try {
      const panel = (total: number) => (
        <AccessibleMapDataPanel
          layers={[LAYER]}
          visibleLayers={new Set(['layer-1'])}
          featureResult={{ ...RESULT, total }}
          open
          onOpenChange={vi.fn()}
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

    function renderCapped(datasetLinksAllowed?: boolean, featureResult = CAPPED) {
      render(
        <AccessibleMapDataPanel
          layers={[LAYER, RASTER, HIDDEN]}
          visibleLayers={new Set(['layer-1', 'layer-2'])}
          featureResult={featureResult}
          open
          onOpenChange={vi.fn()}
          onRefresh={vi.fn()}
          datasetLinksAllowed={datasetLinksAllowed}
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

    it('shows no hint or links while every visible feature is listed', () => {
      renderCapped(true, RESULT);

      expect(screen.queryByText(/zoom in or pan the map/i)).not.toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
    });
  });
});
