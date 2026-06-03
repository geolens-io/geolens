import {
  qualityScoreClasses,
  semanticBadgeColors,
  jobStatusColors,
  userStatusColors,
  visibilityColors,
  vrtGenerationColors,
  activeDotColor,
  recordTypeColors,
  ingestionStatusColors,
  validationLevelColors,
  healthDotColors,
  experimentalBadgeColor,
  syntheticBadgeColor,
  vrtRasterStatusColors,
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

  it('returns emerald styling for exact boundary 80', () => {
    expect(qualityScoreClasses(80)).toContain('emerald');
  });

  it('returns neutral styling for exact boundary 60', () => {
    expect(qualityScoreClasses(60)).toContain('bg-secondary');
  });

  it('returns rose styling for score 59 (just below 60)', () => {
    expect(qualityScoreClasses(59)).toContain('rose');
  });
});

describe('jobStatusColors', () => {
  it('maps all expected statuses to semantic tokens', () => {
    expect(jobStatusColors.pending).toBe(semanticBadgeColors.warning);
    expect(jobStatusColors.running).toBe(semanticBadgeColors.info);
    expect(jobStatusColors.complete).toBe(semanticBadgeColors.success);
    expect(jobStatusColors.failed).toBe(semanticBadgeColors.destructive);
  });
});

describe('userStatusColors', () => {
  it('maps all expected statuses', () => {
    expect(userStatusColors.pending).toBe(semanticBadgeColors.warning);
    expect(userStatusColors.active).toBe(semanticBadgeColors.success);
    expect(userStatusColors.deactivated).toContain('bg-muted');
  });
});

describe('visibilityColors', () => {
  it('maps all expected levels', () => {
    expect(visibilityColors.public).toBe(semanticBadgeColors.success);
    expect(visibilityColors.restricted).toBe(semanticBadgeColors.warning);
    expect(visibilityColors.private).toBe(semanticBadgeColors.destructive);
  });
});

describe('vrtGenerationColors', () => {
  it('maps all expected statuses', () => {
    expect(vrtGenerationColors.completed).toBe(semanticBadgeColors.success);
    expect(vrtGenerationColors.running).toBe(semanticBadgeColors.info);
    expect(vrtGenerationColors.failed).toBe(semanticBadgeColors.destructive);
  });
});

describe('activeDotColor', () => {
  it('maps boolean states to semantic tokens', () => {
    expect(activeDotColor.true).toBe('bg-success');
    expect(activeDotColor.false).toBe('bg-destructive');
  });
});

describe('recordTypeColors', () => {
  it('maps all expected record types', () => {
    expect(Object.keys(recordTypeColors)).toEqual(
      expect.arrayContaining(['collection', 'vector_dataset', 'raster_dataset', 'vrt_dataset', 'table', 'unknown'])
    );
  });

  it('uses design tokens for dataset types', () => {
    expect(recordTypeColors.vector_dataset).toContain('type-vector');
    expect(recordTypeColors.raster_dataset).toContain('type-raster');
    expect(recordTypeColors.vrt_dataset).toContain('type-vrt');
    expect(recordTypeColors.table).toContain('type-table');
    expect(recordTypeColors.collection).toBe(semanticBadgeColors.warning);
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

describe('experimentalBadgeColor', () => {
  it('uses amber palette with dark mode variant', () => {
    expect(experimentalBadgeColor).toContain('amber');
    expect(experimentalBadgeColor).toContain('dark:');
  });
});

describe('syntheticBadgeColor', () => {
  it('uses violet palette with dark mode variants', () => {
    expect(syntheticBadgeColor).toContain('violet');
    expect(syntheticBadgeColor).toContain('dark:');
  });
});
