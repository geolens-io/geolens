import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import type { IndicatorConfig } from './definition';
import { useIndicatorText } from './indicator-value';

export function IndicatorFallback({ config, data }: WidgetRenderProps<IndicatorConfig>) {
  const { t } = useTranslation('widgets');
  return <p className="text-sm">{t('types.indicator.summary', useIndicatorText(config, data))}</p>;
}
