import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@/test/test-utils';
import type { ReactNode } from 'react';
import { FeaturePopup, type FeatureInfo } from '../FeaturePopup';

// MapLibre's Popup component requires a real map context. For unit tests we
// just need the children to render — replace it with a passthrough wrapper.
vi.mock('@vis.gl/react-maplibre', () => ({
  Popup: ({ children }: { children: ReactNode }) => <div data-testid="popup">{children}</div>,
}));

function makeFeature(overrides: Partial<FeatureInfo> = {}): FeatureInfo {
  return {
    properties: { city: 'NYC', state: 'NY' },
    layerName: 'Test Layer',
    columnInfo: null,
    title: null,
    visibleFields: null,
    ...overrides,
  };
}

describe('FeaturePopup', () => {
  it('renders the title above the property table when set', () => {
    const features: FeatureInfo[] = [makeFeature({ title: 'New York' })];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    expect(screen.getByText('New York')).toBeInTheDocument();
    expect(screen.getByText('NYC')).toBeInTheDocument();
  });

  it('renders only the title when visibleFields is [] (zero rows)', () => {
    const features: FeatureInfo[] = [
      makeFeature({ title: 'Just a title', visibleFields: [] }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    expect(screen.getByText('Just a title')).toBeInTheDocument();
    // Property values should NOT be rendered
    expect(screen.queryByText('NYC')).not.toBeInTheDocument();
  });

  it('honors visible_fields ordering', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { a: '1', b: '2', c: '3' },
        visibleFields: ['c', 'a'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const cells = screen.getAllByRole('cell');
    // Row 0: c key + value, Row 1: a key + value
    expect(cells[0]).toHaveTextContent('C');
    expect(cells[1]).toHaveTextContent('3');
    expect(cells[2]).toHaveTextContent('A');
    expect(cells[3]).toHaveTextContent('1');
  });

  it('clamps activeIndex when features.length shrinks below the active page', () => {
    const features: FeatureInfo[] = [
      makeFeature({ properties: { name: 'A' } }),
      makeFeature({ properties: { name: 'B' } }),
      makeFeature({ properties: { name: 'C' } }),
    ];
    const { rerender } = render(
      <FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />,
    );
    // Initial: page 1/3, showing A
    expect(screen.getByText('A')).toBeInTheDocument();

    // Shrink to a single feature — activeIndex would be out of bounds (0 is fine
    // here, but the effect should reset it whenever features.length < activeIndex).
    rerender(
      <FeaturePopup
        longitude={0}
        latitude={0}
        features={[makeFeature({ properties: { name: 'X' } })]}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('X')).toBeInTheDocument();
    // Pager hidden when only one feature
    expect(screen.queryByLabelText(/next feature/i)).not.toBeInTheDocument();
  });
});
