import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
  opacity: 1,
  paint: { 'circle-color': '#0077cc' },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '/tiles/test/{z}/{x}/{y}.pbf',
} as SharedLayerResponse;

function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <LayerLegend
      layers={[LAYER]}
      visibleLayers={new Set(['layer-1'])}
      onToggleVisibility={vi.fn()}
      isOpen={open}
      onToggle={() => setOpen((v) => !v)}
    />
  );
}

describe('LayerLegend Escape', () => {
  it('closes the panel and returns focus to the toggle', () => {
    render(<Harness />);
    const eye = screen.getByRole('button', { name: /Hide Test Layer/ });
    eye.focus();

    fireEvent.keyDown(eye, { key: 'Escape' });

    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /legend/i }));
  });

  it('marks the event handled so document-level Escape handlers skip it', () => {
    const outer = vi.fn();
    const onDocument = (e: KeyboardEvent) => {
      if (!e.defaultPrevented) outer();
    };
    document.addEventListener('keydown', onDocument);
    try {
      render(<Harness />);
      fireEvent.keyDown(screen.getByRole('button', { name: /Hide Test Layer/ }), { key: 'Escape' });
      expect(outer).not.toHaveBeenCalled();
    } finally {
      document.removeEventListener('keydown', onDocument);
    }
  });

  it('does not close on Escape pressed elsewhere on the page', () => {
    render(<Harness />);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.getByRole('region')).toBeInTheDocument();
  });
});
