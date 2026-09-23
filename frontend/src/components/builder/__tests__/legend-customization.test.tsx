/** Both legends draw the map's custom title and each entry's name from legendFacts. */

import { render, screen } from '@/test/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { LegendPlugin } from '@/components/map-plugins/builtin/LegendPlugin';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { legendFacts } from '@/components/map/legend-facts';
import type { PluginContext } from '@/components/map-plugins/types';
import { savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';

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

function renderViewerLegend(legendTitle?: string) {
  return render(
    <LayerLegend
      layers={[toSharedLayer(labelledLayer)]}
      visibleLayers={new Set([labelledLayer.id])}
      onToggleVisibility={vi.fn()}
      isOpen
      onToggle={vi.fn()}
      legendTitle={legendTitle}
    />,
  );
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
});
