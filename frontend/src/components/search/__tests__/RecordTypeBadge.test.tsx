// A 3D Tiles record gets its own labelled, coloured badge; an unknown type gets none.
import { render, screen } from '@/test/test-utils';
import { RecordTypeBadge } from '../RecordTypeBadge';

describe('RecordTypeBadge', () => {
  it('labels a tiles3d_dataset record as 3D Tiles in the tiles3d colours', () => {
    render(<RecordTypeBadge recordType="tiles3d_dataset" />);

    const badge = screen.getByText('3D Tiles');
    expect(badge).toHaveClass('text-type-tiles3d', 'bg-type-tiles3d-bg');
  });

  it('renders nothing for a record type it does not know', () => {
    const { container } = render(<RecordTypeBadge recordType="point_cloud_dataset" />);

    expect(container).toBeEmptyDOMElement();
  });
});
