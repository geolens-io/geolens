import { useTranslation } from 'react-i18next';
import { aggregateResult, aggregateStat, formatAggregateValue, STAT_LABEL_KEYS } from '../aggregate';
import type { IndicatorConfig } from './definition';

/** The statistic's label and its value as text, with "no data" before the host has fetched it. */
export function useIndicatorText(config: IndicatorConfig, data: unknown): { label: string; value: string } {
  const { t } = useTranslation('widgets');
  let value: number | string | null | undefined;
  if (config.stat === 'count') {
    value = aggregateResult(data, 'count')?.count;
  } else {
    const stat = aggregateStat(config.stat) as 'sum' | 'avg' | 'min' | 'max';
    value = aggregateResult(data, 'stats')?.[stat];
  }
  return {
    label: t(STAT_LABEL_KEYS[config.stat], { column: config.column }),
    value: value === undefined ? t('noData') : formatAggregateValue(value),
  };
}
