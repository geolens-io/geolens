import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { columnName, type SelectionValue, type WidgetRenderProps } from '../contract';
import { selectedValues } from '../selection';
import { categoryLabel, labelOfColumn, useCategoryRows } from '../value-counts';
import type { CategorySelectorConfig } from './definition';

interface SelectorOption {
  key: SelectionValue;
  label: string;
  /** The value's count as text; undefined for a pick the current numbers no longer list. */
  count?: string;
}

const OPTION_CLASS = 'flex items-center gap-2 rounded-sm px-1 py-0.5 text-sm hover:bg-muted';
/** How many values the list shows before the reader asks for the rest. */
const COLLAPSED_OPTIONS = 10;

/**
 * The column's most frequent values with their counts, as checkboxes, or as
 * radio buttons headed by "All" when the reader picks one value. The first
 * values and any picked one are listed, and a button shows the rest. Where
 * the host doesn't link widgets, as in the Builder's preview, the inputs are
 * disabled and the button still works.
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
  const [expanded, setExpanded] = useState(false);
  const picked = selectedValues(selection, config.column);

  if (!rows || rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{t(rows ? 'noRows' : 'noData')}</p>;
  }

  // Another widget's pick can leave a picked value out of the list; it stays, so it can be cleared here.
  const options: SelectorOption[] = [
    ...rows.map((row) => ({ key: row.key, label: row.label, count: row.text })),
    ...picked
      .filter((value) => !rows.some((row) => row.key === value))
      .map((value) => ({ key: value, label: categoryLabel(value, t, labelOf) })),
  ];
  const shown = options.filter(
    (option, index) => expanded || index < COLLAPSED_OPTIONS || picked.includes(option.key),
  );
  // Picked values can keep every row listed while the list is folded.
  const allShown = shown.length === options.length;
  const disabled = !onSelect;
  const choose = (key: SelectionValue, checked: boolean) => {
    const values = config.multiple
      ? checked
        ? [...picked, key]
        : picked.filter((value) => value !== key)
      : [key];
    const label = values.map((value) => categoryLabel(value, t, labelOf)).join(', ');
    onSelect?.(values.length > 0 ? { column: config.column, label, values } : null);
  };

  return (
    <div className="space-y-1">
      <fieldset disabled={disabled}>
        <legend className="sr-only">
          {t('types.category_selector.summary', { column: (columnLabel ?? columnName)(config.column) })}
        </legend>
        <ul id={`${idPrefix}-options`} className="space-y-0.5">
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
          {shown.map((option) => {
            const id = `${idPrefix}-${options.indexOf(option)}`;
            const checked = picked.includes(option.key);
            return (
              <li key={id} className={OPTION_CLASS}>
                {config.multiple ? (
                  <Checkbox
                    id={id}
                    checked={checked}
                    disabled={disabled}
                    onCheckedChange={(next) => choose(option.key, next === true)}
                  />
                ) : (
                  <input
                    id={id}
                    type="radio"
                    name={idPrefix}
                    className="size-4 shrink-0 accent-primary"
                    checked={checked}
                    onChange={(event) => choose(option.key, event.target.checked)}
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
      </fieldset>
      {options.length > COLLAPSED_OPTIONS && (
        <Button
          type="button"
          variant="link"
          size="sm"
          className="px-1"
          aria-expanded={allShown}
          aria-controls={`${idPrefix}-options`}
          onClick={() => setExpanded(!allShown)}
        >
          {allShown
            ? t('types.category_selector.showFewer')
            : t('types.category_selector.showMore', { count: options.length - shown.length })}
        </Button>
      )}
      {other !== undefined && (
        <p className="text-xs text-muted-foreground">{t('types.category_selector.other', { value: other })}</p>
      )}
    </div>
  );
}
