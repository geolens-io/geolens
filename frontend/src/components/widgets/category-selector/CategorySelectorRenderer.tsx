import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Checkbox } from '@/components/ui/checkbox';
import { columnName, type SelectionValue, type WidgetRenderProps } from '../contract';
import { selectedValues } from '../selection';
import { categoryLabel, isBlankValue, labelOfColumn, useCategoryRows } from '../value-counts';
import type { CategorySelectorConfig } from './definition';

interface SelectorOption {
  key: SelectionValue;
  keys: readonly SelectionValue[];
  label: string;
  /** The value's count as text; undefined for a pick the current numbers no longer list. */
  count?: string;
}

const OPTION_CLASS = 'flex items-center gap-2 rounded-sm px-1 py-0.5 text-sm hover:bg-muted';

/**
 * The column's most frequent values with their counts, as checkboxes, or as
 * radio buttons headed by "All" when the reader picks one value. Where the
 * host doesn't link widgets, as in the Builder's preview, the inputs are
 * disabled.
 */
export default function CategorySelectorRenderer({
  config,
  data,
  selection,
  onSelect,
  columnLabel,
  valueLabel,
}: WidgetRenderProps<CategorySelectorConfig>) {
  const { t } = useTranslation('widgets');
  const labelOf = labelOfColumn(valueLabel, config.column);
  const { rows, other } = useCategoryRows(data, labelOf);
  const idPrefix = useId();
  const picked = selectedValues(selection, config.column);

  if (!rows || rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{t(rows ? 'noRows' : 'noData')}</p>;
  }

  // Another widget's pick can leave a picked value out of the list; it stays, so it can be cleared here.
  // Held blank spellings join the listed no-value row, so one action clears them all.
  const missing = picked.filter((value) => !rows.some((row) => row.keys.includes(value)));
  const missingBlanks = missing.filter(isBlankValue);
  const blankRow = missingBlanks.length > 0 ? rows.find((row) => isBlankValue(row.key)) : undefined;
  const options: SelectorOption[] = [
    ...rows.map((row) => ({
      key: row.key,
      keys: row === blankRow ? [...row.keys, ...missingBlanks] : row.keys,
      label: row.label,
      count: row.text,
    })),
    ...missing
      .filter((value) => !isBlankValue(value))
      .map((value) => ({ key: value, keys: [value], label: categoryLabel(value, t, labelOf) })),
    ...(missingBlanks.length > 0 && !blankRow
      ? [{ key: missingBlanks[0], keys: missingBlanks, label: categoryLabel(missingBlanks[0], t, labelOf) }]
      : []),
  ];
  const disabled = !onSelect;
  const choose = (keys: readonly SelectionValue[], checked: boolean) => {
    const values = config.multiple
      ? checked
        ? [...picked, ...keys]
        : picked.filter((value) => !keys.includes(value))
      : [...keys];
    const label = [...new Set(values.map((value) => categoryLabel(value, t, labelOf)))].join(', ');
    onSelect?.(values.length > 0 ? { column: config.column, label, values } : null);
  };

  return (
    <fieldset className="space-y-1" disabled={disabled}>
      <legend className="sr-only">
        {t('types.category_selector.summary', { column: (columnLabel ?? columnName)(config.column) })}
      </legend>
      <ul className="max-h-64 space-y-0.5 overflow-y-auto">
        {!config.multiple && (
          <li className={OPTION_CLASS}>
            <input
              id={`${idPrefix}-all`}
              type="radio"
              name={idPrefix}
              className="size-4 shrink-0 accent-primary"
              checked={picked.length === 0}
              onChange={() => onSelect?.(null)}
            />
            <label htmlFor={`${idPrefix}-all`} className="flex-1">
              {t('types.category_selector.all')}
            </label>
          </li>
        )}
        {options.map((option, index) => {
          const id = `${idPrefix}-${index}`;
          const checked = option.keys.some((key) => picked.includes(key));
          return (
            <li key={index} className={OPTION_CLASS}>
              {config.multiple ? (
                <Checkbox
                  id={id}
                  checked={checked}
                  disabled={disabled}
                  onCheckedChange={(next) => choose(option.keys, next === true)}
                />
              ) : (
                <input
                  id={id}
                  type="radio"
                  name={idPrefix}
                  className="size-4 shrink-0 accent-primary"
                  checked={checked}
                  onChange={(event) => choose(option.keys, event.target.checked)}
                />
              )}
              <label htmlFor={id} className="flex-1 break-words">
                {option.label}
              </label>
              {option.count !== undefined && (
                <span className="text-xs tabular-nums text-muted-foreground">{option.count}</span>
              )}
            </li>
          );
        })}
      </ul>
      {other !== undefined && (
        <p className="text-xs text-muted-foreground">{t('types.category_selector.other', { value: other })}</p>
      )}
    </fieldset>
  );
}
