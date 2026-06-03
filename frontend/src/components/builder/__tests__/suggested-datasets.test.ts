import { describe, it, expect } from 'vitest';
import { SUGGESTED_DATASETS } from '../suggested-datasets';
import type { SuggestedDataset } from '../suggested-datasets';

/**
 * Minimal test stub for suggested-datasets.ts (CE-23 remediation).
 *
 * suggested-datasets.ts is a pure constants file that ships empty by default.
 * Operators populate it per deployment. Tests verify the export contract and
 * that any populated entries conform to the SuggestedDataset interface.
 */

function isValidUUIDv4(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id);
}

const VALID_RECORD_TYPES: SuggestedDataset['record_type'][] = [
  'vector_dataset',
  'raster_dataset',
  'vrt_dataset',
];

describe('SUGGESTED_DATASETS', () => {
  it('exports an array (may be empty by default)', () => {
    expect(Array.isArray(SUGGESTED_DATASETS)).toBe(true);
  });

  it('every entry has required fields: id, name, record_type', () => {
    for (const dataset of SUGGESTED_DATASETS) {
      expect(typeof dataset.id).toBe('string');
      expect(dataset.id.length).toBeGreaterThan(0);
      expect(typeof dataset.name).toBe('string');
      expect(dataset.name.length).toBeGreaterThan(0);
      expect(VALID_RECORD_TYPES).toContain(dataset.record_type);
    }
  });

  it('every populated entry has a valid UUID v4 id (guards against 404 API calls)', () => {
    for (const dataset of SUGGESTED_DATASETS) {
      expect(isValidUUIDv4(dataset.id)).toBe(true);
    }
  });
});
