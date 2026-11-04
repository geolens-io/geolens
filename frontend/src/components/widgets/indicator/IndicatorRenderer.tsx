import type { WidgetRenderProps } from '../contract';
import type { IndicatorConfig } from './definition';
import { useIndicatorText } from './indicator-value';

const TONE_CLASSES = {
  good: 'text-success',
  bad: 'text-destructive',
  neutral: 'text-muted-foreground',
} as const;

export default function IndicatorRenderer({ config, data, columnLabel }: WidgetRenderProps<IndicatorConfig>) {
  const { label, value, reference, difference } = useIndicatorText(config, data, columnLabel);
  return (
    <div className="flex flex-col gap-1">
      <p className="text-3xl font-semibold tabular-nums break-words">{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
      {reference && <p className="text-sm tabular-nums break-words">{reference.line}</p>}
      {difference && (
        <p className={`text-sm font-medium tabular-nums break-words ${TONE_CLASSES[difference.tone]}`}>
          <span aria-hidden="true">{difference.arrow} </span>
          {difference.text}
        </p>
      )}
    </div>
  );
}
