/**
 * ENH-06 (Phase 1201-06) — legend customization round-trip.
 *
 * Proves that a custom map-level legend title + a per-entry legendLabel override
 * render IDENTICALLY in the builder (LegendPlugin) and the viewer (LayerLegend),
 * and that an absent/empty config falls back to the prior default names with no
 * title heading.
 *
 * The "round-trip" is the shared contract: the title rides a map-level field
 * (ctx.legendTitle / LayerLegend legendTitle prop) and the per-entry label rides
 * style_config.legendLabel — the SAME persisted shape on both sides.
 */

import { render, screen } from '@/test/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { LegendPlugin } from '@/components/map-plugins/builtin/LegendPlugin';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import type { PluginContext } from '@/components/map-plugins/types';
import type { MapLayerResponse, SharedLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

const CUSTOM_TITLE = 'Population by tract';
const ENTRY_OVERRIDE = 'Median household income';
const DEFAULT_NAME = 'Census Tracts';

function builderLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: DEFAULT_NAME,
    dataset_geometry_type: 'MULTIPOLYGON',
    dataset_table_name: 'tracts',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: DEFAULT_NAME,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'fill-color': '#3b82f6' },
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: 'vector_geolens',
    show_in_legend: true,
    ...overrides,
  };
}

function viewerLayer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: DEFAULT_NAME,
    display_name: DEFAULT_NAME,
    table_name: 'tracts',
    geometry_type: 'MULTIPOLYGON',
    column_info: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'fill-color': '#3b82f6' },
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    show_in_legend: true,
    tile_url: '/tiles/tracts/{z}/{x}/{y}.pbf',
    ...overrides,
  };
}

function makeCtx(overrides: Partial<PluginContext> = {}): PluginContext {
  return {
    mapInstance: null,
    layers: [],
    mapId: 'map-1',
    terrainConfig: null,
    ...overrides,
  };
}

describe('ENH-06 legend customization — builder (LegendPlugin)', () => {
  it('renders the custom legend title and per-entry legendLabel override', () => {
    render(
      <LegendPlugin
        ctx={makeCtx({
          legendTitle: CUSTOM_TITLE,
          layers: [builderLayer({ style_config: { legendLabel: ENTRY_OVERRIDE } as MapLayerResponse['style_config'] })],
        })}
      />,
    );

    expect(screen.getByTestId('legend-title')).toHaveTextContent(CUSTOM_TITLE);
    expect(screen.getByText(ENTRY_OVERRIDE)).toBeInTheDocument();
    expect(screen.queryByText(DEFAULT_NAME)).not.toBeInTheDocument();
  });

  it('falls back to the default name and renders no custom title when config is absent', () => {
    render(<LegendPlugin ctx={makeCtx({ layers: [builderLayer()] })} />);

    expect(screen.queryByTestId('legend-title')).not.toBeInTheDocument();
    expect(screen.getByText(DEFAULT_NAME)).toBeInTheDocument();
  });
});

describe('ENH-06 legend customization — viewer (LayerLegend)', () => {
  it('renders the custom legend title and per-entry legendLabel override (parity)', () => {
    render(
      <LayerLegend
        layers={[viewerLayer({ style_config: { legendLabel: ENTRY_OVERRIDE } as SharedLayerResponse['style_config'] })]}
        visibleLayers={new Set(['layer-1'])}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
        legendTitle={CUSTOM_TITLE}
      />,
    );

    expect(screen.getByTestId('viewer-legend-title')).toHaveTextContent(CUSTOM_TITLE);
    expect(screen.getByText(ENTRY_OVERRIDE)).toBeInTheDocument();
    expect(screen.queryByText(DEFAULT_NAME)).not.toBeInTheDocument();
  });

  it('falls back to the default name and renders no custom title when config is absent', () => {
    render(
      <LayerLegend
        layers={[viewerLayer()]}
        visibleLayers={new Set(['layer-1'])}
        onToggleVisibility={vi.fn()}
        isOpen
        onToggle={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('viewer-legend-title')).not.toBeInTheDocument();
    expect(screen.getByText(DEFAULT_NAME)).toBeInTheDocument();
  });
});
