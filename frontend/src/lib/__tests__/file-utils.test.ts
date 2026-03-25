import { buildAcceptMap, deriveFormatBadges } from '@/lib/file-utils';

describe('buildAcceptMap', () => {
  it('maps known extensions to correct MIME types', () => {
    const result = buildAcceptMap(['.zip', '.csv', '.tif']);
    expect(result).toEqual({
      'application/zip': ['.zip'],
      'text/csv': ['.csv'],
      'image/tiff': ['.tif'],
    });
  });

  it('groups extensions sharing a MIME type', () => {
    const result = buildAcceptMap(['.tif', '.tiff']);
    expect(result).toEqual({
      'image/tiff': ['.tif', '.tiff'],
    });
  });

  it('maps .geojson and .json to geo+json', () => {
    const result = buildAcceptMap(['.geojson', '.json']);
    expect(result).toEqual({
      'application/geo+json': ['.geojson', '.json'],
    });
  });

  it('falls back to application/octet-stream for unknown extensions', () => {
    const result = buildAcceptMap(['.parquet', '.fgb']);
    expect(result).toEqual({
      'application/octet-stream': ['.parquet', '.fgb'],
    });
  });

  it('handles mixed known and unknown extensions', () => {
    const result = buildAcceptMap(['.zip', '.parquet']);
    expect(result['application/zip']).toEqual(['.zip']);
    expect(result['application/octet-stream']).toEqual(['.parquet']);
  });

  it('returns empty object for empty input', () => {
    expect(buildAcceptMap([])).toEqual({});
  });

  it('deduplicates extensions within a MIME group', () => {
    const result = buildAcceptMap(['.tif', '.tif']);
    expect(result['image/tiff']).toEqual(['.tif']);
  });
});

describe('deriveFormatBadges', () => {
  it('returns all extensions when no aliases present', () => {
    expect(deriveFormatBadges(['.zip', '.csv', '.gpkg'])).toEqual(['.zip', '.csv', '.gpkg']);
  });

  it('deduplicates .tif/.tiff — keeps .tif', () => {
    expect(deriveFormatBadges(['.zip', '.tif', '.tiff'])).toEqual(['.zip', '.tif']);
  });

  it('deduplicates .geojson/.json — keeps .geojson', () => {
    expect(deriveFormatBadges(['.geojson', '.json', '.csv'])).toEqual(['.geojson', '.csv']);
  });

  it('keeps .tiff when .tif is not present', () => {
    expect(deriveFormatBadges(['.tiff', '.csv'])).toEqual(['.tiff', '.csv']);
  });

  it('keeps .json when .geojson is not present', () => {
    expect(deriveFormatBadges(['.json', '.csv'])).toEqual(['.json', '.csv']);
  });

  it('returns empty array for empty input', () => {
    expect(deriveFormatBadges([])).toEqual([]);
  });

  it('handles full default extension set', () => {
    const defaults = ['.zip', '.gpkg', '.geojson', '.json', '.csv', '.tif', '.tiff', '.xlsx', '.xls'];
    const badges = deriveFormatBadges(defaults);
    expect(badges).toEqual(['.zip', '.gpkg', '.geojson', '.csv', '.tif', '.xlsx', '.xls']);
    expect(badges).not.toContain('.json');
    expect(badges).not.toContain('.tiff');
  });
});
