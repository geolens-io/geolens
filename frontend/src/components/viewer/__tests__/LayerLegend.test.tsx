import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LayerLegend } from '../LayerLegend';
import type { SharedLayerResponse } from '@/types/api';

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
