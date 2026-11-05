import { useTranslation } from 'react-i18next';
import type { WidgetEditorProps } from '../contract';
import { isSortableColumn } from '@/lib/column-utils';
import { ColumnField, IntegerField, SelectField } from '../editor-fields';
import { MAX_PAGE_SIZE, MIN_PAGE_SIZE, type FeatureListConfig } from './definition';

// Select values can't be empty, so "none" stands for a column left out.
const NONE = '__none__';

export default function FeatureListEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<FeatureListConfig>) {
  const { t } = useTranslation('widgets');
  const optional = (value: string | null) => value ?? NONE;
  const options = [
    { value: NONE, label: t('editor.featureList.none') },
    ...columns.map((column) => ({ value: column.name, label: column.name })),
  ];
  const sortOptions = [
    options[0],
    ...columns.filter((column) => isSortableColumn(column.name, column.type)).map((column) => ({ value: column.name, label: column.name })),
  ];
  return (
    <div className="space-y-3">
      <ColumnField
        id={`${idPrefix}-title-column`}
        label={t('editor.featureList.title')}
        value={config.title_column}
        columns={columns}
        onChange={(title_column) => onChange({ ...config, title_column })}
      />
      <SelectField
        id={`${idPrefix}-subtitle`}
        label={t('editor.featureList.subtitle')}
        value={optional(config.subtitle_column)}
        options={options}
        onChange={(value) => onChange({ ...config, subtitle_column: value === NONE ? null : value })}
      />
      <SelectField
        id={`${idPrefix}-sort`}
        label={t('editor.featureList.sortBy')}
        value={optional(config.sort_column)}
        options={sortOptions}
        onChange={(value) => onChange({ ...config, sort_column: value === NONE ? null : value })}
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
