import {
  qualityScoreClasses,
  semanticBadgeColors,
  recordTypeColors,
  ingestionStatusColors,
  validationLevelColors,
  healthDotColors,
  vrtRasterStatusColors,
  syntheticBadgeColor,
} from '@/lib/status-colors';

describe('qualityScoreClasses', () => {
  it('returns neutral styling for score 70 (60-79 range)', () => {
    const result = qualityScoreClasses(70);
    expect(result).toContain('bg-secondary');
    expect(result).not.toContain('amber');
  });

  it('returns emerald styling for score 85 (80+ range)', () => {
    const result = qualityScoreClasses(85);
    expect(result).toContain('emerald');
  });

  it('returns rose styling for score 40 (below 60)', () => {
    const result = qualityScoreClasses(40);
    expect(result).toContain('rose');
  });

  it('returns emerald styling for score 95 (high score)', () => {
    const result = qualityScoreClasses(95);
    expect(result).toContain('emerald');
  });

  it('returns rose styling for score 55 (just below 60)', () => {
    const result = qualityScoreClasses(55);
    expect(result).toContain('rose');
  });
});

describe('recordTypeColors', () => {
  it('maps all expected record types', () => {
    expect(Object.keys(recordTypeColors)).toEqual(
      expect.arrayContaining(['collection', 'vector_dataset', 'raster_dataset', 'vrt_dataset', 'table', 'unknown'])
    );
  });

  it('uses semanticBadgeColors for standard types', () => {
    expect(recordTypeColors.collection).toBe(semanticBadgeColors.warning);
    expect(recordTypeColors.vector_dataset).toBe(semanticBadgeColors.info);
    expect(recordTypeColors.raster_dataset).toBe(semanticBadgeColors.success);
  });

  it('uses violet palette for vrt_dataset', () => {
    expect(recordTypeColors.vrt_dataset).toContain('violet');
  });
});

describe('ingestionStatusColors', () => {
  it('maps all expected statuses', () => {
    expect(Object.keys(ingestionStatusColors)).toEqual(
      expect.arrayContaining(['draft', 'ready', 'internal'])
    );
  });

  it('uses semantic tokens for draft and ready', () => {
    expect(ingestionStatusColors.draft).toBe(semanticBadgeColors.warning);
    expect(ingestionStatusColors.ready).toBe(semanticBadgeColors.info);
  });

  it('uses muted for internal', () => {
    expect(ingestionStatusColors.internal).toContain('bg-muted');
  });
});

describe('validationLevelColors', () => {
  it('maps error, warning, success to semantic tokens', () => {
    expect(validationLevelColors.error).toBe('text-destructive');
    expect(validationLevelColors.warning).toBe('text-warning');
    expect(validationLevelColors.success).toBe('text-success');
  });
});

describe('healthDotColors', () => {
  it('maps all expected states', () => {
    expect(healthDotColors.healthy).toBe('bg-success');
    expect(healthDotColors.unhealthy).toBe('bg-destructive');
    expect(healthDotColors.unknown).toBe('bg-muted-foreground');
  });
});

describe('vrtRasterStatusColors', () => {
  it('maps all expected statuses', () => {
    expect(Object.keys(vrtRasterStatusColors)).toEqual(
      expect.arrayContaining(['ready', 'regenerating', 'failed'])
    );
  });

  it('uses semantic border/text tokens', () => {
    expect(vrtRasterStatusColors.ready).toContain('text-success');
    expect(vrtRasterStatusColors.failed).toContain('text-destructive');
  });
});

describe('syntheticBadgeColor', () => {
  it('uses violet palette with dark mode variants', () => {
    expect(syntheticBadgeColor).toContain('violet');
    expect(syntheticBadgeColor).toContain('dark:');
  });
});
