import i18n from '@/i18n/i18n';

/** Abbreviate large numbers for legend readability (e.g. 8918925.75 → "8.9M") */
function formatBreakValue(v: number): string {
  const locale = i18n.language;
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}M`;
  if (abs >= 1_000) return `${(v / 1_000).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}K`;
  if (Number.isInteger(v)) return v.toLocaleString(locale);
  return v.toLocaleString(locale, { maximumFractionDigits: 2 });
}

/** Build a human-readable label for a graduated break range. */
export function breakLabel(i: number, breaks: number[]): string {
  if (i === 0) return `< ${formatBreakValue(breaks[0])}`;
  if (i === breaks.length) return `\u2265 ${formatBreakValue(breaks[breaks.length - 1])}`;
  return `${formatBreakValue(breaks[i - 1])} \u2013 ${formatBreakValue(breaks[i])}`;
}
