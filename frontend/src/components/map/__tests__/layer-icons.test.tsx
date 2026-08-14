import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ColorizedGeometryIcon } from '../layer-icons';

// fix(#1494): a horizontal <line> has a zero-height bounding box, and the SVG
// spec disables rendering of any element painted by a bounding-box-united
// gradient when either bbox dimension is zero. The line icon's gradient must
// therefore declare userSpaceOnUse, or every multi-color line layer (banded
// categorical and graduated alike) renders a blank where its symbology
// belongs — in the builder layer list, the sidebar rail, and both legends.
describe('ColorizedGeometryIcon line gradients', () => {
  const bands = ['#9ca3af', '#60a5fa', '#facc15', '#fb923c'];

  it('paints multi-color line icons with a user-space gradient', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="MultiLineString"
        colors={bands}
        layerId="storm-tracks"
        discrete
      />,
    );

    const gradient = container.querySelector('linearGradient');
    expect(gradient).not.toBeNull();
    expect(gradient).toHaveAttribute('gradientUnits', 'userSpaceOnUse');

    const line = container.querySelector('line');
    expect(line).toHaveAttribute('stroke', `url(#${gradient!.id})`);
    // The gradient must span the stroke it paints, not default to a unit box.
    expect(gradient).toHaveAttribute('x1', line!.getAttribute('x1')!);
    expect(gradient).toHaveAttribute('x2', line!.getAttribute('x2')!);
  });

  it('keeps single-color line icons on a plain stroke with no gradient', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="LineString"
        colors={['#ef4444']}
        layerId="single"
      />,
    );

    expect(container.querySelector('linearGradient')).toBeNull();
    expect(container.querySelector('line')).toHaveAttribute('stroke', '#ef4444');
  });
});
