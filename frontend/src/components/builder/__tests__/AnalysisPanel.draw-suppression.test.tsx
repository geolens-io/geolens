import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@/test/test-utils';
import { AnalysisPanel } from '../AnalysisPanel';
import { useMapDrawStore } from '@/stores/map-draw-store';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

/**
 * fix(#726): a clip-drawing vertex click also opened the clicked feature's
 * popup, so a five-point mask left five popups behind and the last one covered
 * the result.
 *
 * BuilderMap's click handler bails on `useMapDrawStore`'s `drawActive`, so what
 * has to hold is that AnalysisPanel raises that flag for exactly as long as a
 * draw mode is running. The lifecycle is the fragile part: `finish` drops
 * TerraDraw to static mode WITHOUT going through `stopDrawing`, which is why
 * the flag mirrors `isDrawing` from one effect rather than being set at each
 * call site.
 */

Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? _key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: () => true,
    permissions: { upload: true },
    isLoading: false,
  }),
}));

vi.mock('@/api/analysis', () => ({
  previewAnalysis: vi.fn(),
  materializeAnalysis: vi.fn(),
}));

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDataset: vi.fn(() => ({ data: { column_info: [] } })),
}));

// Captures the 'finish' handler so a completed polygon can be replayed without
// a real map. TerraDrawMapLibreGLAdapter needs a live GL context otherwise.
// vi.hoisted: the mock factories run at import time, before this file's own
// module-level bindings would be initialized.
const { finishRef, stopSpy, setModeSpy } = vi.hoisted(() => ({
  finishRef: { current: null as ((id: string | number) => void) | null },
  stopSpy: vi.fn(),
  setModeSpy: vi.fn(),
}));

vi.mock('terra-draw', () => ({
  TerraDraw: class {
    start = vi.fn();
    setMode = setModeSpy;
    stop = stopSpy;
    removeFeatures = vi.fn();
    getSnapshotFeature = () => ({
      geometry: {
        type: 'Polygon',
        coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
      },
    });
    on = (event: string, cb: (id: string | number) => void) => {
      if (event === 'finish') finishRef.current = cb;
    };
  },
  TerraDrawPolygonMode: class {},
}));

vi.mock('terra-draw-maplibre-gl-adapter', () => ({
  TerraDrawMapLibreGLAdapter: class {},
}));

const polygonLayer = {
  id: 'l1',
  dataset_id: 'ds1',
  dataset_name: 'Parcels',
  display_name: null,
  is_dem: false,
  dataset_geometry_type: 'MultiPolygon',
} as unknown as MapLayerResponse;

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  // startDrawing bails without a map; the adapter is mocked. on/off: the
  // finished polygon sets a mask, whose fix(#775) style.load subscription
  // attaches to the map.
  const mapInstanceRef = {
    current: { on: vi.fn(), off: vi.fn() } as unknown as MaplibreMap,
  };
  return render(
    <QueryClientProvider client={qc}>
      <AnalysisPanel layers={[polygonLayer]} mapInstanceRef={mapInstanceRef} />
    </QueryClientProvider>,
  );
}

/** Get to Clip and start the draw mode. */
async function startDrawing(user: ReturnType<typeof userEvent.setup>) {
  // Combobox order: layer, operation.
  await user.click(screen.getAllByRole('combobox')[1]);
  await user.click(await screen.findByRole('option', { name: 'Clip' }));
  await user.click(screen.getByRole('button', { name: 'Draw clip area' }));
}

beforeEach(() => {
  finishRef.current = null;
  stopSpy.mockClear();
  setModeSpy.mockClear();
  useMapDrawStore.setState({ drawActive: false });
});

describe('AnalysisPanel draw-mode pointer ownership (#726)', () => {
  it('is inactive before any drawing starts', () => {
    renderPanel();
    expect(useMapDrawStore.getState().drawActive).toBe(false);
  });

  it('claims the pointer while the clip mask is being drawn', async () => {
    const user = userEvent.setup();
    renderPanel();
    await startDrawing(user);
    expect(useMapDrawStore.getState().drawActive).toBe(true);
  });

  it('releases the pointer when the polygon is finished', async () => {
    const user = userEvent.setup();
    renderPanel();
    await startDrawing(user);
    expect(useMapDrawStore.getState().drawActive).toBe(true);

    // The regression that per-call-site updates would miss: finish keeps the
    // TerraDraw instance alive in static mode instead of calling stopDrawing,
    // so clicks must start resolving features again without a stop().
    act(() => finishRef.current?.('feature-1'));
    expect(setModeSpy).toHaveBeenCalledWith('static');
    expect(stopSpy).not.toHaveBeenCalled();
    expect(useMapDrawStore.getState().drawActive).toBe(false);
  });

  it('releases the pointer when drawing is cancelled', async () => {
    const user = userEvent.setup();
    renderPanel();
    await startDrawing(user);
    // By text, not role+name: the panel's <label for="analysis-clip-action">
    // gives every variant of that button the accessible name "Draw clip area".
    await user.click(screen.getByText('Cancel'));
    expect(useMapDrawStore.getState().drawActive).toBe(false);
  });

  it('releases the pointer when the panel unmounts mid-draw', async () => {
    const user = userEvent.setup();
    const { unmount } = renderPanel();
    await startDrawing(user);
    expect(useMapDrawStore.getState().drawActive).toBe(true);

    unmount();
    expect(useMapDrawStore.getState().drawActive).toBe(false);
  });
});
