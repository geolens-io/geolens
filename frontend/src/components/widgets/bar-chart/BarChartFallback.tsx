import type { WidgetRenderProps } from '../contract';
import { ValueTable } from '../ValueTable';
import type { BarChartConfig } from './definition';
import { barTableProps, useBarChartText } from './bar-chart-rows';

export function BarChartFallback({ config, data, selection, columnLabel }: WidgetRenderProps<BarChartConfig>) {
  return <ValueTable {...barTableProps(config, useBarChartText(config, data, columnLabel), selection)} />;
}
