import { describe, expect, it } from 'vitest';
import type { MapLayerResponse } from '@/types/api';
import { SAVED_LAYERS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';
import { legendFacts, type LegendFacts } from '../legend-facts';

type Row = [label: string, layer: MapLayerResponse, expected: LegendFacts | null];

const drawsNothing = new Set<string>(['folderRow', 'terrainDem']);

const fixtureRows: Row[] = Object.entries(SAVED_LAYERS).map(([key, layer]) => [
  key,
  layer,
  drawsNothing.has(key) ? null : { name: layer.display_name ?? '' },
]);

const nameRows: Row[] = [
  ['null display name', savedLayer({ display_name: null, dataset_name: 'County parcels' }), { name: 'County parcels' }],
  ['empty display name', savedLayer({ display_name: '', dataset_name: 'County parcels' }), { name: 'County parcels' }],
  ['whitespace display name', savedLayer({ display_name: '   ', dataset_name: 'County parcels' }), { name: 'County parcels' }],
  ['legendLabel override', savedLayer({ display_name: 'Parcels', style_config: { legendLabel: 'Tax parcels' } }), { name: 'Tax parcels' }],
  ['whitespace legendLabel', savedLayer({ display_name: 'Parcels', style_config: { legendLabel: '  ' } }), { name: 'Parcels' }],
  ['padded display name', savedLayer({ display_name: '  Parcels  ' }), { name: 'Parcels' }],
  ['no usable name', savedLayer({ display_name: ' ', dataset_name: '' }), { name: '' }],
  [
    'terrain DEM with a legendLabel',
    { ...SAVED_LAYERS.terrainDem, style_config: { render_mode: 'terrain', legendLabel: 'Relief' } },
    null,
  ],
];

describe('legendFacts', () => {
  it.each([...fixtureRows, ...nameRows])('%s gives the same facts in the builder and viewer shapes', (_label, layer, expected) => {
    expect(legendFacts(layer)).toEqual(expected);
    expect(legendFacts(toSharedLayer(layer))).toEqual(expected);
  });
});
