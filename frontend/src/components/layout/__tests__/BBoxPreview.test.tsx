import { render } from '@/test/test-utils';
import { BBoxPreview } from '../BBoxPreview';

/** The extent rects, i.e. everything except the world outline. */
function extentRects(container: HTMLElement): SVGRectElement[] {
  return Array.from(container.querySelectorAll('rect')).filter(
    (rect) => rect.getAttribute('width') !== '360',
  );
}

describe('BBoxPreview', () => {
  it('draws one rect for a normal extent', () => {
    const { container } = render(<BBoxPreview bbox={[-74.5, 40.5, -73.5, 41.5]} />);

    const rects = extentRects(container);
    expect(rects).toHaveLength(1);
    expect(rects[0].getAttribute('x')).toBe('105.5');
    expect(rects[0].getAttribute('width')).toBe('2'); // 1° clamped to the 2 minimum
  });

  // fix(#903): the file already detected a crossing extent for the viewBox, but
  // still drew one rect from `maxx - minx` — negative, so it collapsed into a
  // sliver pinned at the east edge instead of showing where the data is.
  it('draws both seam halves for an antimeridian-crossing extent', () => {
    const { container } = render(<BBoxPreview bbox={[178.5, -20, -178.5, -15]} />);

    const rects = extentRects(container);
    expect(rects).toHaveLength(2);
    // West half runs up to the seam at x = 360; east half starts at x = 0.
    expect(rects[0].getAttribute('x')).toBe('358.5');
    expect(rects[1].getAttribute('x')).toBe('0');
    expect(rects.every((rect) => Number(rect.getAttribute('width')) > 0)).toBe(true);
  });

  it('renders the empty state without a bbox', () => {
    const { container } = render(<BBoxPreview bbox={null} />);

    expect(container.querySelector('svg')).toBeNull();
  });
});
