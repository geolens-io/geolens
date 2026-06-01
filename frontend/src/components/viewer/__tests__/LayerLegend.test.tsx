import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LayerLegend } from '../LayerLegend';
import type { MapTerrainConfig, SharedLayerResponse } from '@/types/api';

function layer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
  return {
    dataset_id: 'dataset-1',
    id: 'layer-1',
    dataset_name: 'Earthquakes',
    display_name: 'Earthquakes (M5+)',
    table_name: 'quakes',
    geometry_type: 'POINT',
    column_info: null,
    sort_order: 0,
    visible: true,
    opacity: 0.85,
    paint: {
      'circle-radius': [
        'interpolate',
        ['linear'],
        ['coalesce', ['to-number', ['get', 'mag']], 0],
        5,
        4,
        6,
        8,
        7,
        14,
        8,
        22,
        9,
        30,
      ],
      'circle-color': [
        'interpolate',
        ['linear'],
        ['coalesce', ['to-number', ['get', 'depth_km']], 0],
        0,
        '#fde725',
        50,
        '#f39c12',
        200,
        '#e74c3c',
        700,
        '#7d3c98',
      ],
    },
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: {
      mode: 'graduated',
      column: 'mag',
      target: 'radius',
      classCount: 4,
      ramp: 'YlOrRd',
      colors: ['#fde725', '#f39c12', '#e74c3c', '#7d3c98'],
      breaks: [6, 7, 8, 9],
      sizes: [4, 8, 14, 22, 30],
      sizeLabel: 'Magnitude',
      colorLabel: 'Depth (km)',
    },
    tile_url: '/tiles/quakes/{z}/{x}/{y}.pbf',
    ...overrides,
  };
}

describe('LayerLegend', () => {
  it('separates graduated radius and color semantics for point layers', () => {
    render(
      <LayerLegend
        layers={[layer()]}
        visibleLayers={new Set(['layer-1'])}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText('Size: Magnitude')).toBeInTheDocument();
    expect(screen.getByText('Color: Depth (km)')).toBeInTheDocument();
    expect(screen.getByText('< 6')).toBeInTheDocument();
    expect(screen.getByText(/50.*200/)).toBeInTheDocument();
  });

  it('uses stable layer keys for duplicate sort orders', () => {
    const onToggleVisibility = vi.fn();
    render(
      <LayerLegend
        layers={[
          layer({ id: 'layer-a', display_name: 'First copy', sort_order: 0 }),
          layer({ id: 'layer-b', display_name: 'Second copy', sort_order: 0 }),
        ]}
        visibleLayers={new Set(['layer-a', 'layer-b'])}
        onToggleVisibility={onToggleVisibility}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Hide Second copy' }));

    expect(onToggleVisibility).toHaveBeenCalledWith('layer-b');
  });
});

describe('LayerLegend terrain consistency (Fix 1)', () => {
  const activeTerrain: MapTerrainConfig = {
    enabled: true,
    source_dataset_id: 'dem-1',
    exaggeration: 1.5,
  };

  function demLayer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
    return {
      dataset_id: 'dem-1',
      id: 'dem-layer',
      dataset_name: 'Elevation',
      display_name: 'Elevation',
      table_name: 'dem',
      geometry_type: null,
      column_info: null,
      sort_order: 1,
      visible: true,
      opacity: 1,
      paint: {},
      layout: {},
      filter: null,
      label_config: null,
      popup_config: null,
      style_config: null,
      tile_url: null,
      is_dem: true,
      ...overrides,
    } as SharedLayerResponse;
  }

  function vectorLayer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
    return {
      dataset_id: 'roads-1',
      id: 'roads',
      dataset_name: 'Roads',
      display_name: 'Roads',
      table_name: 'roads',
      geometry_type: 'LINESTRING',
      column_info: null,
      sort_order: 0,
      visible: true,
      opacity: 1,
      paint: { 'line-color': '#333333' },
      layout: {},
      filter: null,
      label_config: null,
      popup_config: null,
      style_config: null,
      tile_url: null,
      is_dem: false,
      ...overrides,
    } as SharedLayerResponse;
  }

  it('excludes a terrain-suppressed DEM layer from per-layer entries (D-02)', () => {
    render(
      <LayerLegend
        layers={[
          vectorLayer(),
          demLayer({ display_name: 'Elevation (terrain)', style_config: { render_mode: 'terrain' } as SharedLayerResponse['style_config'] }),
        ]}
        visibleLayers={new Set(['roads', 'dem-layer'])}
        terrainConfig={activeTerrain}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText('Roads')).toBeInTheDocument();
    expect(screen.queryByText('Elevation (terrain)')).not.toBeInTheDocument();
  });

  it('shows exactly one synthetic 3D terrain entry when terrain_config is active (D-01)', () => {
    render(
      <LayerLegend
        layers={[vectorLayer()]}
        visibleLayers={new Set(['roads'])}
        terrainConfig={activeTerrain}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getAllByTestId('legend-terrain-synthetic')).toHaveLength(1);
    expect(screen.getByText('3D terrain')).toBeInTheDocument();
  });

  it('does NOT show the synthetic entry when terrain is inactive', () => {
    render(
      <LayerLegend
        layers={[vectorLayer()]}
        visibleLayers={new Set(['roads'])}
        terrainConfig={null}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
  });

  it('pins the synthetic terrain entry ABOVE per-layer entries (A1 position assertion)', () => {
    render(
      <LayerLegend
        layers={[vectorLayer()]}
        visibleLayers={new Set(['roads'])}
        terrainConfig={activeTerrain}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    const synthetic = screen.getByTestId('legend-terrain-synthetic');
    const roads = screen.getByText('Roads');
    expect(
      synthetic.compareDocumentPosition(roads) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Synthetic <li> is the first child of the legend list.
    expect(synthetic.parentElement?.firstElementChild).toBe(synthetic);
  });

  it('keeps a painting hillshade-mode relief DEM layer as a normal entry (D-03)', () => {
    render(
      <LayerLegend
        layers={[
          demLayer({
            id: 'dem-hillshade',
            display_name: 'Hillshade relief',
            style_config: { render_mode: 'hillshade' } as SharedLayerResponse['style_config'],
          }),
        ]}
        visibleLayers={new Set(['dem-hillshade'])}
        terrainConfig={activeTerrain}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText('Hillshade relief')).toBeInTheDocument();
  });
});
