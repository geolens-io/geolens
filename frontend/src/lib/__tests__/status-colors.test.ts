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
    expect(result).not.toContain('warning');
  });

  it('returns the success token for score 85 (80+ range)', () => {
    expect(qualityScoreClasses(85)).toBe(semanticBadgeColors.success);
  });

  it('returns the destructive token for score 40 (below 60)', () => {
    expect(qualityScoreClasses(40)).toBe(semanticBadgeColors.destructive);
  });

  it('returns the success token for score 95 (high score)', () => {
    expect(qualityScoreClasses(95)).toBe(semanticBadgeColors.success);
  });

  it('returns the destructive token for score 55 (just below 60)', () => {
    expect(qualityScoreClasses(55)).toBe(semanticBadgeColors.destructive);
  });

  it('returns the success token for exact boundary 80', () => {
    expect(qualityScoreClasses(80)).toBe(semanticBadgeColors.success);
  });

  it('returns neutral styling for exact boundary 60', () => {
    expect(qualityScoreClasses(60)).toContain('bg-secondary');
  });

  it('returns the destructive token for score 59 (just below 60)', () => {
    expect(qualityScoreClasses(59)).toBe(semanticBadgeColors.destructive);
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
  it('uses the warning token', () => {
    expect(experimentalBadgeColor).toContain('warning');
  });
});

describe('syntheticBadgeColor', () => {
  it('uses the synthetic provenance token', () => {
    expect(syntheticBadgeColor).toContain('synthetic');
  });
});

// fix(#435): DS-01 — this file is the app's declared "single source of truth for
// status colors", so it is also the right place to guard against a raw Tailwind
// palette creeping back in. Every export must be token-driven.
describe('token discipline (DS-01)', () => {
  const RAW_PALETTES = /\b(emerald|teal|amber|rose|violet|sky|lime|fuchsia|cyan|indigo)-\d{2,3}\b/;

  const allRecipes = [
    ...Object.values(semanticBadgeColors),
    ...Object.values(jobStatusColors),
    ...Object.values(userStatusColors),
    ...Object.values(visibilityColors),
    ...Object.values(vrtGenerationColors),
    ...Object.values(activeDotColor),
    ...Object.values(recordTypeColors),
    ...Object.values(ingestionStatusColors),
    ...Object.values(validationLevelColors),
    ...Object.values(healthDotColors),
    ...Object.values(vrtRasterStatusColors),
    experimentalBadgeColor,
    syntheticBadgeColor,
    qualityScoreClasses(95),
    qualityScoreClasses(70),
    qualityScoreClasses(20),
  ];

  it.each(allRecipes)('%s contains no raw Tailwind palette', (recipe) => {
    expect(recipe).not.toMatch(RAW_PALETTES);
  });

  it('renders one success green everywhere it appears', () => {
    const successRecipes = [
      semanticBadgeColors.success,
      jobStatusColors.complete,
      jobStatusColors.fanned_out,
      userStatusColors.active,
      visibilityColors.public,
      vrtGenerationColors.completed,
      ingestionStatusColors.published,
      qualityScoreClasses(95),
    ];
    expect(new Set(successRecipes).size).toBe(1);
  });
});
