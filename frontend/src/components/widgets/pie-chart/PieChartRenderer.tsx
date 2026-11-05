import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { useChartMarks } from '../chart-marks';
import type { SelectionValue, WidgetRenderProps } from '../contract';
import { useLayerColors } from '../layer-colors';
import { PICKED_GLYPH, PickedMark } from '../PickedMark';
import { selectedValues, togglePick } from '../selection';
import { ValueTable } from '../ValueTable';
import type { PieChartConfig } from './definition';
import { arcCentre, arcPath, pieArcs } from './pie-geometry';
import { pieTableProps, usePieChartText } from './pie-chart-rows';

// Drawn in viewBox units; the SVG scales to the panel's width.
const SIZE = 120;
const CENTRE = SIZE / 2;
const RADIUS = 56;

// Static class names, so Tailwind sees each one; slices past the eighth reuse the palette.
const THEME_FILLS = [
  'fill-viz-1',
  'fill-viz-2',
  'fill-viz-3',
  'fill-viz-4',
  'fill-viz-5',
  'fill-viz-6',
  'fill-viz-7',
  'fill-viz-8',
] as const;

/**
 * A pie of the top values of a column, the rest merged into an "Other" slice,
 * with a legend that gives every slice its label, value and share, so colour
 * never carries the meaning alone. Like the bar chart it is one tab stop whose
 * slices are hidden from assistive technology: arrow keys, Home and End move
 * between slices, and a live readout below names the active one. The data
 * table is one click away.
 *
 * Where the host links widgets, a click on a slice, or Enter or Space on the
 * active one, picks its value; picking it again clears the pick. "Other"
 * stands for no one value and can't be picked. A chart on the layer's style
 * column draws each slice in the layer's colour for it.
 */
export default function PieChartRenderer({
  config,
  data,
  selection,
  onSelect,
  mapHidden,
  columnLabel,
}: WidgetRenderProps<PieChartConfig>) {
  const { t, i18n } = useTranslation('widgets');
  const text = usePieChartText(config, data, columnLabel);
  const hintId = useId();
  const colorOf = useLayerColors(config.use_layer_colors ? config.column : null);
  const rows = text.rows ?? [];
  const picked = selectedValues(selection, config.column);
  const hasOther = text.other !== undefined;
  const slices: { key: SelectionValue; label: string; text: string; amount: number }[] = [
    ...rows.map((row) => ({ key: row.key, label: row.label, text: row.text, amount: row.amount })),
    ...(hasOther ? [{ key: null, label: String(t('other')), text: text.other!, amount: text.otherAmount }] : []),
  ];
  const arcs = pieArcs(slices.map((slice) => slice.amount));
  // Shares of a list that leaves groups out would read as shares of the whole.
  const whole = text.note === undefined;
  const share = (index: number) =>
    new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: 1 }).format(arcs[index].share);
  const { current, chartProps, markProps } = useChartMarks(
    slices.length,
    onSelect
      ? (index) => {
          if (index >= rows.length) return;
          onSelect(
            togglePick(picked.length === 1 && picked[0] === rows[index].key, {
              column: config.column,
              label: rows[index].label,
              values: [rows[index].key],
            }),
          );
        }
      : undefined,
  );
  const table = <ValueTable {...pieTableProps(config, text, selection)} />;

  if (rows.length === 0) return table;

  const isOther = (index: number) => hasOther && index === rows.length;
  const colorFor = (index: number) => (isOther(index) ? undefined : colorOf?.(rows[index].key));
  const fillClass = (index: number) =>
    colorFor(index) ? undefined : isOther(index) ? 'fill-muted-foreground' : THEME_FILLS[index % THEME_FILLS.length];
  const anyPicked = picked.length > 0;

  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="group"
        aria-roledescription={t('types.pie_chart.roleDescription')}
        aria-label={text.summary}
        aria-describedby={hintId}
        {...chartProps}
        className={cn(chartProps.className, 'mx-auto max-w-40')}
      >
        {slices.map((slice, index) => {
          const isActive = index === current;
          const isPicked = !isOther(index) && picked.includes(slice.key);
          const centre = arcCentre(CENTRE, CENTRE, RADIUS, arcs[index]);
          return (
            <g key={index} aria-hidden="true" data-picked={isPicked || undefined} {...(isOther(index) ? {} : markProps(index))}>
              <path
                d={arcPath(CENTRE, CENTRE, RADIUS, arcs[index])}
                className={cn(
                  fillClass(index),
                  isActive ? 'stroke-foreground' : 'stroke-background',
                  anyPicked && !isPicked && 'opacity-75',
                )}
                style={colorFor(index) ? { fill: colorFor(index) } : undefined}
                strokeWidth={isActive ? 3 : 1}
              />
              {isPicked && arcs[index].share > 0.05 && (
                <text
                  x={centre.x}
                  y={centre.y}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize={12}
                  className="fill-background font-semibold"
                >
                  {PICKED_GLYPH}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <p id={hintId} className="sr-only">
        {t(onSelect ? (mapHidden ? 'types.pie_chart.keyboardHintPickPage' : 'types.pie_chart.keyboardHintPick') : 'types.pie_chart.keyboardHint')}
      </p>
      <figcaption className="min-h-5 text-sm" aria-live="polite">
        {current !== null && (
          <span>
            {t(whole ? 'types.pie_chart.slice' : 'types.pie_chart.sliceValue', {
              label: slices[current].label,
              value: slices[current].text,
              share: share(current),
            })}
          </span>
        )}
      </figcaption>
      <ul className="space-y-1 text-sm">
        {slices.map((slice, index) => (
          <li key={index} className="flex items-baseline gap-2">
            <svg aria-hidden="true" viewBox="0 0 10 10" className="size-2.5 shrink-0 self-center">
              <rect
                width={10}
                height={10}
                rx={2}
                className={fillClass(index)}
                style={colorFor(index) ? { fill: colorFor(index) } : undefined}
              />
            </svg>
            <span className={cn('min-w-0 flex-1 break-words', (index === current || (!isOther(index) && picked.includes(slice.key))) && 'font-semibold')}>
              {slice.label}
              {!isOther(index) && picked.includes(slice.key) && <PickedMark />}
            </span>
            <span className="tabular-nums">{slice.text}</span>
            {whole && <span className="w-12 text-right tabular-nums text-muted-foreground">{share(index)}</span>}
          </li>
        ))}
      </ul>
      {text.note && <p className="text-xs text-muted-foreground">{text.note}</p>}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">{t('showTable')}</summary>
        {table}
      </details>
    </figure>
  );
}
