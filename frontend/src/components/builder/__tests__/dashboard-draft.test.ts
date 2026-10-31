import type { MapLayerResponse } from '@/types/api';
import {
  dashboardChanged,
  dashboardPayload,
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

describe('dashboard drafts', () => {
  it('read a dashboard saved before the panel choice as a right panel', () => {
    expect(toDashboardDraft(null)).toEqual({ panel: 'right', widgets: [] });
    const draft = toDashboardDraft({ version: 1, widgets: [indicator({})] } as never);
    expect(draft.panel).toBe('right');
    expect(draft.widgets).toHaveLength(1);
    expect(toDashboardDraft({ version: 1, panel: 'bottom', widgets: [] }).panel).toBe('bottom');
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

    expect(dashboardPayload(draft, [layer()], 'right')).toEqual({
      version: 1,
      panel: 'bottom',
      widgets: [{ ...kept, title: 'Parcels' }],
    });
    expect(dashboardPayload({ panel: 'right', widgets: [gone] }, [layer()], 'right')).toBeNull();
    const { title: _title, ...untitled } = kept;
    expect(
      dashboardPayload({ panel: 'right', widgets: [{ ...kept, title: ' ' }] }, [layer()], 'right')?.widgets,
    ).toEqual([untitled]);
  });

  it('send the panel only where a 1.28.0 server is ruled out', () => {
    const widgets = [indicator({})];
    // A right panel on a map that never had a bottom one: a 1.28.0 server would refuse the key.
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], 'right')).not.toHaveProperty('panel');
    expect(dashboardPayload({ panel: 'bottom', widgets }, [layer()], 'right')?.panel).toBe('bottom');
    // Moving a stored bottom panel back must say so.
    expect(dashboardPayload({ panel: 'right', widgets }, [layer()], 'bottom')?.panel).toBe('right');
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
    expect(dashboardPayload({ panel: 'right', widgets: [text] }, [], 'right')).toEqual({
      version: 1,
      widgets: [text],
    });
  });

  it('reads back from a map response', () => {
    expect(toDashboardDraft({ version: 1, widgets: [text] } as never).widgets).toEqual([text]);
  });
});
