import type { WidgetRenderProps } from '../contract';
import type { BarChartConfig } from './definition';
import { useBarChartText } from './bar-chart-rows';
import { BarChartTable } from './BarChartTable';

export function BarChartFallback({ config, data }: WidgetRenderProps<BarChartConfig>) {
  return <BarChartTable config={config} text={useBarChartText(config, data)} />;
}
