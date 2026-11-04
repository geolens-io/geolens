import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import { ValueTable } from '../ValueTable';
import type { IndicatorConfig } from './definition';
import { useIndicatorText } from './indicator-value';

export function IndicatorFallback({ config, data, columnLabel }: WidgetRenderProps<IndicatorConfig>) {
  const { t } = useTranslation('widgets');
  const text = useIndicatorText(config, data, columnLabel);
  const summary = t('types.indicator.summary', { label: text.label, value: text.value });
  if (!text.reference) return <p className="text-sm">{summary}</p>;
  return (
    <ValueTable
      caption={summary}
      labelHeader={t('types.indicator.measure')}
      valueHeader={t('types.indicator.value')}
      rows={[
        { label: text.label, text: text.value },
        { label: text.reference.label, text: text.reference.value },
        ...(text.difference ? [{ label: t('types.indicator.difference'), text: text.difference.text }] : []),
      ]}
    />
  );
}
