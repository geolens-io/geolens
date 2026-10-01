import { act, useEffect } from 'react';
import { fireEvent, render, screen } from '@/test/test-utils';
import { TerraDrawRectangleMode } from 'terra-draw';
import { SpatialFilterPanel, normalizeBboxLongitudes } from '../SpatialFilterPanel';

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
  it('keeps the default click-then-click rectangle so dragging still pans, and says so', () => {
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} />);
    const options = vi.mocked(TerraDrawRectangleMode).mock.calls[0][0] as { drawInteraction?: string };
    expect(options.drawInteraction ?? 'click-move').toBe('click-move');
    expect(screen.getByText('Click to start the box, then click again to finish it')).toBeInTheDocument();
  });

  it('applies a box drawn across the antimeridian with longitudes inside +/-180', () => {
    const onApply = vi.fn();
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={onApply} />);
    act(() => draw.handlers.finish('feature-1'));
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledWith('144.408,72.18,-161.452,81.41', expect.any(String), undefined);
  });
});

describe('normalizeBboxLongitudes', () => {
  it.each([
    ['-10,1,20,2', '-10,1,20,2'],
    ['170,1,180,2', '170,1,180,2'],
    ['-200,1,-170,2', '160,1,-170,2'],
    ['-400,1,400,2', '-180,1,180,2'],
  ])('%s -> %s', (input, expected) => {
    expect(normalizeBboxLongitudes(input)).toBe(expected);
  });
});
