import { formatRelativeTime } from './relative-time';

// chore(#835): the Intl relative-time implementation moved to
// `lib/relative-time.ts` (it was written out 4x across the app). Re-exported
// here so existing importers (e.g. quality-freshness) keep their contract.
export { formatRelativeTime } from './relative-time';

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
