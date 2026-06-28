import { describe, it, expect } from 'vitest';
import { toViewerSyncInput } from '@/components/viewer/ViewerMap';
import { getDataDrivenColumnsForLayer } from '@/components/builder/map-sync';
import type { SharedLayerResponse } from '@/types/api';

// #350 (Codex P2): the INITIAL viewer render builds its source via
// toViewerSyncInput() -> syncMapComposition before any token-refresh path runs.
// If popup_config is dropped in that conversion, a viewer opened at z<10 strips
// the popup's selected fields and shows "No attributes". Pin the copy so the
// initial source build requests the popup cols= just like the refresh path.
describe('toViewerSyncInput popup_config preservation (#350)', () => {
  function makeShared(popup_config: SharedLayerResponse['popup_config']): SharedLayerResponse {
    return {
      table_name: 'cities',
      geometry_type: 'MultiPoint',
      opacity: 1,
      paint: {},
      layout: {},
      filter: null,
      label_config: null,
      style_config: null,
      dataset_id: 'ds-1',
      popup_config,
    } as unknown as SharedLayerResponse;
  }

  it('carries popup_config into the normalized viewer input', () => {
    const popup = { enabled: true, expression: '{city}, {state}', visible_fields: ['pop2025', 'label'] };
    const input = toViewerSyncInput(makeShared(popup), 'l1', new Set(['l1']));
    expect(input.popup_config).toEqual(popup);
  });

  it('the initial source build requests popup cols via the carried config', () => {
    const input = toViewerSyncInput(
      makeShared({ enabled: true, expression: '{city}', visible_fields: ['pop2025', 'label'] }),
      'l1',
      new Set(['l1']),
    );
    // This is what syncMapComposition feeds to buildSignedTileUrl for the source.
    expect(getDataDrivenColumnsForLayer(input).sort()).toEqual(['city', 'label', 'pop2025']);
  });

  it('passes through a null popup_config without inventing cols', () => {
    const input = toViewerSyncInput(makeShared(null), 'l1', new Set(['l1']));
    expect(input.popup_config).toBeNull();
    expect(getDataDrivenColumnsForLayer(input)).toEqual([]);
  });
});
