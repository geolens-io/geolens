import { useTranslation } from 'react-i18next';
import type { WidgetEditorProps } from '../contract';
import { ColumnField, IntegerField, StatColumnFields } from '../editor-fields';
import type { BarChartConfig } from './definition';

const MAX_BARS = 50;

export default function BarChartEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<BarChartConfig>) {
  const { t } = useTranslation('widgets');
  return (
    <div className="space-y-3">
      <ColumnField
        id={`${idPrefix}-column`}
        label={t('editor.groupBy')}
        value={config.column}
        columns={columns}
        onChange={(column) => onChange({ ...config, column })}
      />
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
    </div>
  );
}
