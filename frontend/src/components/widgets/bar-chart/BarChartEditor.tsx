import { useTranslation } from 'react-i18next';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { isAggregateNumeric, isTextColumn } from '@/lib/column-utils';
import type { WidgetColumn, WidgetEditorProps } from '../contract';
import {
  ColumnField,
  IntegerField,
  isDateColumn,
  LayerColorsField,
  SelectField,
  StatColumnFields,
} from '../editor-fields';
import { categoryColumn } from '../initial-columns';
import {
  DATE_BUCKETS,
  MAX_BARS,
  MAX_FIELDS,
  type BarChartConfig,
  type CategoryBarChartConfig,
  type DateBarChartConfig,
  type DateBucket,
  type FeatureBarChartConfig,
  type FieldsBarChartConfig,
} from './definition';

type Mode = NonNullable<BarChartConfig['mode']>;
const MODES: readonly Mode[] = ['category', 'date', 'by_feature', 'by_fields'];

/** A starting config for `mode` on the layer's columns, keeping the bar limit. */
function configForMode(mode: Mode, config: BarChartConfig, columns: readonly WidgetColumn[]): BarChartConfig {
  const limit = 'limit' in config ? config.limit : 10;
  const first = (pick: (column: WidgetColumn) => boolean) => columns.find(pick)?.name ?? '';
  switch (mode) {
    case 'date':
      return {
        mode,
        column: first((column) => isDateColumn(column.type)),
        date_bucket: 'month',
        stat: 'count',
        stat_column: null,
        limit,
      };
    case 'by_feature':
      return {
        mode,
        label_column: categoryColumn(columns).column ?? first((column) => isTextColumn(column.type)),
        value_column: first((column) => isAggregateNumeric(column.type)),
        sort: 'desc',
        limit,
      };
    case 'by_fields':
      return { mode, fields: [first((column) => isAggregateNumeric(column.type))].filter(Boolean), stat: 'sum' };
    default:
      return { column: categoryColumn(columns).column ?? '', stat: 'count', stat_column: null, limit };
  }
}

function CategoryFields({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<CategoryBarChartConfig | DateBarChartConfig>) {
  const { t } = useTranslation('widgets');
  const date = config.mode === 'date';
  return (
    <>
      <ColumnField
        id={`${idPrefix}-column`}
        label={t(date ? 'editor.dateColumn' : 'editor.groupBy')}
        value={config.column}
        columns={date ? columns.filter((column) => isDateColumn(column.type)) : columns}
        onChange={(column) => onChange({ ...config, column })}
      />
      {config.mode === 'date' && (
        <SelectField
          id={`${idPrefix}-bucket`}
          label={t('editor.dateBucket')}
          value={config.date_bucket}
          options={DATE_BUCKETS.map((bucket) => ({ value: bucket, label: t(`editor.dateBuckets.${bucket}`) }))}
          onChange={(bucket) => onChange({ ...config, date_bucket: bucket as DateBucket })}
        />
      )}
      <StatColumnFields
        idPrefix={idPrefix}
        stat={config.stat}
        column={config.stat_column}
        columns={columns}
        onChange={(stat, statColumn) => onChange({ ...config, stat, stat_column: statColumn })}
      />
      <IntegerField
        id={`${idPrefix}-limit`}
        label={t('editor.limit')}
        value={config.limit}
        min={1}
        max={MAX_BARS}
        onChange={(limit) => onChange({ ...config, limit })}
      />
    </>
  );
}

function FeatureFields({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<FeatureBarChartConfig>) {
  const { t } = useTranslation('widgets');
  return (
    <>
      <ColumnField
        id={`${idPrefix}-label-column`}
        label={t('editor.labelField')}
        value={config.label_column}
        columns={columns}
        onChange={(label_column) => onChange({ ...config, label_column })}
      />
      <ColumnField
        id={`${idPrefix}-value-column`}
        label={t('editor.valueField')}
        value={config.value_column}
        columns={columns.filter((column) => isAggregateNumeric(column.type))}
        onChange={(value_column) => onChange({ ...config, value_column })}
      />
      <SelectField
        id={`${idPrefix}-sort`}
        label={t('editor.sortOrder')}
        value={config.sort}
        options={[
          { value: 'desc', label: t('editor.sortDesc') },
          { value: 'asc', label: t('editor.sortAsc') },
        ]}
        onChange={(sort) => onChange({ ...config, sort: sort as 'asc' | 'desc' })}
      />
      <IntegerField
        id={`${idPrefix}-limit`}
        label={t('editor.limit')}
        value={config.limit}
        min={1}
        max={MAX_BARS}
        onChange={(limit) => onChange({ ...config, limit })}
      />
    </>
  );
}

function FieldsFields({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<FieldsBarChartConfig>) {
  const { t } = useTranslation('widgets');
  const numeric = columns.filter((column) => isAggregateNumeric(column.type));
  const toggle = (name: string, on: boolean) => {
    const fields = on ? [...config.fields, name] : config.fields.filter((field) => field !== name);
    // A chart with no fields can't be saved, and the last one has nothing to give up to.
    if (fields.length > 0 && fields.length <= MAX_FIELDS) onChange({ ...config, fields });
  };
  return (
    <>
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium">{t('editor.fields')}</legend>
        {numeric.map((column) => {
          const checked = config.fields.includes(column.name);
          return (
            <div key={column.name} className="flex items-center gap-2">
              <Checkbox
                id={`${idPrefix}-field-${column.name}`}
                checked={checked}
                disabled={(checked && config.fields.length === 1) || (!checked && config.fields.length >= MAX_FIELDS)}
                onCheckedChange={(next) => toggle(column.name, next === true)}
              />
              <Label className="text-xs font-normal" htmlFor={`${idPrefix}-field-${column.name}`}>
                {column.name}
              </Label>
            </div>
          );
        })}
      </fieldset>
      <SelectField
        id={`${idPrefix}-stat`}
        label={t('editor.stat')}
        value={config.stat}
        options={(['count', 'sum', 'mean', 'min', 'max'] as const).map((stat) => ({
          value: stat,
          label: t(`editor.statNames.${stat}`),
        }))}
        onChange={(stat) => onChange({ ...config, stat: stat as FieldsBarChartConfig['stat'] })}
      />
    </>
  );
}

export default function BarChartEditor(props: WidgetEditorProps<BarChartConfig>) {
  const { config, onChange, columns, idPrefix } = props;
  const { t } = useTranslation('widgets');
  const mode: Mode = config.mode ?? 'category';
  const numeric = columns.some((column) => isAggregateNumeric(column.type));
  const dated = columns.some((column) => isDateColumn(column.type));
  const available: Record<Mode, boolean> = { category: true, date: dated, by_feature: numeric, by_fields: numeric };
  return (
    <div className="space-y-3">
      <SelectField
        id={`${idPrefix}-mode`}
        label={t('editor.barMode')}
        value={mode}
        options={MODES.map((option) => ({
          value: option,
          label: t(`editor.barModes.${option}`),
          disabled: !available[option] && option !== mode,
        }))}
        onChange={(next) => onChange(configForMode(next as Mode, config, columns))}
      />
      {!available[mode] && (
        <p className="text-xs text-muted-foreground">{t(mode === 'date' ? 'editor.barNeedsDates' : 'editor.barNeedsNumbers')}</p>
      )}
      {config.mode === 'by_feature' ? (
        <FeatureFields {...props} config={config} />
      ) : config.mode === 'by_fields' ? (
        <FieldsFields {...props} config={config} />
      ) : (
        <CategoryFields {...props} config={config} />
      )}
      {(config.mode === undefined || config.mode === 'category') && (
        <LayerColorsField
          id={`${idPrefix}-layer-colors`}
          checked={config.use_layer_colors !== false}
          onChange={(on) => {
            const next = { ...config };
            delete next.use_layer_colors;
            onChange(on ? next : { ...next, use_layer_colors: false });
          }}
        />
      )}
    </div>
  );
}
