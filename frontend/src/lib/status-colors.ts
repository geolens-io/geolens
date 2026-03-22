/** Single source of truth for all status-related colors (COMP-04). */

export const semanticBadgeColors = {
  warning:
    'border-amber-300 bg-amber-100 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200',
  info:
    'border-sky-300 bg-sky-100 text-sky-950 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200',
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
} as const;

export const userStatusColors: Record<string, string> = {
  pending: semanticBadgeColors.warning,
  active: semanticBadgeColors.success,
} as const;

export const visibilityColors: Record<string, string> = {
  public: semanticBadgeColors.success,
  restricted: semanticBadgeColors.warning,
  private: semanticBadgeColors.destructive,
} as const;

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
} as const;

export const activeDotColor = {
  true:  'bg-success',
  false: 'bg-destructive',
} as const;
