import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SharedLayerResponse } from '@/types/api';
import { LayerLegend } from '../LayerLegend';

const LAYER = {
  dataset_id: 'ds-1',
  id: 'layer-1',
  dataset_name: 'Test Layer',
  display_name: 'Test Layer',
  table_name: 'test_layer',
  geometry_type: 'POINT',
  column_info: null,
  sort_order: 0,
  visible: true,
  show_in_legend: true,
  opacity: 1,
  paint: { 'circle-color': '#0077cc' },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '/tiles/test/{z}/{x}/{y}.pbf',
} as SharedLayerResponse;

function mockPanelGeometry(scrollHeight: number, clientHeight: number) {
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(scrollHeight);
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(clientHeight);
}

function renderLegend() {
  return render(
    <LayerLegend
      layers={[LAYER]}
      visibleLayers={new Set(['layer-1'])}
      onToggleVisibility={vi.fn()}
      isOpen
      onToggle={vi.fn()}
    />,
  );
}

describe('LayerLegend scroll cue', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows a cue while rows are cut off and hides it at the end of the list', () => {
    mockPanelGeometry(600, 300);
    renderLegend();
    expect(screen.getByTestId('legend-more-below')).toBeInTheDocument();

    const panel = screen.getByRole('region');
    vi.spyOn(panel, 'scrollTop', 'get').mockReturnValue(300);
    act(() => {
      fireEvent.scroll(panel);
    });
    expect(screen.queryByTestId('legend-more-below')).not.toBeInTheDocument();
  });

  it('shows no cue when everything fits', () => {
    mockPanelGeometry(300, 300);
    renderLegend();
    expect(screen.queryByTestId('legend-more-below')).not.toBeInTheDocument();
  });
});
