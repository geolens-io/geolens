// Binary rounding noise from a SUM or AVG shows as a run of 0s or 9s and a stray
// digit or two at the end of the fraction (491.9000000000001). Only that shape is
// rounded, to the 15 significant digits a double carries. A genuine value of the
// same shape rounds too, so the result tables keep the exact value in each title.
const NOISE_TAIL = /\.\d*?(?:0{6,}|9{6,})\d{1,2}$/;

/** Display text for one cell of an AI chat query result. */
export function formatQueryCell(raw: unknown): string {
  if (raw == null) return '';
  const text = String(raw);
  if (typeof raw === 'number' && NOISE_TAIL.test(text)) return String(Number(raw.toPrecision(15)));
  return text;
}
