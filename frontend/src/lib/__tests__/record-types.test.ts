// The frontend mirror answers every record type as the backend table does;
// the backend asserts the same snapshot against capabilities().
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { RECORD_TYPE_CAPABILITIES, recordTypeCapabilities } from '@/lib/record-types';

interface SnapshotEntry {
  feature_table: boolean;
  map_layer_type: string | null;
  tile_token: string | null;
}

const snapshot = JSON.parse(
  readFileSync(join(process.cwd(), 'src/lib/__tests__/record-type-capabilities.cases.json'), 'utf-8'),
) as { unknown: string; capabilities: Record<string, SnapshotEntry> };

const closed = snapshot.capabilities[snapshot.unknown];

describe('recordTypeCapabilities', () => {
  it('knows exactly the record types the backend table holds', () => {
    const backendTypes = Object.keys(snapshot.capabilities).filter((t) => t !== snapshot.unknown);
    expect(Object.keys(RECORD_TYPE_CAPABILITIES).sort()).toEqual(backendTypes.sort());
  });

  it.each(Object.entries(snapshot.capabilities))('answers %s as the backend does', (recordType, expected) => {
    expect(recordTypeCapabilities(recordType)).toEqual({
      featureTable: expected.feature_table,
      mapLayerType: expected.map_layer_type,
      tileToken: expected.tile_token,
    });
  });

  it.each([undefined, null, '', 'constructor'])('gives %j no capabilities', (recordType) => {
    expect(recordTypeCapabilities(recordType)).toEqual({
      featureTable: closed.feature_table,
      mapLayerType: closed.map_layer_type,
      tileToken: closed.tile_token,
    });
  });
});
