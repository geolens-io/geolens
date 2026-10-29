import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { WidgetEditorProps } from '../contract';
import { ColumnField, StatColumnFields } from '../editor-fields';
import type { BarChartConfig } from './definition';

const MAX_BARS = 50;

export default function BarChartEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<BarChartConfig>) {
  const { t } = useTranslation('widgets');
  // Typed text, so the field can be empty or mid-number while the config keeps
  // its last valid limit. A limit set from outside (a reset draft) replaces it.
  const [limitText, setLimitText] = useState(String(config.limit));
  const [shownLimit, setShownLimit] = useState(config.limit);
  if (config.limit !== shownLimit) {
    setShownLimit(config.limit);
    setLimitText(String(config.limit));
  }
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
      <div className="space-y-1.5">
        <Label className="text-xs" htmlFor={`${idPrefix}-limit`}>
          {t('editor.limit')}
        </Label>
        <Input
          id={`${idPrefix}-limit`}
          type="number"
          inputMode="numeric"
          min={1}
          max={MAX_BARS}
          className="h-8"
          value={limitText}
          onChange={(event) => {
            setLimitText(event.target.value);
            const limit = Number(event.target.value);
            if (Number.isInteger(limit) && limit >= 1 && limit <= MAX_BARS) {
              setShownLimit(limit);
              onChange({ ...config, limit });
            }
          }}
          onBlur={() => setLimitText(String(config.limit))}
        />
      </div>
    </div>
  );
}
