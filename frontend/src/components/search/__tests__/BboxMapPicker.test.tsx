import { render, screen } from '@/test/test-utils';
import { BboxMapPicker } from '../BboxMapPicker';

// test(#828): region-label coverage. The map canvas cannot carry an aria-label
// (@vis.gl/react-maplibre v8 drops it), so the wrapper role="region" label is
// the picker's only accessible name — a broken t() lookup would render an
// unlabeled region with no test noticing.

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mapgl">{children}</div>
  ),
}));

vi.mock('terra-draw', () => ({
  TerraDraw: vi.fn(() => ({
    start: vi.fn(),
    stop: vi.fn(),
    setMode: vi.fn(),
    on: vi.fn(),
    removeFeatures: vi.fn(),
    getSnapshotFeature: vi.fn(),
  })),
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
    expect(screen.getByText('Click and drag to draw a bounding box')).toBeInTheDocument();
  });
});
