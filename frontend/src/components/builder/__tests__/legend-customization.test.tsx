/** Both legends draw the map's custom title, each entry's name and its swatches from legendFacts. */

import { render, screen } from '@/test/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { LegendPlugin } from '@/components/map-plugins/builtin/LegendPlugin';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { legendFacts } from '@/components/map/legend-facts';
import type { PluginContext } from '@/components/map-plugins/types';
import { MAP_COLORS } from '@/lib/map-colors';
import { SAVED_LAYERS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';

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
