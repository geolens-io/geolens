import { useState } from 'react';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { render } from '@/test/test-utils';
import type { MapBookmark } from '@/types/api';
import { BookmarksPanel } from '../BookmarksPanel';

function stubMap() {
  return {
    getCenter: () => ({ lng: 10, lat: 20 }),
    getZoom: () => 4,
    getBearing: () => 0,
    getPitch: () => 0,
    getContainer: () => ({ clientWidth: 1000, clientHeight: 500 }),
    fitBounds: vi.fn(),
    cameraForBounds: () => ({ zoom: 4 }),
  } as unknown as MaplibreMap & { fitBounds: ReturnType<typeof vi.fn> };
}

const bm = (name: string): MapBookmark => ({ name, extent: [0, 0, 1, 1] });

function Harness({ initial, map, onChange }: { initial: MapBookmark[]; map: MaplibreMap | null; onChange?: (b: MapBookmark[]) => void }) {
  const [bookmarks, setBookmarks] = useState(initial);
  return (
    <BookmarksPanel
      bookmarks={bookmarks}
      map={map}
      onChange={(next) => {
        setBookmarks(next);
        onChange?.(next);
      }}
    />
  );
}

describe('BookmarksPanel', () => {
  it('says what bookmarks are for when there are none', () => {
    render(<Harness initial={[]} map={stubMap()} />);
    expect(screen.getByText(/save a map view/i)).toBeInTheDocument();
  });

  it('adds the current view as a numbered bookmark and focuses its name', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={[bm('First')]} map={stubMap()} onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Add current view' }));
    expect(onChange.mock.lastCall![0].map((b: MapBookmark) => b.name)).toEqual(['First', 'Bookmark 2']);
    const input = screen.getByLabelText('Name of bookmark 2') as HTMLInputElement;
    expect(input).toHaveFocus();
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe('Bookmark 2'.length);
  });

  it('disables adding without a map and names the reason', () => {
    render(<Harness initial={[]} map={null} />);
    const add = screen.getByRole('button', { name: 'Add current view' });
    expect(add).toBeDisabled();
    expect(add).toHaveAccessibleDescription('The map is not ready yet.');
  });

  it('stops adding at 100 bookmarks', () => {
    const many = Array.from({ length: 100 }, (_, i) => bm(`B${i}`));
    render(<Harness initial={many} map={stubMap()} />);
    const add = screen.getByRole('button', { name: 'Add current view' });
    expect(add).toBeDisabled();
    expect(add).toHaveAccessibleDescription(/up to 100/);
  });

  it('passes a name on as it is typed, so a save from the keyboard carries it', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={[bm('Alpha')]} map={stubMap()} onChange={onChange} />);
    const input = screen.getByLabelText('Name of bookmark 1');
    await user.type(input, 'bet');
    expect(input).toHaveFocus();
    expect(onChange.mock.lastCall![0][0].name).toBe('Alphabet');
  });

  it('puts back the name the field had when a name typed down to nothing is left blank', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={[bm('Abc')]} map={stubMap()} onChange={onChange} />);
    const input = screen.getByLabelText('Name of bookmark 1');
    await user.type(input, '{Backspace}{Backspace}{Backspace}');
    expect(onChange.mock.lastCall![0][0].name).toBe('A');
    await user.tab();
    expect(onChange.mock.lastCall![0][0].name).toBe('Abc');
    expect(screen.getByLabelText('Name of bookmark 1')).toHaveValue('Abc');
  });

  it('renames, trims on blur and puts the old name back for a blank one', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={[bm('Alpha')]} map={stubMap()} onChange={onChange} />);
    const input = screen.getByLabelText('Name of bookmark 1');
    await user.clear(input);
    await user.type(input, '  Beta  ');
    await user.tab();
    expect(onChange.mock.lastCall![0][0].name).toBe('Beta');
    expect(screen.getByLabelText('Name of bookmark 1')).toHaveValue('Beta');

    onChange.mockClear();
    await user.clear(screen.getByLabelText('Name of bookmark 1'));
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Name of bookmark 1')).toHaveValue('Beta');
  });

  it('reorders by keyboard and keeps focus on the moved row', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={[bm('A'), bm('B'), bm('C')]} map={stubMap()} onChange={onChange} />);
    expect(screen.getByRole('button', { name: 'Move A up' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Move C down' })).toBeDisabled();

    screen.getByRole('button', { name: 'Move C up' }).focus();
    await user.keyboard('{Enter}');
    expect(onChange.mock.lastCall![0].map((b: MapBookmark) => b.name)).toEqual(['A', 'C', 'B']);
    expect(screen.getByRole('button', { name: 'Move C up' })).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(onChange.mock.lastCall![0].map((b: MapBookmark) => b.name)).toEqual(['C', 'A', 'B']);
    // At the top its up button is disabled, so focus falls to the down button.
    expect(screen.getByRole('button', { name: 'Move C down' })).toHaveFocus();
  });

  it('deletes and moves focus to the next row, or the add button after the last', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={[bm('A'), bm('B')]} map={stubMap()} onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Delete A' }));
    expect(onChange.mock.lastCall![0].map((b: MapBookmark) => b.name)).toEqual(['B']);
    await user.click(screen.getByRole('button', { name: 'Delete B' }));
    expect(screen.getByRole('button', { name: 'Add current view' })).toHaveFocus();
  });

  it('goes to a bookmark', async () => {
    const user = userEvent.setup();
    const map = stubMap();
    render(<Harness initial={[bm('A')]} map={map} />);
    await user.click(screen.getByRole('button', { name: 'Go to A' }));
    expect(map.fitBounds).toHaveBeenCalledOnce();
  });
});
