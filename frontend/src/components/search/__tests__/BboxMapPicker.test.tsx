import { useEffect } from 'react';
import { act, render, screen } from '@/test/test-utils';
import { changeTestLanguage } from '@/test/i18n';
import { BboxMapPicker } from '../BboxMapPicker';

// test(#828): region-label coverage. The map canvas cannot carry an aria-label
// (@vis.gl/react-maplibre v8 drops it), so the wrapper role="region" label is
// the picker's only accessible name — a broken t() lookup would render an
// unlabeled region with no test noticing.

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ children, onLoad, locale }: { children?: React.ReactNode; onLoad?: (e: { target: unknown }) => void; locale?: Record<string, string> }) => {
    useEffect(() => {
      onLoad?.({ target: {} });
    }, [onLoad]);
    return <div data-testid="mapgl" data-locale={JSON.stringify(locale ?? null)}>{children}</div>;
  },
}));

const draw = vi.hoisted(() => ({
  finish: undefined as undefined | ((id: string) => void),
  ring: [] as number[][],
}));

vi.mock('terra-draw', () => ({
  TerraDraw: vi.fn(function () {
    return {
      start: vi.fn(),
      stop: vi.fn(),
      setMode: vi.fn(),
      on: vi.fn((_event: string, handler: (id: string) => void) => {
        draw.finish = handler;
      }),
      removeFeatures: vi.fn(),
      getSnapshotFeature: vi.fn(() => ({ geometry: { type: 'Polygon', coordinates: [draw.ring] } })),
    };
  }),
  TerraDrawRectangleMode: vi.fn(),
}));

vi.mock('terra-draw-maplibre-gl-adapter', () => ({
  TerraDrawMapLibreGLAdapter: vi.fn(),
}));

vi.mock('@/components/theme-provider', () => ({
  useTheme: () => ({ resolvedTheme: 'light' }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
}));

describe('BboxMapPicker — region label (#828)', () => {
  it('labels the map wrapper region "Bounding box map"', () => {
    render(<BboxMapPicker onBboxSelected={vi.fn()} />);
    expect(screen.getByRole('region', { name: 'Bounding box map' })).toBeInTheDocument();
  });

  it('shows the localized draw instruction', () => {
    render(<BboxMapPicker onBboxSelected={vi.fn()} />);
    expect(screen.getByText('Click to start the box, then click again to finish it')).toBeInTheDocument();
  });
});

describe('BboxMapPicker — antimeridian', () => {
  it('reports a box drawn across the seam with west > east and both inside +/-180', () => {
    draw.ring = [[172.45, 9.82], [222.08, 9.82], [222.08, 32.2], [172.45, 32.2], [172.45, 9.82]];
    const onBboxSelected = vi.fn();
    render(<BboxMapPicker onBboxSelected={onBboxSelected} />);
    act(() => draw.finish?.('box'));
    expect(onBboxSelected).toHaveBeenCalledWith('172.45,9.82,-137.92,32.2');
  });
});

describe('BboxMapPicker — map locale', () => {
  afterEach(async () => {
    await act(() => changeTestLanguage('en'));
  });

  it('gives the map control strings in the interface language', async () => {
    await act(() => changeTestLanguage('fr'));
    render(<BboxMapPicker onBboxSelected={vi.fn()} />);
    const locale = JSON.parse(screen.getByTestId('mapgl').dataset.locale ?? 'null');
    expect(locale['NavigationControl.ZoomIn']).toBe('Zoom avant');
  });
});
