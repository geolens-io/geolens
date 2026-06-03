import { formatRelativeTime } from './provenance-attribution';

export type QualityCadence = 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'annually' | 'unknown';
export type QualityFreshnessState = 'fresh' | 'stale' | 'missing';

export interface DeriveQualityFreshnessOptions {
  computedAt?: string | null;
  updateFrequency?: string | null;
  now?: Date;
  locale?: string;
}

export interface QualityFreshnessResult {
  state: QualityFreshnessState;
  cadence: QualityCadence;
  absoluteTimestamp: string | null;
  relativeAge: string | null;
  isStale: boolean;
}

const MS_IN_MINUTE = 60 * 1000;
const MS_IN_HOUR = 60 * MS_IN_MINUTE;
const MS_IN_DAY = 24 * MS_IN_HOUR;

const cadencePolicies: Record<QualityCadence, { staleAfterMs: number }> = {
  daily: {
    staleAfterMs: 2 * MS_IN_DAY,
  },
  weekly: {
    staleAfterMs: 14 * MS_IN_DAY,
  },
  monthly: {
    staleAfterMs: 62 * MS_IN_DAY,
  },
  quarterly: {
    staleAfterMs: 186 * MS_IN_DAY,
  },
  annually: {
    staleAfterMs: 550 * MS_IN_DAY,
  },
  unknown: {
    staleAfterMs: 45 * MS_IN_DAY,
  },
};

function normalizeFrequency(value: string | null | undefined): QualityCadence {
  if (!value) return 'unknown';

  const normalized = value.toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();

  if (/(daily|every day|day)/.test(normalized)) return 'daily';
  if (/(weekly|every week|week)/.test(normalized)) return 'weekly';
  if (/(monthly|every month|month)/.test(normalized)) return 'monthly';
  if (/(quarterly|every quarter|quarter)/.test(normalized)) return 'quarterly';
  if (/(annually|annual|yearly|every year|year)/.test(normalized)) return 'annually';

  return 'unknown';
}

function formatAbsoluteTimestamp(date: Date, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function deriveQualityFreshness({
  computedAt,
  updateFrequency,
  now = new Date(),
  locale = 'en',
}: DeriveQualityFreshnessOptions): QualityFreshnessResult {
  const cadence = normalizeFrequency(updateFrequency);
  const cadencePolicy = cadencePolicies[cadence];

  if (!computedAt) {
    return {
      state: 'missing',
      cadence,
      absoluteTimestamp: null,
      relativeAge: null,
      isStale: false,
    };
  }

  const computedDate = new Date(computedAt);
  if (Number.isNaN(computedDate.getTime())) {
    return {
      state: 'missing',
      cadence,
      absoluteTimestamp: null,
      relativeAge: null,
      isStale: false,
    };
  }

  const ageMs = now.getTime() - computedDate.getTime();
  const isStale = ageMs > cadencePolicy.staleAfterMs;
  const state: QualityFreshnessState = isStale ? 'stale' : 'fresh';

  return {
    state,
    cadence,
    absoluteTimestamp: formatAbsoluteTimestamp(computedDate, locale),
    relativeAge: formatRelativeTime(computedDate, now, locale),
    isStale,
  };
}
