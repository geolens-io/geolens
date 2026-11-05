import type { WidgetRenderProps } from '../contract';
import { ValueTable } from '../ValueTable';
import type { PieChartConfig } from './definition';
import { pieTableProps, usePieChartText } from './pie-chart-rows';

export function PieChartFallback({ config, data, selection, columnLabel }: WidgetRenderProps<PieChartConfig>) {
  return <ValueTable {...pieTableProps(config, usePieChartText(config, data, columnLabel), selection)} />;
}
