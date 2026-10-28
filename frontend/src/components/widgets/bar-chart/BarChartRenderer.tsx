import { useId, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { WidgetRenderProps } from '../contract';
import type { BarChartConfig } from './definition';
import { useBarChartText } from './bar-chart-rows';
import { BarChartTable } from './BarChartTable';

// Drawn in viewBox units; the SVG scales to the panel's width.
const WIDTH = 320;
const LABEL_WIDTH = 110;
const VALUE_WIDTH = 56;
const ROW_HEIGHT = 22;
const BAR_HEIGHT = 14;
const BAR_SPACE = WIDTH - LABEL_WIDTH - VALUE_WIDTH - 8;
const MAX_LABEL_CHARS = 18;

function clip(text: string, max: number): string {
  const chars = [...text];
  return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : text;
}

/**
 * Horizontal bars, largest first, from a zero baseline. The chart is one tab stop, a labelled group
 * whose bars are hidden from assistive technology: arrow keys, Home and End
 * move between bars, the active bar gets an outline, and a live readout below
 * the chart names it. The data table is one click away.
 */
export default function BarChartRenderer({ config, data }: WidgetRenderProps<BarChartConfig>) {
  const { t } = useTranslation('widgets');
  const text = useBarChartText(config, data);
  const [active, setActive] = useState<number | null>(null);
  const hintId = useId();
  const rows = text.rows;

  if (!rows || rows.length === 0) {
    return <BarChartTable config={config} text={text} />;
  }

  // A signed domain that always holds zero, so negative bars run left of the baseline.
  const amounts = rows.map((row) => (Number.isFinite(row.amount) ? row.amount : 0));
  const low = Math.min(0, ...amounts);
  const span = Math.max(0, ...amounts) - low;
  const scale = span > 0 ? BAR_SPACE / span : 0;
  const zeroX = LABEL_WIDTH - low * scale;
  const current = active === null ? null : Math.min(active, rows.length - 1);

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const last = rows.length - 1;
    const from = current ?? -1;
    const next: Record<string, number> = {
      ArrowDown: Math.min(from + 1, last),
      ArrowRight: Math.min(from + 1, last),
      ArrowUp: Math.max(from - 1, 0),
      ArrowLeft: Math.max(from - 1, 0),
      Home: 0,
      End: last,
    };
    if (event.key in next) {
      event.preventDefault();
      setActive(next[event.key]);
    }
  };

  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${WIDTH} ${rows.length * ROW_HEIGHT}`}
        className="h-auto w-full rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        role="group"
        aria-roledescription={t('types.bar_chart.roleDescription')}
        aria-label={text.summary}
        aria-describedby={hintId}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onFocus={() => setActive((value) => value ?? 0)}
      >
        {rows.map((row, index) => {
          const y = index * ROW_HEIGHT;
          const end = zeroX + amounts[index] * scale;
          const width = Math.abs(end - zeroX);
          const isActive = index === current;
          return (
            <g key={index} aria-hidden="true">
              <text
                x={LABEL_WIDTH - 6}
                y={y + ROW_HEIGHT / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={11}
                className={cn('fill-foreground', isActive && 'font-semibold')}
              >
                {clip(row.label, MAX_LABEL_CHARS)}
              </text>
              <rect
                x={Math.min(zeroX, end)}
                y={y + (ROW_HEIGHT - BAR_HEIGHT) / 2}
                width={Math.max(width, 1)}
                height={BAR_HEIGHT}
                rx={2}
                className={cn('fill-primary', isActive && 'stroke-foreground')}
                strokeWidth={isActive ? 2 : 0}
              />
              <text
                x={Math.max(zeroX, end) + 4}
                y={y + ROW_HEIGHT / 2}
                dominantBaseline="middle"
                fontSize={11}
                className="fill-muted-foreground tabular-nums"
              >
                {row.text}
              </text>
            </g>
          );
        })}
        {low < 0 && (
          <line
            x1={zeroX}
            x2={zeroX}
            y1={0}
            y2={rows.length * ROW_HEIGHT}
            className="stroke-muted-foreground"
            strokeWidth={1}
            aria-hidden="true"
          />
        )}
      </svg>
      <p id={hintId} className="sr-only">
        {t('types.bar_chart.keyboardHint')}
      </p>
      <figcaption className="text-sm" aria-live="polite">
        {current !== null && (
          <span>{t('types.bar_chart.bar', { label: rows[current].label, value: rows[current].text })}</span>
        )}
      </figcaption>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">{t('showTable')}</summary>
        <BarChartTable config={config} text={text} />
      </details>
    </figure>
  );
}
