import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { WidgetEditorProps } from '../contract';
import { SelectField, StatColumnFields } from '../editor-fields';
import { REFERENCE_LABEL_MAX_LENGTH, type IndicatorComparison, type IndicatorConfig } from './definition';

const COMPARISONS = ['both', 'value', 'percent'] as const satisfies readonly IndicatorComparison[];

/** The config with its reference options set; a default is left out, and without a reference they all are. */
function withReference(
  config: IndicatorConfig,
  options: Pick<IndicatorConfig, 'reference' | 'reference_label' | 'higher_is_better' | 'comparison'>,
): IndicatorConfig {
  const { stat, column } = config;
  const { reference, reference_label: label, higher_is_better: higher, comparison } = options;
  if (reference === undefined) return { stat, column };
  return {
    stat,
    column,
    reference,
    ...(label ? { reference_label: label } : {}),
    ...(higher === false ? { higher_is_better: false } : {}),
    ...(comparison && comparison !== 'both' ? { comparison } : {}),
  };
}

export default function IndicatorEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<IndicatorConfig>) {
  const { t } = useTranslation('widgets');
  const [text, setText] = useState(config.reference === undefined ? '' : String(config.reference));
  const [shown, setShown] = useState(config.reference);
  if (config.reference !== shown) {
    setShown(config.reference);
    setText(config.reference === undefined ? '' : String(config.reference));
  }
  return (
    <div className="space-y-3">
      <StatColumnFields
        idPrefix={idPrefix}
        stat={config.stat}
        column={config.column}
        columns={columns}
        onChange={(stat, column) => onChange({ ...config, stat, column })}
      />
      <div className="space-y-1.5">
        <Label className="text-xs" htmlFor={`${idPrefix}-reference`}>
          {t('editor.reference')}
        </Label>
        <Input
          id={`${idPrefix}-reference`}
          type="number"
          inputMode="decimal"
          step="any"
          className="h-8"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            // A half-typed number such as "-" reads as empty and must not clear the reference.
            if (event.target.validity.badInput) return;
            const next = event.target.value.trim() === '' ? undefined : Number(event.target.value);
            if (next === undefined || Number.isFinite(next)) {
              setShown(next);
              onChange(withReference(config, { ...config, reference: next }));
            }
          }}
          onBlur={() => setText(config.reference === undefined ? '' : String(config.reference))}
        />
      </div>
      {config.reference !== undefined && (
        <>
          <div className="space-y-1.5">
            <Label className="text-xs" htmlFor={`${idPrefix}-reference-label`}>
              {t('editor.referenceLabel')}
            </Label>
            <Input
              id={`${idPrefix}-reference-label`}
              className="h-8"
              value={config.reference_label ?? ''}
              onChange={(event) => onChange(withReference(config, { ...config, reference_label: [...event.target.value].slice(0, REFERENCE_LABEL_MAX_LENGTH).join('') }))}
            />
          </div>
          <SelectField
            id={`${idPrefix}-comparison`}
            label={t('editor.comparison')}
            value={config.comparison ?? 'both'}
            options={COMPARISONS.map((value) => ({ value, label: t(`editor.comparisons.${value}`) }))}
            onChange={(comparison) =>
              onChange(withReference(config, { ...config, comparison: comparison as IndicatorComparison }))
            }
          />
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${idPrefix}-higher-is-better`}
              checked={config.higher_is_better ?? true}
              onCheckedChange={(checked) =>
                onChange(withReference(config, { ...config, higher_is_better: checked === true }))
              }
            />
            <Label className="text-xs font-normal" htmlFor={`${idPrefix}-higher-is-better`}>
              {t('editor.higherIsBetter')}
            </Label>
          </div>
        </>
      )}
    </div>
  );
}
