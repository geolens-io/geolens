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

  it('colors graduated-size swatches with a constant fill, not the gray fallback', () => {
    // Regression: a constant (string) circle-color is not an expression, so
    // parsePaintColors returns null — the radius legend must still use the real
    // color instead of falling back to gray (#cccccc).
    const constColorLayer = layer({
      id: 'layer-const',
      display_name: 'Magnitude (graduated)',
      paint: {
        'circle-radius': ['step', ['get', 'mag'], 4, 5, 7, 6, 11, 7, 16],
        'circle-color': '#ef4444',
      },
      style_config: {
        mode: 'graduated',
        column: 'mag',
        target: 'radius',
        ramp: 'YlOrRd',
        breaks: [5, 6, 7],
        sizes: [4, 7, 11, 16],
        sizeLabel: 'Magnitude',
      },
    });

    const { container } = render(
      <LayerLegend
        layers={[constColorLayer]}
        visibleLayers={new Set(['layer-const'])}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText('Size: Magnitude')).toBeInTheDocument();
    expect(container.querySelectorAll('circle[fill="#ef4444"]').length).toBeGreaterThanOrEqual(1);
    expect(container.querySelector('circle[fill="#cccccc"]')).toBeNull();
  });

  it('shows a raster icon, not a colored point swatch, for raster layers', () => {
    // Regression: raster layers (no vector fill) were given the #6366f1 default
    // color + a point swatch. They should render a raster icon like the builder.
    const rasterLayer = layer({
      id: 'raster-1',
      display_name: 'Sentinel-2 scene 1',
      layer_type: 'raster_geolens',
      dataset_record_type: 'raster_dataset',
      // geometry_type stays 'POINT' (as real raster layers report) so the bug —
      // a purple circle swatch — is what we assert is gone.
      paint: {},
      style_config: null,
    });

    const { container } = render(
      <LayerLegend
        layers={[rasterLayer]}
        visibleLayers={new Set(['raster-1'])}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText('Sentinel-2 scene 1')).toBeInTheDocument();
    expect(container.querySelector('[fill="#6366f1"]')).toBeNull();
    expect(container.querySelector('circle[fill="#6366f1"]')).toBeNull();
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
      // 999.17 MD-01: must be terrain-capable (raster_dataset) so the synthetic
      // entry's backing-layer check (isTerrainCapableDemLayer) passes.
      dataset_record_type: 'raster_dataset',
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
        layers={[
          vectorLayer(),
          demLayer({ style_config: { render_mode: 'terrain' } as SharedLayerResponse['style_config'] }),
        ]}
        visibleLayers={new Set(['roads', 'dem-layer'])}
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

  // 999.17 MD-01: dangling terrain_config (enabled + source, NO backing DEM
  // layer) must NOT render a phantom synthetic entry in the viewer either.
  it('does NOT show the synthetic entry for a dangling terrain_config (no backing DEM layer)', () => {
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

    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
    expect(screen.getByText('Roads')).toBeInTheDocument();
  });

  it('pins the synthetic terrain entry ABOVE per-layer entries (A1 position assertion)', () => {
    render(
      <LayerLegend
        layers={[
          vectorLayer(),
          demLayer({ style_config: { render_mode: 'terrain' } as SharedLayerResponse['style_config'] }),
        ]}
        visibleLayers={new Set(['roads', 'dem-layer'])}
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

  // Dedup: when the terrain SOURCE DEM is shown as a visible hillshade entry of
  // the same dataset (the Matterhorn swissALTI3D case), suppress the synthetic
  // "3D terrain" entry so the legend doesn't list one DEM twice.
  it('drops the synthetic entry when the source DEM is shown as a visible hillshade layer', () => {
    render(
      <LayerLegend
        layers={[
          demLayer({
            id: 'dem-hillshade',
            display_name: 'swissALTI3D relief',
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

    expect(screen.getByText('swissALTI3D relief')).toBeInTheDocument();
    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
    expect(screen.queryByText('3D terrain')).not.toBeInTheDocument();
  });

  // Regression: the viewer keeps toggled-off layers in the list (visibility
  // lives in visibleLayers, not the list), but 3D terrain stays active from
  // terrain_config regardless. If the source hillshade is toggled OFF, the
  // synthetic entry must STILL show — otherwise active 3D terrain has no legend
  // representation. So dedup against visible entries only.
  it('keeps the synthetic entry when the source DEM is toggled off but terrain is active', () => {
    render(
      <LayerLegend
        layers={[
          demLayer({
            id: 'dem-hillshade',
            display_name: 'swissALTI3D relief',
            style_config: { render_mode: 'hillshade' } as SharedLayerResponse['style_config'],
          }),
        ]}
        visibleLayers={new Set()} /* source layer toggled OFF */
        terrainConfig={activeTerrain}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByTestId('legend-terrain-synthetic')).toBeInTheDocument();
    expect(screen.getByText('3D terrain')).toBeInTheDocument();
  });
});
