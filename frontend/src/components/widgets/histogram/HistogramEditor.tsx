import { useTranslation } from 'react-i18next';
import { isAggregateNumeric } from '@/lib/column-utils';
import type { WidgetEditorProps } from '../contract';
import { ColumnField, IntegerField } from '../editor-fields';
import { MAX_BINS, MIN_BINS, type HistogramConfig } from './definition';

export default function HistogramEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<HistogramConfig>) {
  const { t } = useTranslation('widgets');
  const numeric = columns.filter((column) => isAggregateNumeric(column.type));
  return (
    <div className="space-y-3">
      <ColumnField
        id={`${idPrefix}-column`}
        label={t('editor.column')}
        value={config.column}
        columns={numeric}
        onChange={(column) => onChange({ ...config, column })}
      />
      {numeric.length === 0 && <p className="text-xs text-muted-foreground">{t('editor.histogramNeedsNumbers')}</p>}
      <IntegerField
        id={`${idPrefix}-bins`}
        label={t('editor.bins')}
        value={config.bins}
        min={MIN_BINS}
        max={MAX_BINS}
        onChange={(bins) => onChange({ ...config, bins })}
      />
    </div>
  );
}
