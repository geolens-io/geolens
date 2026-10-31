import type { WidgetRenderProps } from '../contract';
import { ValueTable } from '../ValueTable';
import type { HistogramConfig } from './definition';
import { histogramTableProps, useHistogramText } from './histogram-bins';

export function HistogramFallback({ config, data, selection, columnLabel }: WidgetRenderProps<HistogramConfig>) {
  return <ValueTable {...histogramTableProps(config, useHistogramText(config, data, columnLabel), selection)} />;
}
