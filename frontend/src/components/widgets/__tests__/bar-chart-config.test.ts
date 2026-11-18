import {
  barChartWidget,
  layerColorColumn,
  needsVersion2,
  pickedColumn,
  type BarChartConfig,
} from '../bar-chart/definition';

const parse = (raw: unknown, v = 2) => barChartWidget.parseConfig(raw, v);
const category = { column: 'kind', stat: 'count', stat_column: null, limit: 10 };
const byFeature = { mode: 'by_feature', label_column: 'name', value_column: 'height', sort: 'desc', limit: 10 };
const byFields = { mode: 'by_fields', fields: ['height', 'area'], stat: 'sum' };
const byDate = { mode: 'date', column: 'built', date_bucket: 'month', stat: 'count', stat_column: null, limit: 12 };

describe('bar chart config', () => {
  it('reads a stored category chart that carries the layer colour option', () => {
    const config = { ...category, use_layer_colors: false };
    expect(parse({ ...config, mode: 'category' }, 1)).toEqual(config);
  });

  it('reads the legacy shape without adding keys', () => {
    expect(parse(category, 1)).toEqual(category);
    expect(parse({ column: 'kind' }, 1)).toEqual(category);
  });

  it('reads each further form as the server stores it, with its unused keys null', () => {
    expect(parse(byDate)).toEqual(byDate);
    expect(parse(byFeature)).toEqual(byFeature);
    expect(parse(byFields)).toEqual(byFields);
    // The server writes the keys a mode doesn't use as null, and the default limit.
    expect(
      parse({ ...byFeature, column: null, stat: 'count', stat_column: null, sort: 'asc' }),
    ).toEqual({ ...byFeature, sort: 'asc' });
    expect(parse({ ...byFields, column: null, stat_column: null, limit: 10 })).toEqual(byFields);
  });

  it('requires each form to name what it draws', () => {
    for (const bad of [
      { mode: 'date', column: 'built', stat: 'count', stat_column: null, limit: 10 },
      { mode: 'date', date_bucket: 'month' },
      { mode: 'date', column: 'built', date_bucket: 'decade' },
      { mode: 'by_feature', label_column: 'name' },
      { mode: 'by_feature', value_column: 'height' },
      { mode: 'by_fields', fields: [] },
      { mode: 'by_fields' },
      { mode: 'by_fields', fields: ['a', 'a'] },
      { mode: 'by_fields', fields: Array.from({ length: 21 }, (_, i) => `f${i}`) },
      { mode: 'stacked', column: 'kind' },
    ]) {
      expect(parse(bad)).toBeNull();
    }
  });

  it('refuses keys that do not belong to the mode', () => {
    for (const bad of [
      { ...category, date_bucket: 'month' },
      { ...category, fields: ['height'] },
      { ...category, label_column: 'name' },
      { ...category, sort: 'asc' },
      { ...byDate, use_layer_colors: false },
      { ...byFeature, column: 'kind' },
      { ...byFeature, stat_column: 'height' },
      { ...byFeature, use_layer_colors: false },
      { ...byFields, column: 'kind' },
      { ...byFields, sort: 'asc' },
      { ...byFields, date_bucket: 'day' },
      { ...byDate, fields: ['height'] },
    ]) {
      expect(parse(bad)).toBeNull();
    }
  });

  it('keeps the statistic column rule of a grouped chart', () => {
    expect(parse({ ...byDate, stat: 'sum', stat_column: 'value' })).toMatchObject({ stat: 'sum', stat_column: 'value' });
    expect(parse({ ...byDate, stat: 'sum' })).toBeNull();
    expect(parse({ ...byDate, stat_column: 'value' })).toBeNull();
  });
});

describe('bar chart requests', () => {
  const request = (raw: unknown) => barChartWidget.dataRequest!(parse(raw)!);

  it('counts values of the column, or groups a statistic by it', () => {
    expect(request(category)).toEqual({ op: 'value_counts', column: 'kind', limit: 10, blank_text_as_null: true });
    expect(request({ ...category, stat: 'mean', stat_column: 'area' })).toEqual({
      op: 'group_by',
      group_column: 'kind',
      stat: 'avg',
      column: 'area',
      limit: 10,
      blank_text_as_null: true,
    });
  });

  it('asks for one row per feature, sorted by the value and capped', () => {
    expect(request(byFeature)).toEqual({
      op: 'rows',
      columns: ['name', 'height'],
      sort_column: 'height',
      sort: 'desc',
      limit: 10,
    });
    expect(request({ ...byFeature, sort: 'asc', limit: 5 })).toMatchObject({ sort: 'asc', limit: 5 });
  });

  it('asks for the statistic of every chosen field', () => {
    expect(request(byFields)).toEqual({ op: 'stats_by_fields', columns: ['height', 'area'], stats: ['sum'] });
    expect(request({ ...byFields, stat: 'mean' })).toMatchObject({ stats: ['avg'] });
  });

  it('groups the date column by its bucket', () => {
    expect(request(byDate)).toEqual({
      op: 'group_by',
      group_column: 'built',
      date_bucket: 'month',
      stat: 'count',
      limit: 12,
      blank_text_as_null: false,
    });
    expect(request({ ...byDate, date_bucket: 'week', stat: 'sum', stat_column: 'value' })).toEqual({
      op: 'group_by',
      group_column: 'built',
      date_bucket: 'week',
      stat: 'sum',
      column: 'value',
      limit: 12,
      blank_text_as_null: false,
    });
  });

  it('names the columns each form reads, and which must be numbers', () => {
    const reads = (raw: unknown) => barChartWidget.readsColumns!(parse(raw)!);
    expect(reads(byFeature)).toEqual([
      { name: 'name', numeric: false, listable: true },
      { name: 'height', numeric: true, sortable: true },
    ]);
    expect(reads(byFields)).toEqual([
      { name: 'height', numeric: true },
      { name: 'area', numeric: true },
    ]);
    expect(reads(byDate)).toEqual([{ name: 'built', numeric: false, date: true }]);
  });
});

describe('bar chart options', () => {
  const read = (raw: unknown) => parse(raw) as BarChartConfig;
  it('stores version 1 until an option needs 2', () => {
    const storedVersion = (config: unknown) => barChartWidget.storedVersion!(read(config));
    expect(needsVersion2(read(category)!)).toBe(false);
    expect(storedVersion(category)).toBe(1);
    expect(storedVersion({ ...category, use_layer_colors: false })).toBe(2);
    expect(storedVersion(byFeature)).toBe(2);
    expect(storedVersion(byDate)).toBe(2);
  });

  it('reads a version 2 widget and offers picks only for bars that are values of one column', () => {
    expect(barChartWidget.v).toBe(3);
    expect(pickedColumn(read(category)!)).toBe('kind');
    expect(pickedColumn(read(byFeature)!)).toBe('name');
    expect(pickedColumn(read(byDate)!)).toBeNull();
    expect(pickedColumn(read(byFields)!)).toBeNull();
    // The host passes onSelect only for a named column.
    expect(barChartWidget.picksColumn!(read(byFields)!)).toBe('');
  });

  it('takes layer colours for a category chart unless switched off', () => {
    expect(layerColorColumn(read(category)!)).toBe('kind');
    expect(layerColorColumn(read({ ...category, use_layer_colors: false }))).toBeNull();
    expect(layerColorColumn(read(byFeature)!)).toBeNull();
    expect(layerColorColumn(read(byDate)!)).toBeNull();
  });
});
