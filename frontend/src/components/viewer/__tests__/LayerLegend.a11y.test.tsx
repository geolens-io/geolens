/**
 * Regression test for GLUX-001: closed LayerLegend panel must not trap keyboard focus.
 *
 * Before the fix, the panel stayed mounted with `opacity-0 pointer-events-none`,
 * leaving per-layer visibility toggle buttons in the tab order. A keyboard user
 * could tab into invisible controls, violating WCAG 2.1.1 / 2.4.3.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { SharedLayerResponse } from '@/types/api';
import { LayerLegend } from '../LayerLegend';

function makeLayer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
  return {
    dataset_id: 'ds-glux001',
    id: 'layer-1',
    dataset_name: 'Test Layer',
    display_name: 'Test Layer',
    table_name: 'test_layer',
    geometry_type: 'POINT',
    column_info: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'circle-color': '#0077cc' },
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    tile_url: '/tiles/test/{z}/{x}/{y}.pbf',
    ...overrides,
  };
}

describe('LayerLegend keyboard trap regression (GLUX-001)', () => {
  it('removes per-layer visibility toggles from the a11y tree when legend is closed', () => {
    // Layer is marked visible, so open-state button label would be "Hide Test Layer".
    render(
      <LayerLegend
        layers={[makeLayer()]}
        visibleLayers={new Set(['layer-1'])}
        onToggleVisibility={vi.fn()}
        isOpen={false}
        onToggle={vi.fn()}
      />,
    );

    // Neither "Hide …" nor "Show …" per-layer buttons must be reachable when closed.
    expect(screen.queryByRole('button', { name: /Hide Test Layer/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Show Test Layer/ })).not.toBeInTheDocument();
  });

  it('keeps the legend toggle button focusable when legend is closed', () => {
    render(
      <LayerLegend
        layers={[makeLayer()]}
        visibleLayers={new Set(['layer-1'])}
        onToggleVisibility={vi.fn()}
        isOpen={false}
        onToggle={vi.fn()}
      />,
    );

    // The outer toggle button (aria-controls="layer-legend-panel") is always visible.
    expect(screen.getByRole('button', { name: 'Show legend' })).toBeInTheDocument();
  });

  it('exposes per-layer visibility toggles when legend is open', () => {
    render(
      <LayerLegend
        layers={[makeLayer()]}
        visibleLayers={new Set(['layer-1'])}
        onToggleVisibility={vi.fn()}
        isOpen={true}
        onToggle={vi.fn()}
      />,
    );

    // Per-layer toggles must be present and reachable in the open state.
    expect(screen.getByRole('button', { name: 'Hide Test Layer' })).toBeInTheDocument();
  });

  it('keeps the legend toggle button focusable when legend is open', () => {
    render(
      <LayerLegend
        layers={[makeLayer()]}
        visibleLayers={new Set(['layer-1'])}
        onToggleVisibility={vi.fn()}
        isOpen={true}
        onToggle={vi.fn()}
      />,
    );

    // Toggle button switches its label to "Hide legend" when open.
    expect(screen.getByRole('button', { name: 'Hide legend' })).toBeInTheDocument();
  });
});
