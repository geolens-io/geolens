import type { AttributeMetadataResponse } from '@/types/api';

export type ValueLabels = Record<string, string>;

/** Current coded-value labels per column; columns without any are left out. */
export function valueLabelsByField(
  attributes: readonly AttributeMetadataResponse[] | undefined,
): Map<string, ValueLabels> {
  const byField = new Map<string, ValueLabels>();
  for (const attribute of attributes ?? []) {
    if (attribute.is_current && attribute.value_labels) {
      byField.set(attribute.field_name, attribute.value_labels);
    }
  }
  return byField;
}

/** The label stored for a code, or undefined when the code has none. */
export function valueLabelFor(labels: ValueLabels | undefined, value: unknown): string | undefined {
  if (!labels || value === null || value === undefined) return undefined;
  const code = String(value);
  return Object.hasOwn(labels, code) ? labels[code] : undefined;
}
