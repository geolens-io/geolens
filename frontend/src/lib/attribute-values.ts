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
      return Number.isInteger(n) ? { ok: true, value: n } : { ok: false };
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
    case 'datetime-local':
      // ISO strings, same wire shape AttributeForm sends.
      return { ok: true, value: trimmed };
    default:
      // text keeps the raw, untrimmed value.
      return { ok: true, value: raw };
  }
}
