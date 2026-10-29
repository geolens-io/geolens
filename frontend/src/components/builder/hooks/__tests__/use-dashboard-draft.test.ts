import { act, renderHook } from '@testing-library/react';
import type { DashboardConfig, MapLayerResponse } from '@/types/api';
import { useDashboardDraft } from '../use-dashboard-draft';

const layerA = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
const layerB = '2d9f4a6b-5e3c-4a0d-9b8f-7c4e9a3d1f56';
const widget = (id: string, layer = layerA, title?: string) => ({
  id,
  type: 'indicator',
  v: 1,
  layer_id: layer,
  scope: 'layer' as const,
  ...(title ? { title } : {}),
  config: { stat: 'count' as const, column: null },
});
const first = widget('6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11');
const second = widget('9a2b4c6d-1e3f-4a5b-8c7d-0e1f2a3b4c5d', layerB);
const saved = (panel: 'right' | 'bottom', widgets: unknown[]) =>
  ({ version: 1, panel, widgets }) as DashboardConfig;

const layer = (id: string) =>
  ({ id, dataset_id: `ds-${id}`, layer_type: 'vector_geolens', dataset_record_type: 'vector_dataset' }) as MapLayerResponse;
const both = [layer(layerA), layer(layerB)];
const onlyA = [layer(layerA)];

function renderDraft(initial: DashboardConfig, layers = both) {
  const onConflict = vi.fn();
  const hook = renderHook(
    ({ config, mapId, layerIds }) => useDashboardDraft(config, mapId, layerIds, onConflict),
    { initialProps: { config: initial, mapId: 'map-1', layerIds: layers } },
  );
  return { ...hook, onConflict };
}

describe('useDashboardDraft', () => {
  it('keeps edits across a refetch of the same dashboard and clears one the saved dashboard now holds', () => {
    const { result, rerender, onConflict } = renderDraft(saved('right', [first]));
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'bottom' }));
    expect(result.current.dashboardEdited).toBe(true);

    rerender({ config: saved('right', [first]), mapId: 'map-1', layerIds: both });
    expect(result.current.dashboard.panel).toBe('bottom');

    act(() => result.current.markSent(result.current.dashboard));
    rerender({ config: saved('bottom', [first]), mapId: 'map-1', layerIds: both });
    expect(result.current.dashboard.panel).toBe('bottom');
    expect(result.current.dashboardEdited).toBe(false);
    expect(onConflict).not.toHaveBeenCalled();
  });

  it('keeps an edit made while a save was in flight once the saved version comes back', () => {
    const { result, rerender, onConflict } = renderDraft(saved('right', [first]));
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'bottom' }));
    const sent = result.current.dashboard;
    act(() => result.current.markSent(sent));
    // Edited again before the save's response arrived.
    act(() => result.current.setDashboard({ ...sent, widgets: [first, second] }));

    rerender({ config: saved('bottom', [first]), mapId: 'map-1', layerIds: both });

    expect(result.current.dashboard.widgets.map((w) => w.id)).toEqual([first.id, second.id]);
    expect(result.current.dashboardEdited).toBe(true);
    expect(onConflict).not.toHaveBeenCalled();
  });

  it('keeps the edit when a save that stored only the layers prunes the saved dashboard', () => {
    const { result, rerender, onConflict } = renderDraft(saved('right', [first, second]));
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'bottom' }));

    // The layer PATCH removed layer B and the dashboard PUT failed.
    rerender({ config: saved('right', [first]), mapId: 'map-1', layerIds: onlyA });

    expect(result.current.dashboard.panel).toBe('bottom');
    expect(result.current.dashboardEdited).toBe(true);
    expect(onConflict).not.toHaveBeenCalled();
  });

  it('keeps local work and says so when another editor changes the dashboard', () => {
    const { result, rerender, onConflict } = renderDraft(saved('right', [first]));
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'bottom' }));

    rerender({ config: saved('right', [{ ...first, title: 'Theirs' }]), mapId: 'map-1', layerIds: both });

    expect(result.current.dashboard.panel).toBe('bottom');
    expect(result.current.dashboardEdited).toBe(true);
    expect(onConflict).toHaveBeenCalledTimes(1);
  });

  it('keeps an edit put back after sending once that save comes back', () => {
    const { result, rerender, onConflict } = renderDraft(saved('right', [first]));
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'bottom' }));
    act(() => result.current.markSent(result.current.dashboard));
    // Put back while the save was in flight.
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'right' }));

    rerender({ config: saved('bottom', [first]), mapId: 'map-1', layerIds: both });

    expect(result.current.dashboard.panel).toBe('right');
    expect(result.current.dashboardEdited).toBe(true);
    expect(onConflict).not.toHaveBeenCalled();
  });

  it('counts an edit put back to the saved dashboard as unedited', () => {
    const { result } = renderDraft(saved('right', [first]));
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'bottom' }));
    act(() => result.current.setDashboard({ ...result.current.dashboard, panel: 'right' }));
    expect(result.current.dashboardEdited).toBe(false);
  });

  it('starts over on another map', () => {
    const { result, rerender } = renderDraft(saved('right', []));
    act(() => result.current.setDashboard({ panel: 'bottom', widgets: [] }));
    rerender({ config: saved('right', []), mapId: 'map-2', layerIds: [] });
    expect(result.current.dashboard).toEqual({ panel: 'right', widgets: [] });
    expect(result.current.dashboardEdited).toBe(false);
  });
});
