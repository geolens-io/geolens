import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LegendPlugin } from '../LegendPlugin';
import type { PluginContext } from '../../types';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';

function layer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Roads',
    display_name: 'Roads',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    show_in_legend: true,
    is_dem: false,
    style_config: null,
    ...overrides,
  } as MapLayerResponse;
}

function createCtx(overrides: Partial<PluginContext> = {}): PluginContext {
  return {
    mapInstance: null,
    layers: [],
    mapId: 'test-map',
    terrainConfig: null,
    ...overrides,
  };
}

const activeTerrain: MapTerrainConfig = {
  enabled: true,
  source_dataset_id: 'dem-1',
  exaggeration: 1.5,
};

const demTerrainStyle = { render_mode: 'terrain' } as MapLayerResponse['style_config'];
const demHillshadeStyle = { render_mode: 'hillshade' } as MapLayerResponse['style_config'];

// 999.17 MD-01: the synthetic "3D terrain" entry only renders when a
// terrain-capable DEM layer backing terrain_config.source_dataset_id ('dem-1')
// is actually present. This is that backing layer (terrain render_mode → also
// suppressed from per-layer entries, exactly as on a real terrain map).
function backingDemLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return layer({
    id: 'dem-terrain',
    display_name: 'Elevation (terrain)',
    dataset_id: 'dem-1',
    dataset_record_type: 'raster_dataset',
    is_dem: true,
    style_config: demTerrainStyle,
    ...overrides,
  });
}

describe('LegendPlugin terrain consistency (Fix 1)', () => {
  it('excludes a terrain-suppressed DEM layer from per-layer entries (D-02)', () => {
    const ctx = createCtx({
      layers: [
        layer({ id: 'roads', display_name: 'Roads' }),
        layer({
          id: 'dem-terrain',
          display_name: 'Elevation (terrain)',
          is_dem: true,
          style_config: demTerrainStyle,
        }),
      ],
      terrainConfig: activeTerrain,
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.getByText('Roads')).toBeInTheDocument();
    expect(screen.queryByText('Elevation (terrain)')).not.toBeInTheDocument();
  });

  it('shows exactly one synthetic 3D terrain entry when terrain_config is active (D-01)', () => {
    const ctx = createCtx({
      layers: [layer({ id: 'roads', display_name: 'Roads' }), backingDemLayer()],
      terrainConfig: activeTerrain,
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.getAllByTestId('legend-terrain-synthetic')).toHaveLength(1);
    expect(screen.getByText('3D terrain')).toBeInTheDocument();
  });

  it('does NOT show the synthetic entry when terrain is configured but disabled', () => {
    const ctx = createCtx({
      layers: [layer({ id: 'roads', display_name: 'Roads' }), backingDemLayer()],
      terrainConfig: { enabled: false, source_dataset_id: 'dem-1', exaggeration: 1 },
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
  });

  // 999.17 MD-01: dangling terrain_config (enabled + source, but NO backing DEM
  // layer for that dataset) must NOT render a phantom synthetic entry.
  it('does NOT show the synthetic entry for a dangling terrain_config (no backing DEM layer)', () => {
    const ctx = createCtx({
      layers: [layer({ id: 'roads', display_name: 'Roads' })], // no DEM layer on dem-1
      terrainConfig: activeTerrain,
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
    expect(screen.getByText('Roads')).toBeInTheDocument();
  });

  it('pins the synthetic terrain entry ABOVE per-layer entries (A1 position assertion)', () => {
    const ctx = createCtx({
      layers: [
        layer({ id: 'roads', display_name: 'Roads' }),
        backingDemLayer(),
      ],
      terrainConfig: activeTerrain,
    });
    const { container } = render(<LegendPlugin ctx={ctx} />);

    const synthetic = screen.getByTestId('legend-terrain-synthetic');
    const roads = screen.getByText('Roads');
    // Synthetic entry must precede the first per-layer entry in DOM order (top
    // of the relief/terrain group, mirroring map-stack's relief:terrain row).
    expect(
      synthetic.compareDocumentPosition(roads) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Sanity: the synthetic row is the first child of the legend container.
    const root = container.querySelector('.min-w-44');
    expect(root?.firstElementChild).toBe(synthetic);
  });

  it('keeps a painting hillshade-mode relief DEM layer as a normal entry (D-03)', () => {
    const ctx = createCtx({
      layers: [
        layer({
          id: 'dem-hillshade',
          display_name: 'Hillshade relief',
          is_dem: true,
          style_config: demHillshadeStyle,
        }),
      ],
      terrainConfig: activeTerrain,
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.getByText('Hillshade relief')).toBeInTheDocument();
  });

  // Dedup: when the terrain SOURCE dataset is itself shown as a visible hillshade
  // entry (same dataset_id as terrain_config.source_dataset_id, e.g. the
  // Matterhorn swissALTI3D map), the synthetic "3D terrain" entry would list one
  // DEM twice. Suppress it; the hillshade entry stands in.
  it('drops the synthetic entry when the source DEM is shown as a visible hillshade layer', () => {
    const ctx = createCtx({
      layers: [
        layer({
          id: 'dem-hillshade',
          display_name: 'swissALTI3D relief',
          dataset_id: 'dem-1', // SAME dataset as activeTerrain.source_dataset_id
          dataset_record_type: 'raster_dataset',
          is_dem: true,
          style_config: demHillshadeStyle,
        }),
      ],
      terrainConfig: activeTerrain,
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.getByText('swissALTI3D relief')).toBeInTheDocument();
    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
    expect(screen.queryByText('3D terrain')).not.toBeInTheDocument();
  });

  // In the builder, BuilderMap clears terrain when the bound DEM is HIDDEN
  // (effectiveTerrainEnabled = enabled && demLayerVisible). The synthetic entry
  // must track that — no mesh rendered, no "3D terrain" row.
  it('drops the synthetic entry when the bound terrain DEM is hidden (no mesh rendered)', () => {
    const ctx = createCtx({
      layers: [backingDemLayer({ visible: false })],
      terrainConfig: activeTerrain,
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
    expect(screen.queryByText('3D terrain')).not.toBeInTheDocument();
  });

  it('leaves non-DEM layers unaffected when terrain is inactive (regression)', () => {
    const ctx = createCtx({
      layers: [
        layer({ id: 'roads', display_name: 'Roads' }),
        layer({ id: 'parks', display_name: 'Parks' }),
      ],
      terrainConfig: null,
    });
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.getByText('Roads')).toBeInTheDocument();
    expect(screen.getByText('Parks')).toBeInTheDocument();
    expect(screen.queryByTestId('legend-terrain-synthetic')).not.toBeInTheDocument();
  });
});
