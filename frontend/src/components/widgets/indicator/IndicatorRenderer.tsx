import type { WidgetRenderProps } from '../contract';
import type { IndicatorConfig } from './definition';
import { useIndicatorText } from './indicator-value';

export default function IndicatorRenderer({ config, data }: WidgetRenderProps<IndicatorConfig>) {
  const { label, value } = useIndicatorText(config, data);
  return (
    <div className="flex flex-col gap-1">
      <p className="text-3xl font-semibold tabular-nums break-words">{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}
