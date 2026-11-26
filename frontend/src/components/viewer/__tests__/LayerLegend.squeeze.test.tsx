import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SharedLayerResponse } from '@/types/api';
import { LayerLegend } from '../LayerLegend';

const LAYER = {
  dataset_id: 'ds-1', id: 'layer-1', dataset_name: 'Test Layer', display_name: 'Test Layer',
  table_name: 'test_layer', geometry_type: 'POINT', column_info: null, sort_order: 0, visible: true,
  show_in_legend: true, opacity: 1, paint: { 'circle-color': '#0077cc' }, layout: {}, filter: null,
  label_config: null, popup_config: null, style_config: null, tile_url: '/tiles/test/{z}/{x}/{y}.pbf',
} as SharedLayerResponse;

let roomHeight = 400;
let observers: Array<() => void> = [];

function setRoom(height: number) {
  roomHeight = height;
  act(() => observers.forEach((cb) => cb()));
}

function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <LayerLegend
      layers={[LAYER]}
      visibleLayers={new Set(['layer-1'])}
      onToggleVisibility={vi.fn()}
      isOpen={open}
      onToggle={() => setOpen((o) => !o)}
    />
  );
}

describe('LayerLegend squeezed beside the table', () => {
  beforeEach(() => {
    roomHeight = 400;
    observers = [];
    vi.stubGlobal('ResizeObserver', class {
      constructor(cb: () => void) { observers.push(cb); }
      observe() {}
      disconnect() {}
    });
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const height = this.dataset.testid === 'legend-room' ? roomHeight : 0;
      return { height, width: 0, top: 0, left: 0, right: 0, bottom: height, x: 0, y: 0, toJSON: () => ({}) };
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('collapses with a closed toggle when there is no room, and returns when room comes back', () => {
    render(<Harness />);
    expect(screen.getByRole('region')).toBeInTheDocument();
    setRoom(40);
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    const toggle = screen.getByRole('button', { name: 'Show legend' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    setRoom(400);
    expect(screen.getByRole('region')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide legend' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('opens over the table on request and Escape returns to collapsed with focus on the toggle', () => {
    render(<Harness />);
    setRoom(40);
    fireEvent.click(screen.getByRole('button', { name: 'Show legend' }));
    const panel = screen.getByRole('region');
    expect(panel.className).toContain('z-30');
    expect(screen.getByRole('button', { name: 'Hide legend' })).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(panel, { key: 'Escape' });
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show legend' })).toHaveFocus();
    // The reader's preference survives: room returning brings the legend back.
    setRoom(400);
    expect(screen.getByRole('region')).toBeInTheDocument();
  });

  it('ends the overlay by itself once there is room', () => {
    render(<Harness />);
    setRoom(40);
    fireEvent.click(screen.getByRole('button', { name: 'Show legend' }));
    setRoom(400);
    expect(screen.getByRole('region').className).not.toContain('z-30');
    // The earlier request doesn't carry over to the next squeeze.
    setRoom(40);
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });

  it('moves focus to the toggle when the legend collapses around it', () => {
    render(<Harness />);
    const row = screen.getByRole('region').querySelector('button')!;
    row.focus();
    setRoom(40);
    expect(screen.getByRole('button', { name: 'Show legend' })).toHaveFocus();
  });
});
