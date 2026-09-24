/** Both legends draw the map's custom title, each entry's name, its swatches and its classes from legendFacts. */

import { render, screen } from '@/test/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { LegendPlugin } from '@/components/map-plugins/builtin/LegendPlugin';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { legendFacts } from '@/components/map/legend-facts';
import type { PluginContext } from '@/components/map-plugins/types';
import { MAP_COLORS } from '@/lib/map-colors';
import { SAVED_LAYERS, ZOOM_FADED_STATIONS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

const CUSTOM_TITLE = 'Population by tract';
const labelledLayer = savedLayer({
  display_name: 'Census Tracts',
  style_config: { legendLabel: 'Median household income' },
});
const entryName = legendFacts(labelledLayer)!.name;

function makeCtx(overrides: Partial<PluginContext> = {}): PluginContext {
  return {
    mapInstance: null,
    layers: [labelledLayer],
    mapId: 'map-1',
    terrainConfig: null,
    ...overrides,
  };
}

function renderViewerLegend(legendTitle?: string, layer = labelledLayer) {
  return render(
    <LayerLegend
      layers={[toSharedLayer(layer)]}
      visibleLayers={new Set([layer.id])}
      onToggleVisibility={vi.fn()}
      isOpen
      onToggle={vi.fn()}
      legendTitle={legendTitle}
    />,
  );
}

/** A CSS colour as the DOM reports it back. */
function cssColor(color: string): string {
  const probe = document.createElement('div');
  probe.style.color = color;
  return probe.style.color;
}

// Zoning is a categorical polygon layer with no stored stroke.
const zoning = SAVED_LAYERS.categorical;

function classSwatchBorders(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll<HTMLElement>('div[aria-hidden="true"]'), (chip) => chip.style.borderColor);
}

describe('builder legend (LegendPlugin)', () => {
  it('draws the custom title and the entry name from legendFacts', () => {
    render(<LegendPlugin ctx={makeCtx({ legendTitle: CUSTOM_TITLE })} />);

    expect(screen.getByTestId('legend-title')).toHaveTextContent(CUSTOM_TITLE);
    expect(screen.getByText(entryName)).toBeInTheDocument();
  });

  it('draws no title heading without a custom title', () => {
    render(<LegendPlugin ctx={makeCtx()} />);

    expect(screen.queryByTestId('legend-title')).not.toBeInTheDocument();
  });

  it('outlines class swatches with the default outline the map draws when no stroke is stored', () => {
    const { container } = render(<LegendPlugin ctx={makeCtx({ layers: [zoning] })} />);

    const borders = classSwatchBorders(container);
    expect(borders).toHaveLength(3);
    expect(new Set(borders)).toEqual(new Set([cssColor(MAP_COLORS.default.stroke)]));
  });
});

describe('viewer legend (LayerLegend)', () => {
  it('draws the custom title and the entry name from legendFacts', () => {
    renderViewerLegend(CUSTOM_TITLE);

    expect(screen.getByTestId('viewer-legend-title')).toHaveTextContent(CUSTOM_TITLE);
    expect(screen.getByText(entryName)).toBeInTheDocument();
  });

  it('draws no title heading without a custom title', () => {
    renderViewerLegend();

    expect(screen.queryByTestId('viewer-legend-title')).not.toBeInTheDocument();
  });

  it('outlines class swatches with the default outline the map draws when no stroke is stored', () => {
    const { container } = renderViewerLegend(undefined, zoning);

    const borders = classSwatchBorders(container);
    expect(borders).toHaveLength(3);
    expect(new Set(borders)).toEqual(new Set([cssColor(MAP_COLORS.default.stroke)]));
  });
});

describe('classes in both legends', () => {
  const legends = {
    builder: (layer: MapLayerResponse) => render(<LegendPlugin ctx={makeCtx({ layers: [layer] })} />).container,
    viewer: (layer: MapLayerResponse) => renderViewerLegend(undefined, layer).container,
  };
  const symbolLayer = SAVED_LAYERS.symbolWithLeftoverClassification;
  const orphanedZoning = { ...zoning, paint: { 'fill-color': '#66c2a5', 'fill-opacity': 0.7 } };
  const magnitudeCircles = savedLayer({
    dataset_geometry_type: 'MULTIPOINT',
    paint: {
      'circle-radius': ['step', ['get', 'mag'], 4, 6, 8, 7, 14],
      'circle-color': ['step', ['get', 'mag'], '#fee8c8', 6, '#fdbb84', 7, '#e34a33'],
    },
    style_config: { mode: 'graduated', column: 'mag', target: 'radius', sizes: [4, 8, 14], breaks: [6, 7] },
  });
  const storedHeat = (heatmapColor: unknown[]) =>
    ({ ...SAVED_LAYERS.heatmapByRamp, paint: { ...SAVED_LAYERS.heatmapByRamp.paint, 'heatmap-color': heatmapColor } });
  const riversByBasin = {
    ...SAVED_LAYERS.graduatedWidth,
    paint: { ...SAVED_LAYERS.graduatedWidth.paint, 'line-color': ['step', ['get', 'basin'], '#bae6fd', 3, '#0369a1'] },
  };

  it.each(Object.entries(legends))('%s legend lists no classes for a symbol layer', (_legend, draw) => {
    draw(symbolLayer);

    expect(screen.queryByText('School')).not.toBeInTheDocument();
  });

  it.each(Object.entries(legends))('%s legend lists no classes the paint no longer draws', (_legend, draw) => {
    draw(orphanedZoning);

    expect(screen.queryByText('Residential')).not.toBeInTheDocument();
  });

  it.each(Object.entries(legends))('%s legend draws each size in its class colour when colour and size share breaks', (_legend, draw) => {
    const container = draw(magnitudeCircles);

    expect(screen.queryByText(/viewer\.legend\.colorLabel/)).not.toBeInTheDocument();
    const sizes = Array.from(container.querySelectorAll('svg[viewBox="0 0 24 24"]:not(.lucide) circle'));
    expect(sizes.map((circle) => circle.getAttribute('fill'))).toEqual(['#fee8c8', '#fdbb84', '#e34a33']);
  });

  it.each(Object.entries(legends))('%s legend draws width classes in the colour the paint gives them', (_legend, draw) => {
    const container = draw(riversByBasin);

    // Three width classes and the first colour class.
    expect(container.querySelectorAll('line[stroke="#bae6fd"]')).toHaveLength(4);
  });

  it.each(Object.entries(legends))('%s legend draws zoom-faded categories at the opacity they fade in to', (_legend, draw) => {
    const container = draw(ZOOM_FADED_STATIONS);

    const chips = Array.from(container.querySelectorAll('svg[viewBox="0 0 14 14"] circle'));
    expect(chips.map((chip) => [chip.getAttribute('fill'), chip.getAttribute('fill-opacity')])).toEqual([
      ['#22c55e', '0.95'],
      ['#a3e635', '0.95'],
      ['#94a3b8', '0.95'],
    ]);
  });

  it('viewer legend icon fills zoom-faded categories at the opacity they fade in to', () => {
    const container = legends.viewer(ZOOM_FADED_STATIONS);

    expect(container.querySelector('.lucide-circle')).toHaveAttribute('fill-opacity', '0.95');
  });

  it.each(Object.entries(legends))('%s legend draws the stored heatmap colour the map draws', (_legend, draw) => {
    const container = draw(SAVED_LAYERS.heatmapByExpression);

    const gradient = (container.querySelector('.h-3.rounded-sm.w-full') as HTMLElement).style.background;
    expect(gradient).toContain('rgb(124, 58, 237)');
    expect(gradient).toContain('rgb(240, 171, 252)');
  });

  it.each(Object.entries(legends))('%s legend draws a heatmap ramp in the five colours the map draws', (_legend, draw) => {
    const container = draw(SAVED_LAYERS.heatmapByRamp);

    const gradient = (container.querySelector('.h-3.rounded-sm.w-full') as HTMLElement).style.background;
    expect(gradient.match(/rgb\(/g)).toHaveLength(5);
  });

  it.each(Object.entries(legends))('%s legend draws a stored heatmap ramp at its own stops', (_legend, draw) => {
    const container = draw(storedHeat(['interpolate', ['linear'], ['heatmap-density'], 0, '#0000ff', 0.1, '#00ff00', 1, '#ff0000']));

    const gradient = (container.querySelector('.h-3.rounded-sm.w-full') as HTMLElement).style.background;
    expect(gradient).toBe('linear-gradient(to right, rgb(0, 0, 255) 0%, rgb(0, 255, 0) 10%, rgb(255, 0, 0) 100%)');
  });

  it.each(Object.entries(legends))('%s legend draws a stored heatmap step as hard bands', (_legend, draw) => {
    const container = draw(storedHeat(['step', ['heatmap-density'], '#fde725', 0.3, '#440154']));

    const gradient = (container.querySelector('.h-3.rounded-sm.w-full') as HTMLElement).style.background;
    expect(gradient).toBe(
      'linear-gradient(to right, rgb(253, 231, 37) 0%, rgb(253, 231, 37) 30%, rgb(68, 1, 84) 30%, rgb(68, 1, 84) 100%)',
    );
  });

  it.each(Object.entries(legends))('%s legend draws no heatmap ramp for a stored colour it cannot read', (_legend, draw) => {
    const container = draw({ ...SAVED_LAYERS.heatmapByRamp, paint: { ...SAVED_LAYERS.heatmapByRamp.paint, 'heatmap-color': ['get', 'color'] } });

    expect(container.querySelector('.h-3.rounded-sm.w-full')).not.toBeInTheDocument();
  });

  it('builder legend names the column a heatmap is weighted by', () => {
    legends.builder(SAVED_LAYERS.heatmapByRamp);

    expect(screen.getByText('plugins.legend.weightedBy')).toBeInTheDocument();
  });

  it('builder legend lists graduated classes that have no breaks', () => {
    const noBreaks = { ...SAVED_LAYERS.graduatedColor, style_config: { ...SAVED_LAYERS.graduatedColor.style_config, breaks: undefined } };
    const container = legends.builder(noBreaks);

    expect(container.querySelectorAll('div[aria-hidden="true"]')).toHaveLength(3);
  });

  it('builder legend shows the icon row for a style that names a column but draws no classes', () => {
    const container = legends.builder(savedLayer({ paint: { 'fill-color': '#3b82f6' }, style_config: { mode: 'categorical', column: 'zone', categories: [] } }));

    expect(container.querySelector('.lucide-pentagon')).toBeInTheDocument();
  });
});
