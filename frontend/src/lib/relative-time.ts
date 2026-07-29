// chore(#835): the single relative-time formatter. Previously written out 4x
// (provenance-attribution, ReportEntryList, admin ApiKeySection, settings
// MyApiKeySection) with drifting unit ranges and fallbacks.

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const MONTH_MS = 30 * DAY_MS;
const YEAR_MS = 365 * DAY_MS;

export interface RelativeTimeFormatOptions {
  /** Cap the largest unit rendered. `'hour'` reproduces the problem-report
   *  list behavior (a session-scoped surface where "49 hours ago" beats
   *  switching to days). Default: no cap (up to years). */
  maxUnit?: 'hour' | 'year';
  /** Render exact second counts under a minute ("42 seconds ago") instead of
   *  clamping to "now". */
  exactSeconds?: boolean;
}

/**
 * Locale-aware relative time via `Intl.RelativeTimeFormat`.
 *
 * Returns `''` when Intl rejects the locale tag — callers render the absolute
 * timestamp (or nothing) instead of crashing.
 */
export function formatRelativeTime(
  timestamp: Date,
  now: Date,
  locale: string,
  options: RelativeTimeFormatOptions = {},
): string {
  const deltaMs = now.getTime() - timestamp.getTime();
  const absoluteDeltaMs = Math.abs(deltaMs);
  const direction = deltaMs >= 0 ? -1 : 1;

  try {
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });

    if (absoluteDeltaMs < MINUTE_MS) {
      return options.exactSeconds
        ? rtf.format(direction * Math.round(absoluteDeltaMs / 1000), 'second')
        : rtf.format(0, 'second');
    }

    if (absoluteDeltaMs < HOUR_MS) {
      const minutes = Math.round(absoluteDeltaMs / MINUTE_MS);
      return rtf.format(direction * minutes, 'minute');
    }

    if (absoluteDeltaMs < DAY_MS || options.maxUnit === 'hour') {
      const hours = Math.round(absoluteDeltaMs / HOUR_MS);
      return rtf.format(direction * hours, 'hour');
    }

    if (absoluteDeltaMs < MONTH_MS) {
      const days = Math.round(absoluteDeltaMs / DAY_MS);
      return rtf.format(direction * days, 'day');
    }

    if (absoluteDeltaMs < YEAR_MS) {
      const months = Math.round(absoluteDeltaMs / MONTH_MS);
      return rtf.format(direction * months, 'month');
    }

    const years = Math.round(absoluteDeltaMs / YEAR_MS);
    return rtf.format(direction * years, 'year');
  } catch {
    return '';
  }
}

/**
 * i18n-key "time ago" variant used by the API-key tables (admin + settings).
 * Renders via the `admin:apiKeys.*` keys — floor semantics ("1 hour ago" until
 * a full second hour has elapsed), unlike the Intl rounding above; that
 * difference is deliberate and pre-dates the consolidation.
 */
export function formatLastUsedRelativeTime(
  dateStr: string | null,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (!dateStr) return t('admin:apiKeys.neverUsed');
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / MINUTE_MS);
  if (minutes < 1) return t('admin:apiKeys.justNow');
  if (minutes < 60) return t('admin:apiKeys.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('admin:apiKeys.hoursAgo', { count: hours });
  const days = Math.floor(hours / 24);
  return t('admin:apiKeys.daysAgo', { count: days });
}
