import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render as renderWithProviders } from '@/test/test-utils';
import { isListableColumn, isSortableColumn } from '@/lib/column-utils';
import FeatureListEditor from '../feature-list/FeatureListEditor';
import { featureListWidget, type FeatureListConfig } from '../feature-list/definition';
import FeatureListRenderer from '../feature-list/FeatureListRenderer';
import { FeatureListFallback } from '../feature-list/FeatureListFallback';
import { parseStoredWidget } from '../registry';

const config: FeatureListConfig = {
  title_column: 'name',
  subtitle_column: 'kind',
  sort_column: 'name',
  sort: 'asc',
  page_size: 25,
};

function rowsResult(rows: unknown[], hasMore = false) {
  return {
    op: 'rows',
    approximate: false,
    cached: false,
    result: { rows, next_cursor: hasMore ? 'next' : null, has_more: hasMore },
  };
}

const mapped = rowsResult(
  [
    { gid: 7, values: { name: 'Elm Park', kind: 'park' }, bbox: [-74, 40, -73.9, 40.1] },
    { gid: 8, values: { name: 'Pier 9', kind: null }, bbox: [-74.01, 40.7, -74.01, 40.7] },
    { gid: 9, values: { name: 'Unplaced', kind: 'park' }, bbox: null },
  ],
  true,
);

describe('feature list config', () => {
  it('reads the stored shape and fills the defaults', () => {
    expect(featureListWidget.parseConfig(config, 1)).toEqual(config);
    expect(featureListWidget.parseConfig({ title_column: 'name' }, 1)).toEqual({
      title_column: 'name',
      subtitle_column: null,
      sort_column: null,
      sort: 'asc',
      page_size: 25,
    });
  });

  it('refuses what the server refuses', () => {
    for (const bad of [
      {},
      { ...config, title_column: '' },
      { ...config, title_column: 'x'.repeat(64) },
      { ...config, subtitle_column: 3 },
      { ...config, sort: 'up' },
      { ...config, page_size: 9 },
      { ...config, page_size: 101 },
      { ...config, page_size: 12.5 },
      { ...config, extra: 1 },
    ]) {
      expect(featureListWidget.parseConfig(bad, 1)).toBeNull();
    }
  });

  it('is a dashboard widget that needs a layer', () => {
    const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
    const layer_id = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
    const widget = { id, type: 'feature_list', v: 1, layer_id, config };
    expect(parseStoredWidget(widget, 'dashboard')).toMatchObject({ ok: true });
    expect(parseStoredWidget({ ...widget, layer_id: undefined }, 'dashboard')).toMatchObject({ ok: false });
    expect(parseStoredWidget(widget, 'story')).toMatchObject({ ok: false });
  });

  it('starts a new list on a text column that is not an identifier', () => {
    const columns = [
      { name: 'gid', type: 'integer' },
      { name: 'parcel_id', type: 'text' },
      { name: 'name', type: 'text' },
    ];
    expect(featureListWidget.initialConfig?.(columns)).toEqual({ title_column: 'name' });
  });
});

describe('feature list request', () => {
  it('asks for one page of the title, subtitle and sort columns once each', () => {
    expect(featureListWidget.dataRequest!(config)).toEqual({
      op: 'rows',
      columns: ['name', 'kind'],
      sort_column: 'name',
      sort: 'asc',
      limit: 25,
    });
    expect(
      featureListWidget.dataRequest!({ ...config, subtitle_column: null, sort_column: 'built', sort: 'desc', page_size: 10 }),
    ).toEqual({ op: 'rows', columns: ['name', 'built'], sort_column: 'built', sort: 'desc', limit: 10 });
    expect(featureListWidget.dataRequest!({ ...config, subtitle_column: null, sort_column: null })).toEqual({
      op: 'rows',
      columns: ['name'],
      sort: 'asc',
      limit: 25,
    });
  });

  it('names the columns it reads so the Builder can check them', () => {
    expect(featureListWidget.readsColumns!(config)).toEqual([
      { name: 'name', numeric: false, listable: true },
      { name: 'kind', numeric: false, listable: true },
      { name: 'name', numeric: false, sortable: true },
    ]);
  });
});

describe('feature list renderer', () => {
  it('shows a blank title as no value', () => {
    const blank = rowsResult([{ gid: 1, values: { name: '', kind: 'park' }, bbox: null }]);
    render(<FeatureListRenderer config={config} data={blank} onZoomTo={vi.fn()} onLoadMore={vi.fn()} />);
    expect(screen.getByText('(no value)')).toBeInTheDocument();
  });

  it('lists titles with subtitles and says more is available', () => {
    render(<FeatureListRenderer config={config} data={mapped} onZoomTo={vi.fn()} onLoadMore={vi.fn()} />);
    expect(screen.getByRole('list', { name: 'Features' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByText('Elm Park')).toBeInTheDocument();
    expect(screen.getAllByText('park')).toHaveLength(2);
    expect(screen.getByText('(no value)')).toBeInTheDocument();
    expect(screen.getByText('3 features shown, more available')).toBeInTheDocument();
  });

  it('zooms to a feature with its id and bounds when its row is clicked', async () => {
    const onZoomTo = vi.fn();
    render(<FeatureListRenderer config={config} data={mapped} onZoomTo={onZoomTo} />);
    await userEvent.click(screen.getByRole('button', { name: /Elm Park/ }));
    expect(onZoomTo).toHaveBeenCalledWith({ id: 7, bbox: [-74, 40, -73.9, 40.1] });
  });

  it('is reachable and operable from the keyboard', async () => {
    const onZoomTo = vi.fn();
    render(<FeatureListRenderer config={config} data={mapped} onZoomTo={onZoomTo} />);
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole('button', { name: /Elm Park/ })).toHaveFocus();
    await user.keyboard('{Enter}');
    await user.tab();
    await user.keyboard(' ');
    expect(onZoomTo.mock.calls.map(([feature]) => feature.id)).toEqual([7, 8]);
  });

  it('leaves a feature with no shape as plain text', () => {
    render(<FeatureListRenderer config={config} data={mapped} onZoomTo={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Unplaced/ })).not.toBeInTheDocument();
    expect(screen.getByText('Unplaced')).toBeInTheDocument();
  });

  it('makes the list a focusable named region when its rows are plain text, so the keyboard can scroll it', async () => {
    const table = rowsResult([{ gid: 1, values: { name: 'Row one', kind: 'a' } }]);
    const { rerender } = render(<FeatureListRenderer config={config} data={table} onZoomTo={vi.fn()} />);
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole('list', { name: 'Features' })).toHaveFocus();

    rerender(<FeatureListRenderer config={config} data={mapped} mapHidden />);
    expect(screen.getByRole('list', { name: 'Features' })).toHaveAttribute('tabindex', '0');

    // With buttons in it, the buttons are the tab stops.
    rerender(<FeatureListRenderer config={config} data={mapped} onZoomTo={vi.fn()} />);
    expect(screen.getByRole('list', { name: 'Features' })).not.toHaveAttribute('tabindex');
  });

  it('lists a layer with no geometry whole and offers no zoom', () => {
    const table = rowsResult([
      { gid: 1, values: { name: 'Row one', kind: 'a' } },
      { gid: 2, values: { name: 'Row two', kind: 'b' } },
    ]);
    render(<FeatureListRenderer config={config} data={table} onZoomTo={vi.fn()} />);
    expect(screen.getByText('Row two')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('2 features shown')).toBeInTheDocument();
  });

  it('keeps rows plain with a hidden note where the dashboard has no map', () => {
    render(<FeatureListRenderer config={config} data={mapped} mapHidden />);
    expect(screen.queryByRole('button', { name: /Elm Park/ })).not.toBeInTheDocument();
    expect(screen.getByText(/has no map/)).toHaveClass('sr-only');
  });

  it('asks for the next page with Load more, and only while there is one', () => {
    const onLoadMore = vi.fn();
    const { rerender } = render(<FeatureListRenderer config={config} data={mapped} onLoadMore={onLoadMore} />);
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    rerender(<FeatureListRenderer config={config} data={mapped} onLoadMore={onLoadMore} loadingMore />);
    expect(screen.getByRole('button', { name: 'Loading more' })).toBeDisabled();

    rerender(<FeatureListRenderer config={config} data={rowsResult([])} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('loads the next page when the end of the list scrolls into view', () => {
    const observers: { callback: IntersectionObserverCallback; target?: Element }[] = [];
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        entry: { callback: IntersectionObserverCallback; target?: Element };
        constructor(callback: IntersectionObserverCallback) {
          this.entry = { callback };
          observers.push(this.entry);
        }
        observe(target: Element) {
          this.entry.target = target;
        }
        disconnect() {}
      },
    );
    try {
      const onLoadMore = vi.fn();
      render(<FeatureListRenderer config={config} data={mapped} onLoadMore={onLoadMore} />);
      const last = observers[observers.length - 1];
      last.callback([{ isIntersecting: true, target: last.target } as IntersectionObserverEntry], {} as IntersectionObserver);
      expect(onLoadMore).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('shows the text version without zoom or paging', () => {
    render(<FeatureListFallback config={config} data={mapped} />);
    expect(screen.getByText('Elm Park')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('feature list editor', () => {
  const columns = [
    { name: 'name', type: 'text' },
    { name: 'tags', type: 'ARRAY' },
    { name: 'extra', type: 'jsonb' },
    { name: 'built', type: 'integer' },
  ];

  it('offers only columns the rows endpoint can order by as the sort', async () => {
    // Radix scrolls the active option into view, which jsdom lacks.
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<FeatureListEditor config={config} onChange={vi.fn()} columns={columns} idPrefix="w" />);
    screen.getByRole('combobox', { name: 'Sort by' }).focus();
    await user.keyboard('{Enter}');
    const offered = screen.getAllByRole('option').map((option) => option.textContent);
    expect(offered).toEqual(['None', 'name', 'built']);
  });

  it('labels the title column picker with an id the widget title input does not use', () => {
    renderWithProviders(
      <>
        <input id="w-title" aria-label="Widget title" />
        <FeatureListEditor config={config} onChange={vi.fn()} columns={columns} idPrefix="w" />
      </>,
    );
    expect(screen.getByRole('combobox', { name: 'Title column' })).toBeInTheDocument();
    expect(document.getElementById('w-title')).toBe(screen.getByLabelText('Widget title'));
  });

  it('offers only listable columns as title and subtitle', async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    const all = [...columns, { name: 'status', type: 'USER-DEFINED' }, { name: 'Mixed', type: 'text' }];
    renderWithProviders(<FeatureListEditor config={config} onChange={vi.fn()} columns={all} idPrefix="w" />);
    screen.getByRole('combobox', { name: 'Subtitle column' }).focus();
    await user.keyboard('{Enter}');
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
      'None',
      'name',
      'tags',
      'extra',
      'built',
    ]);
  });

  it('can pick a column named like the none choice', async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    const onChange = vi.fn();
    const named = [...columns, { name: 'none', type: 'text' }, { name: '__none__', type: 'text' }];
    renderWithProviders(<FeatureListEditor config={config} onChange={onChange} columns={named} idPrefix="w" />);
    screen.getByRole('combobox', { name: 'Subtitle column' }).focus();
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('option', { name: '__none__' }));
    expect(onChange).toHaveBeenCalledWith({ ...config, subtitle_column: '__none__' });
  });

  it('starts a new list on a listable column', () => {
    const picked = featureListWidget.initialConfig?.([
      { name: 'status', type: 'USER-DEFINED' },
      { name: 'Label', type: 'text' },
      { name: 'title', type: 'text' },
    ]);
    expect(picked).toEqual({ title_column: 'title' });
  });

  it('mirrors the server rule for a sortable column', () => {
    expect(isListableColumn('name', 'text')).toBe(true);
    expect(isListableColumn('status', 'USER-DEFINED')).toBe(false);
    expect(isListableColumn('Mixed', 'text')).toBe(false);
    expect(isSortableColumn('name', 'text')).toBe(true);
    expect(isSortableColumn('built', 'integer')).toBe(true);
    for (const [name, type] of [['tags', 'ARRAY'], ['extra', 'jsonb'], ['geom', 'text'], ['Name', 'text'], ['x', null]] as const) {
      expect(isSortableColumn(name, type)).toBe(false);
    }
  });
});
