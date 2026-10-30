import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import { selectedValues } from '../selection';
import { useCategoryRows } from '../value-counts';
import { ValueTable } from '../ValueTable';
import type { CategorySelectorConfig } from './definition';

/** The values and their counts as a table, with the reader's picks marked. */
export function CategorySelectorFallback({ config, data, selection }: WidgetRenderProps<CategorySelectorConfig>) {
  const { t } = useTranslation('widgets');
  const { rows, other } = useCategoryRows(data);
  const picked = selectedValues(selection, config.column);
  return (
    <ValueTable
      caption={t('types.category_selector.summary', { column: config.column })}
      labelHeader={config.column}
      valueHeader={t('stats.count')}
      rows={rows?.map((row) => ({ ...row, picked: picked.includes(row.key) }))}
      other={other}
    />
  );
}
