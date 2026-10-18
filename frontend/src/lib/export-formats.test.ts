import { exportFilename, exportFormatsFor, isExportFormat } from '@/lib/export-formats';

describe('export formats', () => {
  it('names a shapefile export as a zip and a parquet export by its extension', () => {
    expect(exportFilename('Manhattan Building Heights', 'shp')).toBe('Manhattan Building Heights.zip');
    expect(exportFilename('Manhattan Building Heights', 'parquet')).toBe('Manhattan Building Heights.parquet');
  });

  it('replaces path separators and recognizes only export formats', () => {
    expect(exportFilename('a/b\\c', 'csv')).toBe('a_b_c.csv');
    expect(isExportFormat('html')).toBe(false);
    expect(isExportFormat('shp')).toBe(true);
  });

  it('limits datasets without a geometry column to csv, as the server does', () => {
    expect(exportFormatsFor(null).map((f) => f.value)).toEqual(['csv']);
    expect(exportFormatsFor('Polygon')).toHaveLength(7);
  });
});
