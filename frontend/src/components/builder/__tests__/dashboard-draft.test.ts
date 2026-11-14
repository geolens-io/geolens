import { dashboardReadableTypes } from '@/components/widgets/registry';
import type { MapLayerResponse } from '@/types/api';
import {
  dashboardChanged,
  dashboardPayload,
  dashboardSavePayload,
  toDashboardDraft,
  widgetProblem,
  widgetLayerGone,
  type DashboardDraft,
} from '../dashboard-draft';

const layerId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
const goneId = '1c8e3f5a-4d2b-4f9c-8a7e-6b3d8f2c0e45';

function layer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: layerId,
    dataset_id: 'dataset-1',
    dataset_name: 'Parcels',
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    dataset_geometry_type: 'POLYGON',
    dataset_column_info: [
      { name: 'kind', type: 'text' },
      { name: 'area', type: 'double precision' },
    ],
    show_in_legend: true,
    ...overrides,
  } as MapLayerResponse;
}

function indicator(config: Record<string, unknown>, onLayer = layerId) {
  return {
    id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
    type: 'indicator',
    v: 1,
    layer_id: onLayer,
    scope: 'layer' as const,
    config: { stat: 'count', column: null, ...config },
  };
}

describe('the version a save stores for a bar chart', () => {
  const bar = (config: Record<string, unknown>) => ({
    id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
    type: 'bar_chart',
    v: 2,
    layer_id: layerId,
    scope: 'layer' as const,
    config,
  });
  const plain = { column: 'kind', stat: 'count', stat_column: null, limit: 10 };
  const saved = (config: Record<string, unknown>) =>
    dashboardPayload({ panel: 'right', widgets: [bar(config)] }, [layer()], { panel: 'right' })?.widgets?.[0];

  it('stays 1 while the chart uses no option of version 2, so earlier releases keep reading it', () => {
    expect(saved(plain)).toMatchObject({ v: 1 });
  });

  it('is 2 once it groups by date, by feature or by field, or turns layer colours off', () => {
    expect(saved({ ...plain, use_layer_colors: false })).toMatchObject({ v: 2 });
    expect(
      saved({ mode: 'date', column: 'built', date_bucket: 'year', stat: 'count', stat_column: null, limit: 10 }),
    ).toMatchObject({ v: 2 });
  });
});

describe("a widget's own filter", () => {
  const keep = ['==', ['get', 'kind'], 'parcel'];
  const filtered = (filter: unknown, extra: Record<string, unknown> = {}) => ({ ...indicator(extra), filter }) as never;
  const saved = (widget: never) =>
    dashboardPayload({ panel: 'right', widgets: [widget] }, [layer()], { panel: 'right' })?.widgets?.[0];

  it('stores at the filter version and reads back, while a plain widget keeps its version and no filter key', () => {
    expect(saved(filtered(keep))).toMatchObject({ v: 3, filter: keep });
    expect(saved(filtered(keep, { reference: 5 }))).toMatchObject({ v: 3 });
    const plain = saved(indicator({}) as never);
    expect(plain).toMatchObject({ v: 1 });
    expect(plain).not.toHaveProperty('filter');
    const draft = toDashboardDraft({ version: 1, widgets: [{ ...indicator({}), v: 3, filter: keep }] } as never);
    expect(draft.widgets[0].filter).toEqual(keep);
  });

  it('is not read from a version that cannot carry it, or in a form the layer filter grammar refuses', () => {
    expect(toDashboardDraft({ version: 1, widgets: [{ ...indicator({}), v: 2, filter: keep }] } as never).widgets).toEqual(
      [],
    );
    expect(
      toDashboardDraft({ version: 1, widgets: [{ ...indicator({}), v: 3, filter: ['==', ['get', 'kind']] }] } as never)
        .widgets,
    ).toEqual([]);
  });

  it('lists the filter versions in what a save says it reads', () => {
    expect(dashboardReadableTypes()).toEqual(
      expect.arrayContaining(['indicator:3', 'bar_chart:3', 'pie_chart:2', 'table:2', 'histogram:2']),
    );
  });

  it('holds the save on a column the layer lacks or a filter the endpoint cannot take', () => {
    expect(widgetProblem(filtered(['==', ['get', 'owner'], 'x']), layer())).toEqual({
      kind: 'missingColumn',
      column: 'owner',
    });
    expect(widgetProblem(filtered(['>', ['length', ['get', 'kind']], 3]), layer())).toEqual({
      kind: 'filterUnsupported',
    });
    expect(widgetProblem(filtered(keep), layer())).toBeNull();
  });

  it('reads no column from the values of a literal list, positive or negated, in a group', () => {
    const members = ['in', ['get', 'kind'], ['literal', ['get', 'has']]];
    expect(widgetProblem(filtered(['all', members, ['any', ['!', ['in', ['get', 'kind'], ['literal', ['has', 'x']]]]]]), layer())).toBeNull();
  });

  it.each([
    [['!in', 'owner', 'x']],
    [['!has', 'owner']],
    [['all', ['has', 'kind'], ['!in', 'owner', 'x']]],
  ])('finds the column a legacy spelling names: %j', (filter) => {
    expect(widgetProblem(filtered(filter), layer())).toEqual({ kind: 'missingColumn', column: 'owner' });
  });

  it.each([[['none', ['!has', 'owner']]], [['all', ['==', ['get', 'kind'], 'a'], ['!has', 'owner']]], [['match', ['get', 'kind'], 'a', true, false]]])(
    'holds a filter in a shape a widget does not take: %j',
    (filter) => {
      expect(widgetProblem(filtered(filter), layer())).toEqual({ kind: 'filterUnsupported' });
    },
  );

  it('holds a filter whose columns are computed', () => {
    expect(widgetProblem(filtered(['==', ['get', ['concat', 'ki', 'nd']], 'a']), layer())).toEqual({
      kind: 'filterUnsupported',
    });
    expect(widgetProblem(filtered(['==', ['at', 0, ['properties']], 'a']), layer())).toEqual({
      kind: 'filterUnsupported',
    });
  });

  it('holds a filter that, with the layer filter, is past what the aggregate endpoint takes', () => {
    const values = Array.from({ length: 900 }, (_, i) => `value-${i}`);
    const members = ['in', ['get', 'kind'], ['literal', values]];
    expect(widgetProblem(filtered(members), layer())).toEqual({ kind: 'filterTooLarge' });
    const half = ['in', ['get', 'kind'], ['literal', values.slice(0, 450)]];
    expect(widgetProblem(filtered(half), layer())).toBeNull();
    expect(widgetProblem(filtered(half), layer({ filter: half as never }))).toEqual({ kind: 'filterTooLarge' });
  });
});

describe('dashboard drafts', () => {
  it('read a dashboard saved before the panel choice as a right panel', () => {
    expect(toDashboardDraft(null)).toEqual({ panel: 'right', widgets: [] });
    const draft = toDashboardDraft({ version: 1, widgets: [indicator({})] } as never);
    expect(draft.panel).toBe('right');
    expect(draft.widgets).toHaveLength(1);
    expect(toDashboardDraft({
        version: 1,
        panel: 'bottom',
        map_hidden: false,
        theme: 'follow',
        widgets: [],
      }).panel).toBe('bottom');
  });

  it('find the columns a widget reads that its layer lacks or holds as text', () => {
    expect(widgetProblem(indicator({ stat: 'sum', column: 'area' }), layer())).toBeNull();
    expect(widgetProblem(indicator({ stat: 'sum', column: 'height' }), layer())).toEqual({
      kind: 'missingColumn',
      column: 'height',
    });
    expect(widgetProblem(indicator({ stat: 'max', column: 'kind' }), layer())).toEqual({
      kind: 'notNumeric',
      column: 'kind',
    });
    // Without column metadata the server decides.
    expect(
      widgetProblem(indicator({ stat: 'sum', column: 'height' }), layer({ dataset_column_info: null })),
    ).toBeNull();
  });

  it('notice a widget whose layer left the map or has no rows to summarize', () => {
    expect(widgetLayerGone(indicator({}), [layer()])).toBe(false);
    expect(widgetLayerGone(indicator({}, goneId), [layer()])).toBe(true);
    expect(widgetLayerGone(indicator({}), [layer({ layer_type: 'raster_geolens' })])).toBe(true);
  });

  it('count a draft as changed only when saving it would change the dashboard', () => {
    const saved: DashboardDraft = { panel: 'right', widgets: [{ ...indicator({}), title: 'Parcels' }] };
    expect(dashboardChanged({ ...saved, panel: 'bottom' }, saved)).toBe(true);
    expect(dashboardChanged({ ...saved, panel: 'right' }, saved)).toBe(false);
    // Saving trims the title, so whitespace alone is no change.
    expect(dashboardChanged({ ...saved, widgets: [{ ...indicator({}), title: ' Parcels ' }] }, saved)).toBe(false);
    expect(dashboardChanged({ ...saved, widgets: [{ ...indicator({}), title: 'Lots' }] }, saved)).toBe(true);
    expect(dashboardChanged({ panel: 'right', widgets: [] }, { panel: 'right', widgets: [] })).toBe(false);
    // No widgets saves as no dashboard, which reads back as a right panel.
    expect(dashboardChanged({ panel: 'bottom', widgets: [] }, { panel: 'right', widgets: [] })).toBe(false);
  });

  it('save without the widgets whose layer left the map, and as null when none are left', () => {
    const kept = { ...indicator({}), title: '  Parcels  ' };
    const gone = { ...indicator({}, goneId), id: '9a2b4c6d-1e3f-4a5b-8c7d-0e1f2a3b4c5d' };
    const draft: DashboardDraft = { panel: 'bottom', widgets: [kept, gone] };

    expect(dashboardPayload(draft, [layer()], { panel: 'right' })).toEqual({
      version: 1,
      readable: dashboardReadableTypes(),
      panel: 'bottom',
      widgets: [{ ...kept, title: 'Parcels' }],
    });
    expect(dashboardPayload({ panel: 'right', widgets: [gone] }, [layer()], { panel: 'right' })).toBeNull();
    const { title: _title, ...untitled } = kept;
    expect(
      dashboardPayload({ panel: 'right', widgets: [{ ...kept, title: ' ' }] }, [layer()], { panel: 'right' })?.widgets,
    ).toEqual([untitled]);
  });

  it('send the panel only where a 1.28.0 server is ruled out', () => {
    const widgets = [indicator({})];
    // A right panel on a map that never had a bottom one: a 1.28.0 server would refuse the key.
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], { panel: 'right' })).not.toHaveProperty('panel');
    expect(dashboardPayload({ panel: 'bottom', widgets }, [layer()], { panel: 'right' })?.panel).toBe('bottom');
    // Moving a stored bottom panel back must say so.
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], { panel: 'bottom' })?.panel).toBe('right');
  });

  it('round-trip a hidden map through the draft and the payload, sending it only when it matters', () => {
    const widgets = [indicator({})];
    expect(toDashboardDraft({ version: 1, map_hidden: false, widgets } as never)).not.toHaveProperty('mapHidden');
    const hidden = toDashboardDraft({ version: 1, map_hidden: true, widgets } as never);
    expect(hidden.mapHidden).toBe(true);
    expect(dashboardPayload(hidden, [layer()], { panel: 'right' })?.map_hidden).toBe(true);
    // Off and never stored: a server from before the setting would refuse the key.
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], { panel: 'right' })).not.toHaveProperty('map_hidden');
    // Showing the map again must say so.
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], { panel: 'right', mapHidden: true })?.map_hidden).toBe(false);
    expect(dashboardChanged({ panel: 'right', widgets, mapHidden: true }, { panel: 'right', widgets })).toBe(true);
    expect(dashboardChanged({ panel: 'right', widgets, mapHidden: undefined }, { panel: 'right', widgets })).toBe(false);
  });

  it('drop a hidden map along with the last widget', () => {
    expect(dashboardPayload({ panel: 'right', widgets: [], mapHidden: true }, [layer()], { panel: 'right', mapHidden: true })).toBeNull();
    expect(
      dashboardChanged({ panel: 'right', widgets: [], mapHidden: true }, { panel: 'right', widgets: [] }),
    ).toBe(false);
  });

  it('send the reader theme only when it is, or was, light or dark', () => {
    const widgets = [indicator({})];
    // Leaving the key out keeps the stored theme, so resetting to follow must say so.
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], { panel: 'right' })).not.toHaveProperty('theme');
    expect(dashboardPayload({ panel: 'right', theme: 'dark', widgets }, [layer()], { panel: 'right' })?.theme).toBe('dark');
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], { panel: 'right', theme: 'dark' })?.theme).toBe('follow');
    expect(dashboardPayload({ panel: 'right', theme: 'follow', widgets }, [layer()], { panel: 'right' })).not.toHaveProperty(
      'theme',
    );
  });

  it('read the saved theme and count a theme change as a change', () => {
    const saved = toDashboardDraft({ version: 1, panel: 'right', map_hidden: false, theme: 'light', widgets: [] });
    expect(saved.theme).toBe('light');
    expect(toDashboardDraft(null).theme).toBeUndefined();
    const widgets = [indicator({})];
    expect(dashboardChanged({ panel: 'right', widgets }, { panel: 'right', theme: 'dark', widgets })).toBe(true);
    expect(dashboardChanged({ panel: 'right', widgets }, { panel: 'right', theme: 'follow', widgets })).toBe(false);
  });

  it('refuse a view scope on a layer with no geometry', () => {
    const viewWidget = { ...indicator({}), scope: 'view' as const };
    expect(widgetProblem(viewWidget, layer({ dataset_geometry_type: 'POINT' }))).toBeNull();
    expect(widgetProblem(viewWidget, layer({ dataset_geometry_type: null }))).toEqual({
      kind: 'viewWithoutGeometry',
    });
    expect(widgetProblem(indicator({}), layer({ dataset_geometry_type: null }))).toBeNull();
  });
});

describe('a widget with no layer', () => {
  const text = {
    id: '2d9f4a6b-5e3c-4a0d-9b8f-7c4e9a3d1f56',
    type: 'markdown',
    v: 1,
    config: { text: 'Source: county GIS' },
  };

  it('is kept when no layer can host widgets, and saved without a layer', () => {
    expect(widgetLayerGone(text, [])).toBe(false);
    expect(dashboardPayload({ panel: 'right', widgets: [text] }, [], { panel: 'right' })).toEqual({
      version: 1,
      readable: dashboardReadableTypes(),
      widgets: [text],
    });
  });

  it('reads back from a map response', () => {
    expect(toDashboardDraft({ version: 1, widgets: [text] } as never).widgets).toEqual([text]);
  });

  it('holds a feature list sorted on a column the rows endpoint cannot order by', () => {
    const list = (sort_column: string) =>
      ({
        id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
        type: 'feature_list',
        v: 1,
        layer_id: layerId,
        scope: 'layer',
        config: { title_column: 'kind', subtitle_column: null, sort_column, sort: 'asc', page_size: 25 },
      }) as never;
    const withColumns = layer({
      dataset_column_info: [
        { name: 'kind', type: 'text' },
        { name: 'tags', type: 'ARRAY' },
      ],
    } as never);
    expect(widgetProblem(list('kind'), withColumns)).toBeNull();
    expect(widgetProblem(list('tags'), withColumns)).toEqual({ kind: 'notSortable', column: 'tags' });
  });
});

describe('a date bar chart', () => {
  const dateChart = (column: string) =>
    ({
      id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
      type: 'bar_chart',
      v: 2,
      layer_id: layerId,
      scope: 'layer',
      config: { mode: 'date', column, date_bucket: 'month', stat: 'count', stat_column: null, limit: 10 },
    }) as never;
  const withColumns = layer({
    dataset_column_info: [
      { name: 'kind', type: 'text' },
      { name: 'built', type: 'date' },
    ],
  } as never);

  it('holds the save while its column is not a date type', () => {
    expect(widgetProblem(dateChart('built'), withColumns)).toBeNull();
    expect(widgetProblem(dateChart('kind'), withColumns)).toEqual({ kind: 'notDate', column: 'kind' });
  });
});

describe('a by-feature bar chart', () => {
  const chart = (value_column: string, label_column = 'kind') =>
    ({
      id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
      type: 'bar_chart',
      v: 2,
      layer_id: layerId,
      scope: 'layer',
      config: { mode: 'by_feature', label_column, value_column, sort: 'desc', limit: 10 },
    }) as never;
  const withColumns = layer({
    dataset_column_info: [
      { name: 'kind', type: 'text' },
      { name: 'height', type: 'integer' },
      { name: 'Height', type: 'integer' },
      { name: 'zone', type: 'user-defined' },
    ],
  } as never);

  it('holds the save while its label field cannot be listed', () => {
    expect(widgetProblem(chart('height', 'Height'), withColumns)).toEqual({ kind: 'notListable', column: 'Height' });
    expect(widgetProblem(chart('height', 'zone'), withColumns)).toEqual({ kind: 'notListable', column: 'zone' });
  });

  it('holds the save while its value field is a name the rows endpoint cannot sort by', () => {
    expect(widgetProblem(chart('height'), withColumns)).toBeNull();
    expect(widgetProblem(chart('Height'), withColumns)).toEqual({ kind: 'notSortable', column: 'Height' });
  });
});

describe('the save that empties a dashboard', () => {
  const widget = { id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11', type: 'markdown', v: 1, config: { text: 'Notes' } };
  const had: DashboardDraft = { panel: 'right', widgets: [widget] };
  const none: DashboardDraft = { panel: 'right', widgets: [] };

  it('says what the build reads, so stored widgets beyond the earliest ones go too', () => {
    expect(dashboardSavePayload(none, [], had)).toEqual({
      version: 1,
      panel: 'right',
      map_hidden: false,
      theme: 'follow',
      readable: dashboardReadableTypes(),
      widgets: [],
    });
  });

  it('resets the layout settings, since an empty dashboard reloads as the defaults', () => {
    const laidOut: DashboardDraft = { panel: 'bottom', theme: 'dark', mapHidden: true, widgets: [] };
    expect(dashboardSavePayload(laidOut, [], { ...had, panel: 'bottom', theme: 'dark', mapHidden: true })).toMatchObject({
      panel: 'right',
      theme: 'follow',
      map_hidden: false,
      widgets: [],
    });
  });

  it('stays null when there was nothing stored to clear', () => {
    expect(dashboardSavePayload(none, [], none)).toBeNull();
  });

  it('holds a feature list that titles rows with a column the rows endpoint cannot list', () => {
    const list = (title_column: string, subtitle_column: string | null) =>
      ({
        id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
        type: 'feature_list',
        v: 1,
        layer_id: layerId,
        scope: 'layer',
        config: { title_column, subtitle_column, sort_column: null, sort: 'asc', page_size: 25 },
      }) as never;
    const withColumns = layer({
      dataset_column_info: [
        { name: 'kind', type: 'text' },
        { name: 'status', type: 'USER-DEFINED' },
      ],
    } as never);
    expect(widgetProblem(list('kind', null), withColumns)).toBeNull();
    expect(widgetProblem(list('status', null), withColumns)).toEqual({ kind: 'notListable', column: 'status' });
    expect(widgetProblem(list('kind', 'status'), withColumns)).toEqual({ kind: 'notListable', column: 'status' });
  });
});
