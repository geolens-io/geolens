import { useTranslation } from 'react-i18next';
import type { WidgetEditorProps } from '../contract';
import { isListableColumn, isSortableColumn } from '@/lib/column-utils';
import { ColumnField, IntegerField, SelectField } from '../editor-fields';
import { MAX_PAGE_SIZE, MIN_PAGE_SIZE, type FeatureListConfig } from './definition';

// Option values carry a prefix so a column named like the "none" choice stays selectable.
const NONE = 'none';
const COLUMN = 'column:';
const encode = (name: string | null) => (name === null ? NONE : `${COLUMN}${name}`);
const decode = (value: string) => (value.startsWith(COLUMN) ? value.slice(COLUMN.length) : null);

export default function FeatureListEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<FeatureListConfig>) {
  const { t } = useTranslation('widgets');
  const listable = columns.filter((column) => isListableColumn(column.name, column.type));
  const choices = (from: typeof columns) => [
    { value: NONE, label: t('editor.featureList.none') },
    ...from.map((column) => ({ value: encode(column.name), label: column.name })),
  ];
  const options = choices(listable);
  const sortOptions = choices(listable.filter((column) => isSortableColumn(column.name, column.type)));
  return (
    <div className="space-y-3">
      <ColumnField
        id={`${idPrefix}-title-column`}
        label={t('editor.featureList.title')}
        value={config.title_column}
        columns={listable}
        onChange={(title_column) => onChange({ ...config, title_column })}
      />
      <SelectField
        id={`${idPrefix}-subtitle`}
        label={t('editor.featureList.subtitle')}
        value={encode(config.subtitle_column)}
        options={options}
        onChange={(value) => onChange({ ...config, subtitle_column: decode(value) })}
      />
      <SelectField
        id={`${idPrefix}-sort`}
        label={t('editor.featureList.sortBy')}
        value={encode(config.sort_column)}
        options={sortOptions}
        onChange={(value) => onChange({ ...config, sort_column: decode(value) })}
      />
      <SelectField
        id={`${idPrefix}-direction`}
        label={t('editor.featureList.direction')}
        value={config.sort}
        options={[
          { value: 'asc', label: t('editor.featureList.ascending') },
          { value: 'desc', label: t('editor.featureList.descending') },
        ]}
        onChange={(sort) => onChange({ ...config, sort: sort === 'desc' ? 'desc' : 'asc' })}
      />
      <IntegerField
        id={`${idPrefix}-page-size`}
        label={t('editor.featureList.pageSize')}
        value={config.page_size}
        min={MIN_PAGE_SIZE}
        max={MAX_PAGE_SIZE}
        onChange={(page_size) => onChange({ ...config, page_size })}
      />
    </div>
  );
}
