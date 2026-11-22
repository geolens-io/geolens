import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { render } from '@/test/test-utils';
import { ViewerBookmarksMenu } from '../ViewerBookmarks';

const map = { fitBounds: vi.fn(), getContainer: () => document.body } as unknown as MaplibreMap & {
  fitBounds: ReturnType<typeof vi.fn>;
};

describe('ViewerBookmarksMenu', () => {
  it('renders nothing without bookmarks', () => {
    render(<ViewerBookmarksMenu bookmarks={[]} getMap={() => map} />);
    expect(screen.queryByRole('button', { name: 'Bookmarks' })).not.toBeInTheDocument();
  });

  it('lists the names and moves the map to the one picked', async () => {
    const user = userEvent.setup();
    render(
      <ViewerBookmarksMenu
        bookmarks={[
          { name: 'Harbour', extent: [1, 2, 3, 4] },
          { name: 'Hills', extent: [5, 6, 7, 8] },
        ]}
        getMap={() => map}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Bookmarks' }));
    await user.click(screen.getByRole('menuitem', { name: 'Hills' }));
    expect(map.fitBounds).toHaveBeenCalledWith([[5, 6], [7, 8]], expect.objectContaining({ bearing: 0 }));
  });
});
