import { exportFilename, exportFormatsFor } from '@/lib/export-formats';

describe('export formats', () => {
  it('names a shapefile export as a zip and a parquet export by its extension', () => {
    expect(exportFilename('Manhattan Building Heights', 'shp')).toBe('Manhattan Building Heights.zip');
    expect(exportFilename('Manhattan Building Heights', 'parquet')).toBe('Manhattan Building Heights.parquet');
  });

  it('replaces path separators and ignores non-export formats', () => {
    expect(exportFilename('a/b\\c', 'csv')).toBe('a_b_c.csv');
    expect(exportFilename('Viewer', 'html')).toBeNull();
  });

  it('limits tables to csv', () => {
    expect(exportFormatsFor('table').map((f) => f.value)).toEqual(['csv']);
  });
});
