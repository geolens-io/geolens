import type { WidgetEditorProps } from '../contract';
import { StatColumnFields } from '../editor-fields';
import type { IndicatorConfig } from './definition';

export default function IndicatorEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<IndicatorConfig>) {
  return (
    <div className="space-y-3">
      <StatColumnFields
        idPrefix={idPrefix}
        stat={config.stat}
        column={config.column}
        columns={columns}
        onChange={(stat, column) => onChange({ stat, column })}
      />
    </div>
  );
}
