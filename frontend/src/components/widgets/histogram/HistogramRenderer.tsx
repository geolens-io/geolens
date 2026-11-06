import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { useChartMarks } from '../chart-marks';
import type { WidgetRenderProps } from '../contract';
import { PICKED_GLYPH } from '../PickedMark';
import { ValueTable } from '../ValueTable';
import type { HistogramConfig } from './definition';
import { axisTicks, histogramTableProps, pickBin, pickedBins, useHistogramText } from './histogram-bins';

// Drawn in viewBox units; the SVG scales to the panel's width.
const WIDTH = 320;
// The peak label's width in viewBox units, per character at the axis font size, plus a gap.
const CHAR_WIDTH = 6;
const LABEL_GAP = 6;
const PLOT_HEIGHT = 100;
// Room above the columns for a picked bin's check mark, and below for the axis labels.
const TOP = 12;
const AXIS_HEIGHT = 18;
const GAP = 1;

/**
 * Columns of counts over equal-width bins, from a zero baseline, with three or
 * four bin edges labelled under the axis and a gridline at the tallest bin's
 * count. Like the bar chart it is one tab
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
  mapHidden,
  columnLabel,
}: WidgetRenderProps<HistogramConfig>) {
  const { t, i18n } = useTranslation('widgets');
  const text = useHistogramText(config, data, columnLabel);
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
  const peakLabel = new Intl.NumberFormat(i18n.language, { notation: 'compact', maximumFractionDigits: 1 }).format(most);
  const LEFT = Math.max(24, peakLabel.length * CHAR_WIDTH + LABEL_GAP);
  const step = (WIDTH - LEFT) / bins.length;
  const ticks = axisTicks(bins);
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
          const x = LEFT + index * step;
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
                  anyPicked && !isPicked && 'opacity-75',
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
        <line x1={LEFT} x2={WIDTH} y1={baseline} y2={baseline} className="stroke-border" strokeWidth={1} aria-hidden="true" />
        <g aria-hidden="true" fontSize={10} className="fill-muted-foreground tabular-nums">
          <line x1={LEFT} x2={WIDTH} y1={TOP} y2={TOP} className="stroke-border" strokeDasharray="3 3" strokeWidth={1} />
          <text x={LEFT - 4} y={TOP} textAnchor="end" dominantBaseline="middle" data-peak="">
            {peakLabel}
          </text>
          {ticks.map(({ edge, text }, index) => {
            const x = LEFT + edge * step;
            return (
              <g key={edge}>
                <line x1={x} x2={x} y1={baseline} y2={baseline + 3} className="stroke-border" strokeWidth={1} />
                <text x={x} y={baseline + 13} textAnchor={index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle'}>
                  {text}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <p id={hintId} className="sr-only">
        {t(onSelect ? (mapHidden ? 'types.histogram.keyboardHintPickPage' : 'types.histogram.keyboardHintPick') : 'types.histogram.keyboardHint')}
      </p>
      <figcaption className="min-h-5 text-sm" aria-live="polite">
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
