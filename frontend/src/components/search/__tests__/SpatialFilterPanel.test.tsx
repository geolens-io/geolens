import { render, screen } from '@/test/test-utils';
import { SpatialFilterPanel } from '../SpatialFilterPanel';

// test(#828): region-label coverage. The map canvas cannot carry an aria-label
// (@vis.gl/react-maplibre v8 drops it), so the wrapper role="region" label and
// the control labels are the only accessible names this panel has — a broken
// t() lookup would render an unlabeled region and empty buttons with no test
// noticing.

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
    addFeatures: vi.fn(() => []),
    removeFeatures: vi.fn(),
    getSnapshotFeature: vi.fn(),
  })),
  TerraDrawRectangleMode: vi.fn(),
  TerraDrawPolygonMode: vi.fn(),
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

function renderPanel() {
  return render(
    <SpatialFilterPanel
      open
      onClose={vi.fn()}
      onApply={vi.fn()}
    />,
  );
}

describe('SpatialFilterPanel — region and control labels (#828)', () => {
  it('labels the map wrapper region "Search area map"', () => {
    renderPanel();
    expect(screen.getByRole('region', { name: 'Search area map' })).toBeInTheDocument();
  });

  it('renders the sheet title and description', () => {
    renderPanel();
    expect(screen.getByText('Search area')).toBeInTheDocument();
    expect(
      screen.getByText('Draw a rectangle or polygon to limit search results to a specific area.'),
    ).toBeInTheDocument();
  });

  it('renders labeled Rectangle and Polygon draw-mode toggles', () => {
    renderPanel();
    // Radix single-select ToggleGroup items expose role="radio".
    expect(screen.getByRole('radio', { name: 'Rectangle' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Polygon' })).toBeInTheDocument();
  });

  it('renders labeled Intersects and Within predicate toggles', () => {
    renderPanel();
    expect(screen.getByRole('radio', { name: 'Intersects' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Within' })).toBeInTheDocument();
  });

  it('renders the labeled Close, Use current map extent, and Apply controls', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use current map extent' })).toBeInTheDocument();
    // No area drawn yet — Apply is present but disabled.
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
  });

  it('shows the rectangle draw instruction before an area is drawn', () => {
    renderPanel();
    expect(screen.getByText('Click and drag to draw a bounding box')).toBeInTheDocument();
  });

  it('every button and toggle in the panel has a non-empty accessible name', () => {
    renderPanel();
    // The regression this guards: a broken label lookup renders empty buttons.
    for (const el of [...screen.getAllByRole('button'), ...screen.getAllByRole('radio')]) {
      expect(el).toHaveAccessibleName();
    }
  });
});
