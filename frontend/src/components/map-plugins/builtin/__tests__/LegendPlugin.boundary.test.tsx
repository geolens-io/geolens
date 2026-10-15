import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LegendPlugin } from '../LegendPlugin';
import type { PluginContext } from '../../types';
import type { MapLayerResponse } from '@/types/api';

vi.mock('@/components/map/layer-icons', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/components/map/layer-icons')>()),
  LayerTypeIcon: ({ layer }: { layer: MapLayerResponse }) => {
    if (layer.id === 'broken') throw new Error('icon failed');
    return <span data-testid="icon" />;
  },
}));

function layer(id: string, name: string): MapLayerResponse {
  return {
    id,
    dataset_id: `ds-${id}`,
    dataset_name: name,
    display_name: name,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    show_in_legend: true,
    is_dem: false,
    style_config: null,
  } as MapLayerResponse;
}

describe('LegendPlugin entry resilience', () => {
  it('replaces a layer whose entry throws while rendering and keeps the others', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const ctx: PluginContext = {
      mapInstance: null,
      layers: [layer('broken', 'Broken layer'), layer('ok', 'Roads')],
      mapId: 'test-map',
      terrainConfig: null,
    };
    render(<LegendPlugin ctx={ctx} />);

    expect(screen.getByText('Broken layer')).toBeInTheDocument();
    expect(screen.getByText(/legend unavailable/i)).toBeInTheDocument();
    expect(screen.getByText('Roads')).toBeInTheDocument();
    expect(screen.getAllByTestId('icon')).toHaveLength(1);
  });
});
