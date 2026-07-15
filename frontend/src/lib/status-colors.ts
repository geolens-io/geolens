/**
 * Single source of truth for all status-related colors (COMP-04).
 *
 * fix(#438): every recipe below is built from design tokens (DS-01). This file
 * previously hardcoded raw emerald/teal/amber/rose/violet Tailwind palettes —
 * about 35 of the app's 49 raw-palette uses — which meant "success" rendered
 * one green here and a different one through `<Badge variant="success">`.
 * The recipes now mirror `badge.tsx`'s AA-verified soft variants exactly, so a
 * status badge and a variant badge are the same color by construction.
 *
 * Values are Tailwind class strings rather than `<Badge variant>` names because
 * every call site composes them with additional classes (sizing, mono type).
 */

/**
 * Written as literals, never composed from a token name at runtime: Tailwind
 * scans source text, so an interpolated class never reaches the stylesheet.
 */
export const semanticBadgeColors = {
  warning: 'border-warning/30 bg-warning/10 text-warning',
  info: 'border-info/30 bg-info/10 text-info',
  success: 'border-success/30 bg-success/10 text-success',
  destructive: 'border-destructive/30 bg-destructive/10 text-destructive',
} as const;

export const jobStatusColors: Record<string, string> = {
  pending: semanticBadgeColors.warning,
  running: semanticBadgeColors.info,
  complete: semanticBadgeColors.success,
  failed: semanticBadgeColors.destructive,
  fanned_out: semanticBadgeColors.success,
};

export const userStatusColors: Record<string, string> = {
  pending: semanticBadgeColors.warning,
  active: semanticBadgeColors.success,
  suspended: semanticBadgeColors.warning,
  deactivated: 'border-border bg-muted text-muted-foreground',
};

export const visibilityColors: Record<string, string> = {
  public: semanticBadgeColors.success,
  internal: semanticBadgeColors.info,
  restricted: semanticBadgeColors.warning,
  private: semanticBadgeColors.destructive,
};

export function qualityScoreClasses(score: number): string {
  if (score >= 80) {
    return semanticBadgeColors.success;
  }
  if (score >= 60) {
    return 'border-border bg-secondary text-secondary-foreground';
  }
  return semanticBadgeColors.destructive;
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
  vector_dataset: 'border-type-vector/30 bg-type-vector-bg text-type-vector',
  raster_dataset: 'border-type-raster/30 bg-type-raster-bg text-type-raster',
  vrt_dataset: 'border-type-vrt/30 bg-type-vrt-bg text-type-vrt',
  table: 'border-type-table/30 bg-type-table-bg text-type-table',
  collection: semanticBadgeColors.warning,
  unknown: 'border-border bg-muted text-muted-foreground',
};

export const ingestionStatusColors: Record<string, string> = {
  draft: semanticBadgeColors.warning,
  ready: semanticBadgeColors.info,
  internal: 'border-border bg-muted text-muted-foreground',
  published: semanticBadgeColors.success,
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

export const experimentalBadgeColor = 'border-warning/50 text-warning';

/** Provenance marker, not a record type — hence its own token pair. */
export const syntheticBadgeColor =
  'border-synthetic/30 bg-synthetic-bg text-synthetic';

/**
 * Import file-entry lifecycle (upload → detect → commit → track). The
 * `committing` state deliberately uses the primary action color rather than a
 * status hue — it marks "acting on your request", not a health state.
 */
export const fileEntryStatusColors: Record<string, string> = {
  uploading: semanticBadgeColors.info,
  previewing: semanticBadgeColors.info,
  preview: semanticBadgeColors.success,
  committing: 'border-primary/30 bg-primary/10 text-primary',
  tracking: semanticBadgeColors.success,
  complete: semanticBadgeColors.success,
  'upload-failed': semanticBadgeColors.destructive,
  'commit-failed': semanticBadgeColors.destructive,
  failed: semanticBadgeColors.destructive,
};

export const vrtRasterStatusColors: Record<string, string> = {
  ready: 'border-success/50 text-success',
  regenerating: 'border-warning/50 text-warning',
  failed: 'border-destructive/50 text-destructive',
};
