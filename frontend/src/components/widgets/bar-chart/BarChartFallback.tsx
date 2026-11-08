import type { WidgetRenderProps } from '../contract';
import { ValueTable } from '../ValueTable';
import type { BarChartConfig } from './definition';
import { barTableProps, useBarChartText } from './bar-chart-rows';

export function BarChartFallback({ config, data, selection, columnLabel, valueLabel }: WidgetRenderProps<BarChartConfig>) {
  const text = useBarChartText(config, data, columnLabel, valueLabel);
  return (
    <>
      <ValueTable {...barTableProps(config, text, selection)} />
      {text.note && <p className="mt-2 text-xs text-muted-foreground">{text.note}</p>}
    </>
  );
}
