import { render, waitFor, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  controls: [] as { setProps: ReturnType<typeof vi.fn>; getCanvas: () => HTMLCanvasElement }[],
  canvas: null as unknown as HTMLCanvasElement,
  createLayers: vi.fn(() => ['layer']),
}));

vi.mock('@deck.gl/maplibre', () => ({ MapLibreOverlay: class {} }));
vi.mock('@vis.gl/react-maplibre', async () => {
  const react = await import('react');
  return {
    useMap: () => ({ current: { getMap: () => ({ easeTo: vi.fn() }) } }),
    useControl: (factory: () => unknown) => {
      factory();
      return react.useMemo(() => {
        const control = { setProps: vi.fn(), getCanvas: () => h.canvas };
        h.controls.push(control);
        return control;
      }, []);
    },
  };
});
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../tileset-layers', () => ({ createTilesetLayers: h.createLayers }));

import Dataset3DOverlay from '../Dataset3DOverlay';

describe('Dataset3DOverlay', () => {
  beforeEach(() => {
    h.controls.length = 0;
    h.createLayers.mockClear();
    h.canvas = document.createElement('canvas');
  });

  it('builds the layer once per tileset URL, not when the extent decision changes', async () => {
    const { rerender } = render(<Dataset3DOverlay datasetId="d1" tilesetUrl="/u" fitToTileset={false} />);
    await waitFor(() => expect(h.createLayers).toHaveBeenCalledTimes(1));
    rerender(<Dataset3DOverlay datasetId="d1" tilesetUrl="/u" fitToTileset />);
    await new Promise((r) => setTimeout(r, 20));
    expect(h.createLayers).toHaveBeenCalledTimes(1);
    expect(h.controls[0].setProps).toHaveBeenCalledWith({ layers: ['layer'] });
  });

  it('remounts the overlay when its canvas context is restored', async () => {
    render(<Dataset3DOverlay datasetId="d1" tilesetUrl="/u" fitToTileset={false} />);
    await waitFor(() => expect(h.createLayers).toHaveBeenCalledTimes(1));
    const lost = new Event('webglcontextlost', { cancelable: true });
    h.canvas.dispatchEvent(lost);
    expect(lost.defaultPrevented).toBe(true);
    act(() => {
      h.canvas.dispatchEvent(new Event('webglcontextrestored'));
    });
    await waitFor(() => expect(h.createLayers).toHaveBeenCalledTimes(2));
    expect(h.controls).toHaveLength(2);
  });
});
