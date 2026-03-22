export interface ProvenanceIdentityLabels {
  unknown: string;
  restricted: string;
  system: string;
}

export interface ProvenanceTimeOptions {
  fallbackRelative: string;
  fallbackAbsolute: string;
  locale?: string;
  now?: Date;
}

export interface ProvenanceTimeResult {
  relative: string;
  absolute: string;
  hasTimestamp: boolean;
}

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const MONTH_MS = 30 * DAY_MS;
const YEAR_MS = 365 * DAY_MS;

function normalizeToken(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

function parseTimestamp(value: string | Date | null | undefined): Date | null {
  if (!value) {
    return null;
  }

  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatRelativeTime(timestamp: Date, now: Date, locale: string): string {
  const deltaMs = now.getTime() - timestamp.getTime();
  const absoluteDeltaMs = Math.abs(deltaMs);
  const direction = deltaMs >= 0 ? -1 : 1;
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });

  if (absoluteDeltaMs < MINUTE_MS) {
    return rtf.format(0, 'second');
  }

  if (absoluteDeltaMs < HOUR_MS) {
    const minutes = Math.round(absoluteDeltaMs / MINUTE_MS);
    return rtf.format(direction * minutes, 'minute');
  }

  if (absoluteDeltaMs < DAY_MS) {
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
}

export function resolveProvenanceIdentity(
  value: string | null | undefined,
  labels: ProvenanceIdentityLabels,
): string {
  if (!value || !value.trim()) {
    return labels.unknown;
  }

  const trimmed = value.trim();
  const normalized = normalizeToken(trimmed);

  if (normalized === 'unknown') {
    return labels.unknown;
  }

  if (normalized === 'restricted user') {
    return labels.restricted;
  }

  if (normalized === 'system') {
    return labels.system;
  }

  return trimmed;
}

export function formatProvenanceTime(
  value: string | Date | null | undefined,
  {
    fallbackRelative,
    fallbackAbsolute,
    locale = 'en',
    now = new Date(),
  }: ProvenanceTimeOptions,
): ProvenanceTimeResult {
  const timestamp = parseTimestamp(value);
  if (!timestamp) {
    return {
      relative: fallbackRelative,
      absolute: fallbackAbsolute,
      hasTimestamp: false,
    };
  }

  return {
    relative: formatRelativeTime(timestamp, now, locale),
    absolute: new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(timestamp),
    hasTimestamp: true,
  };
}
