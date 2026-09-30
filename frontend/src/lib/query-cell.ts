// Binary rounding noise from a SUM or AVG shows as a run of 0s or 9s and a stray
// digit or two at the end of a number with 15 or more significant digits
// (491.9000000000001, 9.99999999999998). The number is rounded where the run
// starts. A genuine value of the same shape rounds too, so the result tables keep
// the exact value in each cell's title.
const NOISE_TAIL = /^(-?\d+\.(\d*?))(?:0{6,}|9{6,})\d{1,2}(e[+-]\d+)?$/;
const MIN_NOISY_DIGITS = 15;

/** Display text for one cell of an AI chat query result. */
export function formatQueryCell(raw: unknown): string {
  if (raw == null) return '';
  const text = String(raw);
  const match = typeof raw === 'number' ? NOISE_TAIL.exec(text) : null;
  if (!match) return text;
  const exponent = match[3] ?? '';
  const mantissa = text.slice(0, text.length - exponent.length);
  const significant = mantissa.replace(/^-?[0.]*/, '').replace('.', '');
  if (significant.length < MIN_NOISY_DIGITS) return text;
  return String(Number(Number(mantissa).toFixed(match[2].length) + exponent));
}
