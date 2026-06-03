import { describe, expect, it, vi } from 'vitest';
import {
  dispatchBuilderLayerAction,
  type BuilderLayerAction,
  type BuilderLayerActionHandlers,
} from '@/components/builder/builder-action-contract';
import type { MapLayerResponse } from '@/types/api';

function makeHandlers(): BuilderLayerActionHandlers {
  return {
    setFilter: vi.fn(),
    setPaint: vi.fn(),
    setStyleConfig: vi.fn(),
    setLabel: vi.fn(),
    setPopup: vi.fn(),
    setLayout: vi.fn(),
    setVisibility: vi.fn(),
    setOpacity: vi.fn(),
    addDataset: vi.fn(),
    removePersistedLayer: vi.fn(),
    removeDraftLayer: vi.fn(),
    duplicateRendering: vi.fn(),
    reorderLayers: vi.fn(),
    bindDemTerrain: vi.fn(),
    unbindDemTerrain: vi.fn(),
    setDemTerrainExaggeration: vi.fn(),
  };
}

describe('builder action contract', () => {
  it('dispatches typed layer actions to existing handlers', () => {
    const reordered = [{ id: 'layer-2' }] as MapLayerResponse[];
    const cases: Array<{
      action: BuilderLayerAction;
      handler: keyof BuilderLayerActionHandlers;
      args: unknown[];
    }> = [
      {
        action: { type: 'set_filter', layerId: 'layer-1', expression: ['==', 'kind', 'trail'] },
        handler: 'setFilter',
        args: ['layer-1', ['==', 'kind', 'trail']],
      },
      {
        action: { type: 'set_paint', layerId: 'layer-1', paint: { 'line-color': '#14532d' } },
        handler: 'setPaint',
        args: ['layer-1', { 'line-color': '#14532d' }],
      },
      {
        action: {
          type: 'set_style_config',
          layerId: 'layer-1',
          config: {
            mode: 'categorical',
            column: 'kind',
            ramp: 'Viridis',
            render_mode: 'heatmap',
          },
          paint: { 'heatmap-opacity': 0.7 },
        },
        handler: 'setStyleConfig',
        args: [
          'layer-1',
          { mode: 'categorical', column: 'kind', ramp: 'Viridis', render_mode: 'heatmap' },
          { 'heatmap-opacity': 0.7 },
        ],
      },
      {
        action: { type: 'set_label', layerId: 'layer-1', config: { column: 'name' } },
        handler: 'setLabel',
        args: ['layer-1', { column: 'name' }],
      },
      {
        action: { type: 'set_popup', layerId: 'layer-1', config: { enabled: true, expression: null, visible_fields: ['name'] } },
        handler: 'setPopup',
        args: ['layer-1', { enabled: true, expression: null, visible_fields: ['name'] }],
      },
      {
        action: { type: 'set_layout', layerId: 'layer-1', layout: { _minzoom: 8 } },
        handler: 'setLayout',
        args: ['layer-1', { _minzoom: 8 }],
      },
      {
        action: { type: 'set_visibility', layerId: 'layer-1', visible: false },
        handler: 'setVisibility',
        args: ['layer-1', false],
      },
      {
        action: { type: 'set_opacity', layerId: 'layer-1', opacity: 0.42 },
        handler: 'setOpacity',
        args: ['layer-1', 0.42],
      },
      {
        action: { type: 'add_dataset', datasetId: 'dataset-1' },
        handler: 'addDataset',
        args: ['dataset-1'],
      },
      {
        action: { type: 'duplicate_rendering', layerId: 'layer-1' },
        handler: 'duplicateRendering',
        args: ['layer-1'],
      },
      {
        action: { type: 'reorder_layers', layers: reordered },
        handler: 'reorderLayers',
        args: [reordered],
      },
      {
        action: { type: 'bind_dem_terrain', layerId: 'dem-layer' },
        handler: 'bindDemTerrain',
        args: ['dem-layer'],
      },
      {
        action: { type: 'unbind_dem_terrain', layerId: 'dem-layer' },
        handler: 'unbindDemTerrain',
        args: ['dem-layer'],
      },
      {
        action: { type: 'set_dem_terrain_exaggeration', layerId: 'dem-layer', exaggeration: 2.1 },
        handler: 'setDemTerrainExaggeration',
        args: ['dem-layer', 2.1],
      },
    ];

    for (const { action, handler, args } of cases) {
      const handlers = makeHandlers();

      dispatchBuilderLayerAction(action, handlers);

      expect(handlers[handler]).toHaveBeenCalledWith(...args);
    }
  });

  it('routes manual remove actions to the persisted remove handler', () => {
    const handlers = makeHandlers();

    dispatchBuilderLayerAction({
      type: 'remove_layer',
      source: 'manual',
      layerId: 'layer-1',
      persistence: 'server',
    }, handlers);

    expect(handlers.removePersistedLayer).toHaveBeenCalledWith('layer-1');
    expect(handlers.removeDraftLayer).not.toHaveBeenCalled();
  });

  it('routes AI remove actions to the draft-only remove handler', () => {
    const handlers = makeHandlers();

    dispatchBuilderLayerAction({
      type: 'remove_layer',
      source: 'ai',
      layerId: 'layer-1',
      persistence: 'draft',
    }, handlers);

    expect(handlers.removeDraftLayer).toHaveBeenCalledWith('layer-1');
    expect(handlers.removePersistedLayer).not.toHaveBeenCalled();
  });

  it.each([
    { input: 1.7, expected: 1 },
    { input: -0.3, expected: 0 },
    { input: 0.65, expected: 0.65 },
  ])('clamps opacity action payload $input to $expected', ({ input, expected }) => {
    const handlers = makeHandlers();

    dispatchBuilderLayerAction({
      type: 'set_opacity',
      source: 'ai',
      layerId: 'layer-1',
      opacity: input,
    }, handlers);

    expect(handlers.setOpacity).toHaveBeenCalledWith('layer-1', expected);
  });

  it('ignores non-finite opacity action payloads', () => {
    const handlers = makeHandlers();

    dispatchBuilderLayerAction({
      type: 'set_opacity',
      source: 'ai',
      layerId: 'layer-1',
      opacity: Number.NaN,
    }, handlers);

    expect(handlers.setOpacity).not.toHaveBeenCalled();
  });
});
