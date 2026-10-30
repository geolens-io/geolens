import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { useChartMarks } from '../chart-marks';
import type { WidgetRenderProps } from '../contract';
import { PICKED_GLYPH } from '../PickedMark';
import { ValueTable } from '../ValueTable';
import type { HistogramConfig } from './definition';
import { histogramTableProps, pickBin, pickedBins, useHistogramText } from './histogram-bins';

// Drawn in viewBox units; the SVG scales to the panel's width.
const WIDTH = 320;
const PLOT_HEIGHT = 100;
// Room above the columns for a picked bin's check mark, and below for the axis labels.
const TOP = 12;
const AXIS_HEIGHT = 16;
const GAP = 1;

/**
 * Columns of counts over equal-width bins, from a zero baseline, with the
 * lowest and highest values under the axis. Like the bar chart it is one tab
 * stop whose columns are hidden from assistive technology: arrow keys, Home
 * and End move between bins, the active bin gets an outline, and a live
 * readout below names it. The data table is one click away.
 *
 * Where the host links widgets, a click on a bin, or Enter or Space on the
 * active one, picks its range; picking a marked bin clears the pick.
 */
export default function HistogramRenderer({
  config,
  data,
  selection,
  onSelect,
  columns,
}: WidgetRenderProps<HistogramConfig>) {
  const { t } = useTranslation('widgets');
  const text = useHistogramText(config, data, columns);
  const hintId = useId();
  const bins = text.bins ?? [];
  const picked = pickedBins(text, config, selection);
  const anyPicked = picked.includes(true);
  const { current, chartProps, markProps } = useChartMarks(
    bins.length,
    onSelect ? (index) => onSelect(pickBin(bins[index], config, picked[index])) : undefined,
  );
  const table = <ValueTable {...histogramTableProps(config, text, selection)} />;

  if (bins.length === 0) return table;

  const most = Math.max(...bins.map((bin) => bin.count));
  const step = WIDTH / bins.length;
  const baseline = TOP + PLOT_HEIGHT;

  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${WIDTH} ${baseline + AXIS_HEIGHT}`}
        role="group"
        aria-roledescription={t('types.histogram.roleDescription')}
        aria-label={text.summary}
        aria-describedby={hintId}
        {...chartProps}
      >
        {bins.map((bin, index) => {
          const height = most > 0 ? (bin.count / most) * PLOT_HEIGHT : 0;
          const drawn = Math.max(height, bin.count > 0 ? 1 : 0);
          const isActive = index === current;
          const isPicked = picked[index];
          const x = index * step;
          return (
            <g key={index} aria-hidden="true" data-picked={isPicked || undefined} {...markProps(index)}>
              {/* The whole column's height takes the click, so a short bin is easy to hit. */}
              <rect x={x} y={TOP} width={step} height={PLOT_HEIGHT} className="fill-transparent" />
              <rect
                x={x + GAP / 2}
                y={baseline - drawn}
                width={Math.max(step - GAP, 1)}
                height={drawn}
                className={cn(
                  'fill-primary',
                  anyPicked && !isPicked && 'opacity-35',
                  isActive && 'stroke-foreground',
                )}
                strokeWidth={isActive ? 2 : 0}
              />
              {isPicked && (
                <text x={x + step / 2} y={TOP - 2} textAnchor="middle" fontSize={10} className="fill-foreground font-semibold">
                  {PICKED_GLYPH}
                </text>
              )}
            </g>
          );
        })}
        <line x1={0} x2={WIDTH} y1={baseline} y2={baseline} className="stroke-border" strokeWidth={1} aria-hidden="true" />
        <g aria-hidden="true" fontSize={10} className="fill-muted-foreground tabular-nums">
          <text x={0} y={baseline + 12}>
            {bins[0].lowerText}
          </text>
          <text x={WIDTH} y={baseline + 12} textAnchor="end">
            {bins[bins.length - 1].upperText}
          </text>
        </g>
      </svg>
      <p id={hintId} className="sr-only">
        {t(onSelect ? 'types.histogram.keyboardHintPick' : 'types.histogram.keyboardHint')}
      </p>
      <figcaption className="text-sm" aria-live="polite">
        {current !== null && (
          <span>{t('types.histogram.bin', { range: bins[current].label, value: bins[current].countText })}</span>
        )}
      </figcaption>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">{t('showTable')}</summary>
        {table}
      </details>
    </figure>
  );
}
