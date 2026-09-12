/** Shared column-type → editor-input mapping and free-text coercion for
 * feature attribute editors (drawing AttributeForm + dataset AttributeTable).
 */

export type AttributeInputType =
  | 'number-int'
  | 'number-float'
  | 'checkbox'
  | 'date'
  | 'datetime-local'
  | 'text';

export function getAttributeInputType(colType: string): AttributeInputType {
  const t = colType.toLowerCase();
  if (t === 'integer' || t === 'bigint') return 'number-int';
  if (['double precision', 'real', 'numeric'].includes(t)) return 'number-float';
  if (t === 'boolean') return 'checkbox';
  if (t === 'date') return 'date';
  if (t === 'timestamp' || t === 'timestamptz' || t.startsWith('timestamp')) return 'datetime-local';
  return 'text';
}

function isTimezoneAwareTimestamp(colType: string): boolean {
  const type = colType.toLowerCase();
  if (type.includes('without time zone')) return false;
  // The layer schema API's short `timestamp` type creates TIMESTAMPTZ columns.
  return type === 'timestamp' || type.startsWith('timestamptz') || type.includes('with time zone');
}

function hasTimezoneOffset(value: string): boolean {
  return /(?:z|[+-]\d{2}:?\d{2})$/i.test(value);
}

function localTimestampWithOffset(raw: string): string | null {
  const match = raw.match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/,
  );
  if (!match) return null;
  const [, year, month, day, hour, minute, second = '0', fraction = ''] = match;
  const milliseconds = Number(fraction.padEnd(3, '0').slice(0, 3));
  const instant = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
    milliseconds,
  );
  if (Number(year) < 100) instant.setFullYear(Number(year));
  if (
    instant.getFullYear() !== Number(year)
    || instant.getMonth() !== Number(month) - 1
    || instant.getDate() !== Number(day)
    || instant.getHours() !== Number(hour)
    || instant.getMinutes() !== Number(minute)
    || instant.getSeconds() !== Number(second)
    || instant.getMilliseconds() !== milliseconds
  ) return null;
  const offsetMinutes = instant.getTimezoneOffset();
  const sign = offsetMinutes <= 0 ? '+' : '-';
  const absoluteOffset = Math.abs(offsetMinutes);
  const hours = String(Math.floor(absoluteOffset / 60)).padStart(2, '0');
  const minutes = String(absoluteOffset % 60).padStart(2, '0');
  return `${raw}${sign}${hours}:${minutes}`;
}

function dateTimeLocalValue(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  second: number,
  millisecond: number,
): string {
  const pad = (part: number) => String(part).padStart(2, '0');
  const minuteValue = [
    year,
    '-',
    pad(month),
    '-',
    pad(day),
    'T',
    pad(hour),
    ':',
    pad(minute),
  ].join('');
  return second === 0 && millisecond === 0
    ? minuteValue
    : `${minuteValue}:${pad(second)}${
      millisecond === 0 ? '' : `.${String(millisecond).padStart(3, '0')}`
    }`;
}

function naiveDateTimeLocalValue(text: string): string | null {
  const match = text.match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?/,
  );
  if (!match) return null;
  const [, year, month, day, hour, minute, second = '0', fraction = ''] = match;
  return dateTimeLocalValue(
    Number(year),
    Number(month),
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
    Number(fraction.padEnd(3, '0').slice(0, 3)),
  );
}

/** Convert an API attribute value to the representation required by its HTML input. */
export function formatAttributeInputValue(value: unknown, colType: string): string {
  const text = String(value);
  if (getAttributeInputType(colType) !== 'datetime-local') return text;

  if (!isTimezoneAwareTimestamp(colType)) {
    return naiveDateTimeLocalValue(text) ?? text;
  }

  const instant = new Date(text);
  if (Number.isNaN(instant.getTime())) return text;
  return dateTimeLocalValue(
    instant.getFullYear(),
    instant.getMonth() + 1,
    instant.getDate(),
    instant.getHours(),
    instant.getMinutes(),
    instant.getSeconds(),
    instant.getMilliseconds(),
  );
}

/** Convert an HTML datetime-local value to the timestamp column's wire representation. */
export function serializeAttributeInputValue(
  raw: string,
  colType: string,
  initialValue?: unknown,
): string {
  if (
    initialValue !== undefined
    && initialValue !== null
    && raw === formatAttributeInputValue(initialValue, colType)
  ) {
    return String(initialValue);
  }

  if (!isTimezoneAwareTimestamp(colType)) return raw;
  return localTimestampWithOffset(raw) ?? raw;
}

const TRUE_WORDS = new Set(['true', 't', '1', 'yes', 'y']);
const FALSE_WORDS = new Set(['false', 'f', '0', 'no', 'n']);

/**
 * Coerce a free-text cell value to the column's wire type.
 *
 * fix(#458 E-03): the attribute table's inline editor is a plain text input;
 * sending its raw string into a typed Postgres column made every non-text
 * cell edit fail. Empty input means NULL (matches the pre-fix `value || null`
 * contract). `ok: false` means the text is not representable in the column
 * type and must not be sent.
 */
export function coerceAttributeValue(
  raw: string,
  colType: string,
): { ok: true; value: unknown } | { ok: false } {
  const trimmed = raw.trim();
  if (trimmed === '') return { ok: true, value: null };

  switch (getAttributeInputType(colType)) {
    case 'number-int': {
      const n = Number(trimmed);
      // isSafeInteger, not isInteger: beyond 2^53 Number silently rounds
      // (9007199254740993 -> ...992), which would corrupt identifier-like
      // bigint values on save instead of rejecting them.
      return Number.isSafeInteger(n) ? { ok: true, value: n } : { ok: false };
    }
    case 'number-float': {
      const n = Number(trimmed);
      return Number.isNaN(n) ? { ok: false } : { ok: true, value: n };
    }
    case 'checkbox': {
      const w = trimmed.toLowerCase();
      if (TRUE_WORDS.has(w)) return { ok: true, value: true };
      if (FALSE_WORDS.has(w)) return { ok: true, value: false };
      return { ok: false };
    }
    case 'date':
      return { ok: true, value: trimmed };
    case 'datetime-local': {
      if (!isTimezoneAwareTimestamp(colType)) return { ok: true, value: trimmed };
      if (hasTimezoneOffset(trimmed)) {
        return Number.isNaN(new Date(trimmed).getTime())
          ? { ok: false }
          : { ok: true, value: trimmed };
      }
      const timestamp = localTimestampWithOffset(trimmed);
      return timestamp === null ? { ok: false } : { ok: true, value: timestamp };
    }
    default:
      // text keeps the raw, untrimmed value.
      return { ok: true, value: raw };
  }
}
