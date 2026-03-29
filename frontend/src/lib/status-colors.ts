/** Single source of truth for all status-related colors (COMP-04). */

export const semanticBadgeColors = {
  warning:
    'border-amber-300 bg-amber-100 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200',
  info:
    'border-teal-300 bg-teal-100 text-teal-950 dark:border-teal-900/60 dark:bg-teal-950/30 dark:text-teal-200',
  success:
    'border-emerald-300 bg-emerald-100 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200',
  destructive:
    'border-rose-300 bg-rose-100 text-rose-950 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200',
} as const;

export const jobStatusColors: Record<string, string> = {
  pending: semanticBadgeColors.warning,
  running: semanticBadgeColors.info,
  complete: semanticBadgeColors.success,
  failed: semanticBadgeColors.destructive,
};

export const userStatusColors: Record<string, string> = {
  pending: semanticBadgeColors.warning,
  active: semanticBadgeColors.success,
  deactivated: 'border-border bg-muted text-muted-foreground',
};

export const visibilityColors: Record<string, string> = {
  public: semanticBadgeColors.success,
  restricted: semanticBadgeColors.warning,
  private: semanticBadgeColors.destructive,
};

export function qualityScoreClasses(score: number): string {
  if (score >= 80) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200';
  }
  if (score >= 60) {
    return 'border-border bg-secondary text-secondary-foreground';
  }
  return 'border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200';
}

export const vrtGenerationColors: Record<string, string> = {
  completed: semanticBadgeColors.success,
  running: semanticBadgeColors.info,
  failed: semanticBadgeColors.destructive,
};

export const activeDotColor = {
  true:  'bg-success',
  false: 'bg-destructive',
} as const;

export const recordTypeColors: Record<string, string> = {
  collection: semanticBadgeColors.warning,
  vector_dataset: semanticBadgeColors.info,
  raster_dataset: semanticBadgeColors.success,
  vrt_dataset: 'border-violet-300 bg-violet-100 text-violet-950 dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-200',
  table: 'border-orange-300 bg-orange-100 text-orange-950 dark:border-orange-900/60 dark:bg-orange-950/30 dark:text-orange-200',
  unknown: 'border-orange-300 bg-orange-100 text-orange-950 dark:border-orange-900/60 dark:bg-orange-950/30 dark:text-orange-200',
};

export const ingestionStatusColors: Record<string, string> = {
  draft: semanticBadgeColors.warning,
  ready: semanticBadgeColors.info,
  internal: 'border-border bg-muted text-muted-foreground',
};

export const validationLevelColors = {
  error: 'text-destructive',
  warning: 'text-warning',
  success: 'text-success',
} as const;

export const healthDotColors = {
  healthy: 'bg-success',
  unhealthy: 'bg-destructive',
  unknown: 'bg-muted-foreground',
} as const;

export const experimentalBadgeColor =
  'border-amber-500/50 text-amber-600 dark:text-amber-400';

export const syntheticBadgeColor =
  'border-violet-300 bg-violet-100 text-violet-950 dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-200';

export const vrtRasterStatusColors: Record<string, string> = {
  ready: 'border-success/50 text-success',
  regenerating: 'border-warning/50 text-warning',
  failed: 'border-destructive/50 text-destructive',
};
