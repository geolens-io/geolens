import { useTranslation } from 'react-i18next';
import { columnName, type WidgetRenderProps } from '../contract';
import { selectedValues } from '../selection';
import { useCategoryRows } from '../value-counts';
import { ValueTable } from '../ValueTable';
import type { CategorySelectorConfig } from './definition';

/** The values and their counts as a table, with the reader's picks marked. */
export function CategorySelectorFallback({
  config,
  data,
  selection,
  columnLabel,
}: WidgetRenderProps<CategorySelectorConfig>) {
  const { t } = useTranslation('widgets');
  const { rows, other } = useCategoryRows(data);
  const column = (columnLabel ?? columnName)(config.column);
  const picked = selectedValues(selection, config.column);
  return (
    <ValueTable
      caption={t('types.category_selector.summary', { column })}
      labelHeader={column}
      valueHeader={t('stats.count')}
      rows={rows?.map((row) => ({ ...row, picked: picked.includes(row.key) }))}
      other={other}
    />
  );
}
