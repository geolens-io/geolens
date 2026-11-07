import type { WidgetRenderProps } from '../contract';
import { ValueTable } from '../ValueTable';
import type { PieChartConfig } from './definition';
import { pieTableProps, usePieChartText } from './pie-chart-rows';

export function PieChartFallback({ config, data, selection, columnLabel }: WidgetRenderProps<PieChartConfig>) {
  const text = usePieChartText(config, data, columnLabel);
  return (
    <>
      <ValueTable {...pieTableProps(config, text, selection)} />
      {text.note && <p className="mt-2 text-xs text-muted-foreground">{text.note}</p>}
    </>
  );
}
