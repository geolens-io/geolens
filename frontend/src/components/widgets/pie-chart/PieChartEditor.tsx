import { useTranslation } from 'react-i18next';
import type { WidgetEditorProps } from '../contract';
import { ColumnField, IntegerField, LayerColorsField, StatColumnFields } from '../editor-fields';
import { MAX_SLICES, type PieChartConfig } from './definition';

export default function PieChartEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<PieChartConfig>) {
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
        label={t('editor.slices')}
        value={config.limit}
        min={1}
        max={MAX_SLICES}
        onChange={(limit) => onChange({ ...config, limit })}
      />
      <LayerColorsField
        id={`${idPrefix}-layer-colors`}
        checked={config.use_layer_colors}
        onChange={(use_layer_colors) => onChange({ ...config, use_layer_colors })}
      />
    </div>
  );
}
