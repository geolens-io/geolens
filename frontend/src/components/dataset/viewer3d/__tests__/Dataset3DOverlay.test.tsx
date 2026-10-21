import { render, waitFor, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

interface FakeOverlay {
  props: { onDeviceInitialized: (device: unknown) => void };
  setProps: ReturnType<typeof vi.fn>;
}

const h = vi.hoisted(() => ({
  controls: [] as FakeOverlay[],
  canvas: null as unknown as HTMLCanvasElement,
  createLayers: vi.fn(() => ['layer']),
}));

vi.mock('@deck.gl/maplibre', () => ({
  MapLibreOverlay: class {
    setProps = vi.fn();
    props: FakeOverlay['props'];
    constructor(props: FakeOverlay['props']) {
      this.props = props;
    }
  },
}));
vi.mock('@vis.gl/react-maplibre', async () => {
  const react = await import('react');
  return {
    useMap: () => ({ current: { getMap: () => ({ easeTo: vi.fn() }) } }),
    useControl: (factory: () => FakeOverlay) =>
      react.useMemo(() => {
        const control = factory();
        h.controls.push(control);
        return control;
      }, []),
  };
});
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../tileset-layers', () => ({ createTilesetLayers: h.createLayers }));
const loadPointCloud = vi.hoisted(() => vi.fn());
vi.mock('../pointcloud-layers', () => ({ loadPointCloud }));

import Dataset3DOverlay from '../Dataset3DOverlay';

describe('Dataset3DOverlay', () => {
  beforeEach(() => {
    h.controls.length = 0;
    h.createLayers.mockClear();
    h.canvas = document.createElement('canvas');
  });

  it('builds the layer once per tileset URL, not when the extent decision changes', async () => {
    const { rerender } = render(<Dataset3DOverlay datasetId="d1" source={{ kind: 'tileset', url: '/u' }} fitToData={false} />);
    await waitFor(() => expect(h.createLayers).toHaveBeenCalledTimes(1));
    rerender(<Dataset3DOverlay datasetId="d1" source={{ kind: 'tileset', url: '/u' }} fitToData />);
    await new Promise((r) => setTimeout(r, 20));
    expect(h.createLayers).toHaveBeenCalledTimes(1);
    expect(h.controls[0].setProps).toHaveBeenCalledWith({ layers: ['layer'] });
  });

  it('remounts the overlay when its canvas context is restored, even if the canvas arrives late', async () => {
    render(<Dataset3DOverlay datasetId="d1" source={{ kind: 'tileset', url: '/u' }} fitToData={false} />);
    await waitFor(() => expect(h.createLayers).toHaveBeenCalledTimes(1));
    // Deck reports its device after mount; no rerender follows.
    h.controls[0].props.onDeviceInitialized({ getDefaultCanvasContext: () => ({ canvas: h.canvas }) });
    const lost = new Event('webglcontextlost', { cancelable: true });
    h.canvas.dispatchEvent(lost);
    expect(lost.defaultPrevented).toBe(true);
    act(() => {
      h.canvas.dispatchEvent(new Event('webglcontextrestored'));
    });
    await waitFor(() => expect(h.createLayers).toHaveBeenCalledTimes(2));
    expect(h.controls).toHaveLength(2);
  });

  it('loads a point cloud instead of a tileset, adds layers as nodes arrive, and stops the load on unmount', async () => {
    const stop = vi.fn();
    loadPointCloud.mockReturnValue(stop);
    const { unmount } = render(
      <Dataset3DOverlay
        datasetId="d1"
        source={{ kind: 'pointcloud', url: '/api/datasets/d1/copc/a/data.copc.laz', sizeBytes: 99 }}
        fitToData={false}
      />,
    );
    await waitFor(() => expect(loadPointCloud).toHaveBeenCalledTimes(1));
    expect(h.createLayers).not.toHaveBeenCalled();
    const [url, size, , handlers] = loadPointCloud.mock.calls[0];
    expect([url, size]).toEqual(['/api/datasets/d1/copc/a/data.copc.laz', 99]);
    handlers.onLayer('a');
    handlers.onLayer('b');
    expect(h.controls[0].setProps).toHaveBeenLastCalledWith({ layers: ['a', 'b'] });
    unmount();
    expect(stop).toHaveBeenCalled();
  });
});
