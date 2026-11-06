import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { useChartMarks } from '../chart-marks';
import type { WidgetRenderProps } from '../contract';
import { PICKED_GLYPH } from '../PickedMark';
import { selectedValues, togglePick } from '../selection';
import { ValueTable } from '../ValueTable';
import { useLayerColors } from '../layer-colors';
import { layerColorColumn, pickedColumn, type BarChartConfig } from './definition';
import { barTableProps, useBarChartText } from './bar-chart-rows';

// Drawn in viewBox units; the SVG scales to the panel's width.
const WIDTH = 320;
const LABEL_WIDTH = 110;
const VALUE_WIDTH = 56;
const ROW_HEIGHT = 22;
const BAR_HEIGHT = 14;
const BAR_SPACE = WIDTH - LABEL_WIDTH - VALUE_WIDTH - 8;
const MAX_LABEL_CHARS = 16;

function clip(text: string, max: number): string {
  const chars = [...text];
  return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : text;
}

/**
 * Horizontal bars, largest first, from a zero baseline. The chart is one tab stop, a labelled group
 * whose bars are hidden from assistive technology: arrow keys, Home and End
 * move between bars, the active bar gets an outline, and a live readout below
 * the chart names it. The data table is one click away.
 *
 * Where the host links widgets, a click on a bar, or Enter or Space on the
 * active one, picks its category; picking it again clears the pick. Picked
 * bars keep full strength and a check mark, and the others fade. Only bars that
 * stand for values of one column can be picked, so a chart by date or by field
 * is read-only. A category chart on the layer's style column draws each bar in
 * the layer's colour for it.
 */
export default function BarChartRenderer({
  config,
  data,
  selection,
  onSelect,
  mapHidden,
  columnLabel,
}: WidgetRenderProps<BarChartConfig>) {
  const { t } = useTranslation('widgets');
  const text = useBarChartText(config, data, columnLabel);
  const hintId = useId();
  const rows = text.rows ?? [];
  const pickColumn = pickedColumn(config);
  const pick = pickColumn === null ? undefined : onSelect;
  const picked = pickColumn === null ? [] : selectedValues(selection, pickColumn);
  const colorOf = useLayerColors(layerColorColumn(config));
  const { current, chartProps, markProps } = useChartMarks(
    rows.length,
    pick && pickColumn !== null
      ? (index) =>
          pick(
            togglePick(picked.length === 1 && picked[0] === rows[index].key, {
              column: pickColumn,
              label: rows[index].label,
              values: [rows[index].key],
            }),
          )
      : undefined,
  );
  const table = <ValueTable {...barTableProps(config, text, selection)} />;

  if (rows.length === 0) return table;

  // A signed domain that always holds zero, so negative bars run left of the baseline.
  const amounts = rows.map((row) => (Number.isFinite(row.amount) ? row.amount : 0));
  const low = Math.min(0, ...amounts);
  const span = Math.max(0, ...amounts) - low;
  const scale = span > 0 ? BAR_SPACE / span : 0;
  const zeroX = LABEL_WIDTH - low * scale;

  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${WIDTH} ${rows.length * ROW_HEIGHT}`}
        role="group"
        aria-roledescription={t('types.bar_chart.roleDescription')}
        aria-label={text.summary}
        aria-describedby={hintId}
        {...chartProps}
      >
        {rows.map((row, index) => {
          const y = index * ROW_HEIGHT;
          const end = zeroX + amounts[index] * scale;
          const width = Math.abs(end - zeroX);
          const isActive = index === current;
          const isPicked = picked.includes(row.key);
          const layerColor = colorOf?.(row.key);
          return (
            <g key={index} aria-hidden="true" data-picked={isPicked || undefined} {...markProps(index)}>
              <title>{t('types.bar_chart.bar', { label: row.label, value: row.text })}</title>
              {isPicked && (
                <text x={0} y={y + ROW_HEIGHT / 2} dominantBaseline="middle" fontSize={11} className="fill-foreground">
                  {PICKED_GLYPH}
                </text>
              )}
              <text
                x={LABEL_WIDTH - 6}
                y={y + ROW_HEIGHT / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={11}
                className={cn('fill-foreground', (isActive || isPicked) && 'font-semibold')}
              >
                {clip(row.label, MAX_LABEL_CHARS)}
              </text>
              <rect
                x={Math.min(zeroX, end)}
                y={y + (ROW_HEIGHT - BAR_HEIGHT) / 2}
                width={Math.max(width, 1)}
                height={BAR_HEIGHT}
                rx={2}
                className={cn(
                  !layerColor && 'fill-primary',
                  picked.length > 0 && !isPicked && 'opacity-75',
                  isActive && 'stroke-foreground',
                )}
                style={layerColor ? { fill: layerColor } : undefined}
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
        {t(pick ? (mapHidden ? 'types.bar_chart.keyboardHintPickPage' : 'types.bar_chart.keyboardHintPick') : 'types.bar_chart.keyboardHint')}
      </p>
      <figcaption className="min-h-5 text-sm" aria-live="polite">
        {current !== null && (
          <span>{t('types.bar_chart.bar', { label: rows[current].label, value: rows[current].text })}</span>
        )}
      </figcaption>
      {text.note && <p className="text-xs text-muted-foreground">{text.note}</p>}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">{t('showTable')}</summary>
        {table}
      </details>
    </figure>
  );
}
