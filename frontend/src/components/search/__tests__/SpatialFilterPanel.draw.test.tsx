import { useEffect } from 'react';
import { render } from '@/test/test-utils';
import { TerraDrawRectangleMode } from 'terra-draw';
import { SpatialFilterPanel } from '../SpatialFilterPanel';

const draw = vi.hoisted(() => ({ handlers: {} as Record<string, (id: string) => void> }));

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ onLoad }: { onLoad?: (e: { target: unknown }) => void }) => {
    useEffect(() => {
      onLoad?.({ target: {} });
    }, [onLoad]);
    return <div data-testid="mapgl" />;
  },
}));

vi.mock('terra-draw', () => ({
  TerraDraw: vi.fn(function () {
    return {
    start: vi.fn(),
    stop: vi.fn(),
    setMode: vi.fn(),
    on: vi.fn((event: string, handler: (id: string) => void) => {
      draw.handlers[event] = handler;
    }),
    addFeatures: vi.fn(() => []),
    removeFeatures: vi.fn(),
    getSnapshotFeature: vi.fn(() => ({
      geometry: {
        type: 'Polygon',
        coordinates: [[[144.408, 72.18], [198.548, 72.18], [198.548, 81.41], [144.408, 81.41], [144.408, 72.18]]],
      },
    })),
    };
  }),
  TerraDrawRectangleMode: vi.fn(),
  TerraDrawPolygonMode: vi.fn(),
}));
vi.mock('terra-draw-maplibre-gl-adapter', () => ({ TerraDrawMapLibreGLAdapter: vi.fn() }));
vi.mock('@/components/theme-provider', () => ({ useTheme: () => ({ resolvedTheme: 'light' }) }));
vi.mock('@/hooks/use-settings', () => ({ useBasemaps: () => ({ data: [] }) }));

describe('SpatialFilterPanel drawing', () => {
  it('lets the rectangle be drawn by click-move or by dragging', () => {
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} />);
    expect(TerraDrawRectangleMode).toHaveBeenCalledWith(
      expect.objectContaining({ drawInteraction: 'click-move-or-drag' }),
    );
  });
});
