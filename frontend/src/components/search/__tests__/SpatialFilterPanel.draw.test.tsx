import { act, useEffect } from 'react';
import { fireEvent, render, screen } from '@/test/test-utils';
import { TerraDrawRectangleMode } from 'terra-draw';
import { SpatialFilterPanel, bboxToRings, normalizeBboxLongitudes } from '../SpatialFilterPanel';

const ACROSS_SEAM = [[144.408, 72.18], [198.548, 72.18], [198.548, 81.41], [144.408, 81.41], [144.408, 72.18]];
const draw = vi.hoisted(() => ({
  handlers: {} as Record<string, (id: string) => void>,
  ring: [] as number[][],
  removeFeatures: undefined as unknown as ReturnType<typeof vi.fn>,
  addFeatures: undefined as unknown as ReturnType<typeof vi.fn>,
  addResult: [{ id: 'restored', valid: true }] as Array<{ id?: string; valid: boolean }>,
  fitBounds: vi.fn(),
}));

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ onLoad }: { onLoad?: (e: { target: unknown }) => void }) => {
    useEffect(() => {
      onLoad?.({
        target: {
          fitBounds: draw.fitBounds,
          getBounds: () => ({ getWest: () => -234.5, getSouth: () => -10.123456789012, getEast: () => 20, getNorth: () => 40 }),
        },
      });
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
    addFeatures: (draw.addFeatures = vi.fn(() => draw.addResult)),
    removeFeatures: (draw.removeFeatures = vi.fn()),
    getSnapshotFeature: vi.fn(() => ({
      geometry: { type: 'Polygon', coordinates: [draw.ring] },
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
  beforeEach(() => {
    draw.ring = ACROSS_SEAM;
    draw.addResult = [{ id: 'restored', valid: true }];
    draw.fitBounds.mockClear();
  });

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

describe('SpatialFilterPanel restoring a stored area', () => {
  it('draws the stored box as a registered rectangle and shows it', () => {
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} initialBbox="-60.46,9.82,-26.71,29.56" />);
    const [[feature]] = draw.addFeatures.mock.calls[0] as [[{ id: string; properties: { mode: string } }]];
    expect(feature.properties.mode).toBe('rectangle');
    expect(typeof feature.id).toBe('string');
    expect(screen.getByText('Bbox: -60.46, 9.82, -26.71, 29.56')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled();
    expect(draw.fitBounds).toHaveBeenCalled();
  });

  it('keeps the stored area as the pending filter even when Terra Draw rejects the drawing', () => {
    draw.addResult = [{ valid: false }];
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} initialBbox="-60.46,9.82,-26.71,29.56" />);
    expect(screen.getByText('Bbox: -60.46, 9.82, -26.71, 29.56')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled();
  });

  it('draws a box across the antimeridian as two halves inside +/-180', () => {
    draw.addResult = [{ id: 'a', valid: true }, { id: 'b', valid: true }];
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} initialBbox="172.45,9.82,-137.92,32.2" />);
    const [features] = draw.addFeatures.mock.calls[0] as [Array<{ geometry: { coordinates: number[][][] } }>];
    const spans = features.map((f) => {
      const lngs = f.geometry.coordinates[0].map(([lng]) => lng);
      return [Math.min(...lngs), Math.max(...lngs)];
    });
    expect(spans).toEqual([[172.45, 180], [-180, -137.92]]);
  });

  it('draws the current map extent normalized and rounded to what Terra Draw accepts', () => {
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Use current map extent' }));
    expect(screen.getByText('Bbox: 125.50, -10.12, 20.00, 40.00')).toBeInTheDocument();
    const [features] = draw.addFeatures.mock.calls[0] as [Array<{ geometry: { coordinates: number[][][] } }>];
    for (const f of features) {
      for (const [lng, lat] of f.geometry.coordinates[0]) {
        expect(Math.abs(lng)).toBeLessThanOrEqual(180);
        expect(String(lat).split('.')[1]?.length ?? 0).toBeLessThanOrEqual(9);
      }
    }
  });
});

describe('bboxToRings', () => {
  it('rounds coordinates to nine decimals', () => {
    const [ring] = bboxToRings('-47.37000000000001,20.1234567891234,41.06,30');
    expect(ring[0]).toEqual([-47.37, 20.123456789]);
  });
});

describe('SpatialFilterPanel bbox label', () => {
  it('shows longitudes inside +/-180 for a box drawn across the antimeridian', () => {
    draw.ring = ACROSS_SEAM;
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} />);
    act(() => draw.handlers.finish('seam'));
    expect(screen.getByText('Bbox: 144.41, 72.18, -161.45, 81.41')).toBeInTheDocument();
  });
});

describe('SpatialFilterPanel zero-area boxes', () => {
  it('discards a rectangle with no height and keeps Apply disabled', () => {
    draw.ring = [[-47.37, 20], [41.06, 20], [41.06, 20], [-47.37, 20], [-47.37, 20]];
    render(<SpatialFilterPanel open onClose={vi.fn()} onApply={vi.fn()} />);
    act(() => draw.handlers.finish('flat'));
    expect(draw.removeFeatures).toHaveBeenCalledWith(['flat']);
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(screen.queryByText(/Bbox:/)).not.toBeInTheDocument();
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
