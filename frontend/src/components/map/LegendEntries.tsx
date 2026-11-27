import { Fragment, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { breakLabel } from '@/lib/legend-utils';
import { patternPreviewStyle } from '@/lib/fill-pattern-preview';
import { rampGradient } from './legend-facts';
import type { LegendClasses, LegendRamp, LegendSwatch } from './legend-facts';

// Swatch colours are data, so forced colors must not repaint them; the edge keeps
// a swatch visible against the system background.
export const KEEP_DATA_COLOR = 'forced-color-adjust-none';
export const SWATCH_EDGE = 'forced-colors:outline forced-colors:outline-1 forced-colors:outline-[CanvasText]';
// Underlays are drawn first and only shown in forced colors: a system-coloured
// halo behind a glyph keeps it visible whatever data colour it carries.
export const UNDERLAY = 'hidden forced-colors:block';
// Drawn over a line's underlay at the foreground's width, so a translucent
// stroke blends against the background, not the halo.
export const KNOCKOUT = `${UNDERLAY} stroke-[Canvas]`;

/**
 * An exterior ring just outside the fill and any authored stroke, so a hollow or
 * translucent glyph stays hollow. The svg lets it overflow rather than clip.
 */
function HaloRing({ cx, cy, r, s }: { cx: number; cy: number; r: number; s?: LegendSwatch | null }) {
  // A zero radius draws nothing, so it gets no halo either.
  if (r <= 0) return null;
  return (
    <circle
      cx={cx} cy={cy} r={r + (s?.stroke?.width ?? 0) / 2 + 1}
      fill="none" strokeWidth={HALO_STROKE}
      className={`${UNDERLAY} stroke-[CanvasText]`}
    />
  );
}
const HALO_SVG = 'forced-colors:overflow-visible';
const HALO_FIT_VAR = '--halo-fit';
// Scales glyph and halo together about the cell centre in forced colors only.
const FIT_HALO = 'forced-colors:[transform:scale(var(--halo-fit))]';
const HALO_STROKE = 1.5;
const RADIUS_CELL_HALF = 12;

/**
 * One scale for a whole radius-class list, set by its largest class, so the
 * largest halo fits its 24 px cell and the classes keep their relative sizes.
 */
function haloFit(items: LegendClasses['items'], s?: LegendSwatch | null): number {
  const largest = Math.max(0, ...items.map((item) => Math.min(item.size ?? 0, RADIUS_CELL_HALF)));
  if (largest <= 0) return 1;
  const outer = largest + (s?.stroke?.width ?? 0) / 2 + 1 + HALO_STROKE / 2;
  return Math.min(1, RADIUS_CELL_HALF / outer);
}

/**
 * Element-level opacity for the LAYER opacity only. Each renderer applies
 * fillOpacity to its fill alone, so a stroke-only style (fill-opacity: 0)
 * keeps its outline.
 */
function swatchOpacityStyle(s?: LegendSwatch | null): React.CSSProperties | undefined {
  const opacity = s?.opacity ?? 1;
  return opacity < 1 ? { opacity } : undefined;
}

/** SVG stroke attributes for a swatch's ring: none when the layer draws no stroke. */
function ringProps(s?: LegendSwatch | null) {
  return s?.stroke ? { stroke: s.stroke.color, strokeWidth: s.stroke.width } : { strokeWidth: 0 };
}


interface GeometrySwatchProps {
  geometryType?: string | null;
  color: string;
  style?: LegendSwatch | null;
}

export function GeometrySwatch({ geometryType, color, style: s }: GeometrySwatchProps) {
  const gt = (geometryType ?? '').toUpperCase();
  const opacityStyle = swatchOpacityStyle(s);

  if (gt.includes('POINT')) {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" className={`shrink-0 ${KEEP_DATA_COLOR} ${HALO_SVG}`} style={opacityStyle} aria-hidden="true">
        <HaloRing cx={7} cy={7} r={5} s={s} />
        <circle
          cx="7" cy="7" r="5"
          fill={color}
          fillOpacity={s?.fillOpacity}
          {...ringProps(s)}
        />
      </svg>
    );
  }

  if (gt.includes('LINE')) {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" className={`shrink-0 ${KEEP_DATA_COLOR}`} style={opacityStyle} aria-hidden="true">
        <line x1="1" y1="7" x2="13" y2="7" strokeWidth={4.5} strokeLinecap="round" className={`${UNDERLAY} stroke-[CanvasText]`} />
        <line x1="1" y1="7" x2="13" y2="7" strokeWidth={2.5} strokeLinecap="round" className={KNOCKOUT} />
        <line
          x1="1" y1="7" x2="13" y2="7"
          stroke={color}
          strokeOpacity={s?.fillOpacity}
          strokeWidth={2.5}
          strokeLinecap="round"
        />
      </svg>
    );
  }

  // Polygon / default: filled rectangle, or the pattern preview when the layer
  // carries a fill-pattern, since MapLibre draws the pattern INSTEAD of the fill.
  const stroke = s?.stroke ?? null;
  const fillStyle: React.CSSProperties = s?.pattern
    ? {
        color: s.pattern.tint ?? color,
        backgroundColor: 'transparent',
        ...patternPreviewStyle(s.pattern.id),
      }
    : { backgroundColor: color };
  // fillOpacity dims the fill LAYER only, rendered as a nested element behind
  // the border. Plain CSS opacity works for every CSS color format (hex3/4/6/8,
  // rgb()/hsl(), named) with no parsing, and never touches the border, which
  // must stay fully opaque for a stroke-only style (fillOpacity 0) to show.
  if (s && s.fillOpacity < 1) {
    fillStyle.opacity = s.fillOpacity;
  }
  return (
    <div
      className={cn('relative w-3.5 h-3.5 rounded-sm shrink-0 overflow-hidden', KEEP_DATA_COLOR, SWATCH_EDGE, stroke && 'border')}
      style={{
        ...(stroke ? { borderColor: stroke.color, borderWidth: stroke.width } : {}),
        ...opacityStyle,
      }}
      aria-hidden="true"
    >
      <div className="absolute inset-0" style={fillStyle} />
    </div>
  );
}


interface ClassListProps {
  items: LegendClasses['items'];
  breaks: number[];
  geometryType?: string | null;
  style?: LegendSwatch | null;
  /** The label of the class every other value falls in. */
  otherLabel: string;
}

/** Colour classes: a swatch per class, labelled by its category or break range. */
function ColorClassList({ items, breaks, geometryType, style: s, otherLabel }: ClassListProps) {
  return (
    <ul className="space-y-0.5">
      {items.map((item, i) => {
        const label = item.label ?? (item.other ? otherLabel : breakLabel(i, breaks));
        return (
          <li key={i} className="flex items-center gap-1.5">
            <GeometrySwatch geometryType={geometryType} color={item.color} style={s} />
            <span className="text-muted-foreground min-w-0 break-words" title={label}>{label}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Radius classes as circles of each class's size. */
function RadiusClassList({ items, breaks, style: s }: ClassListProps) {
  const opacityStyle = swatchOpacityStyle(s);
  const fit = haloFit(items, s);
  return (
    <ul className="space-y-0.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <svg
            viewBox="0 0 24 24" width="24" height="24"
            className={`shrink-0 ${KEEP_DATA_COLOR} ${HALO_SVG} ${FIT_HALO}`}
            style={{ ...opacityStyle, [HALO_FIT_VAR]: fit } as React.CSSProperties}
          >
            <HaloRing cx={12} cy={12} r={Math.min(item.size ?? 0, 12)} s={s} />
            <circle
              cx="12" cy="12"
              r={Math.min(item.size ?? 0, 12)}
              fill={item.color}
              fillOpacity={s?.fillOpacity}
              {...ringProps(s)}
            />
          </svg>
          <span className="text-muted-foreground min-w-0 break-words" title={breakLabel(i, breaks)}>{breakLabel(i, breaks)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Width classes as lines of each class's width. */
function WidthClassList({ items, breaks, style: s }: ClassListProps) {
  const opacityStyle = swatchOpacityStyle(s);
  return (
    <ul className="space-y-0.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <svg width="24" height="16" className={`shrink-0 ${KEEP_DATA_COLOR}`} style={opacityStyle}>
            {(item.size ?? 0) > 0 && (
              <>
                <line x1="0" y1="8" x2="24" y2="8" strokeWidth={Math.min(item.size ?? 0, 8) + 3} strokeLinecap="round" className={`${UNDERLAY} stroke-[CanvasText]`} />
                <line x1="0" y1="8" x2="24" y2="8" strokeWidth={Math.min(item.size ?? 0, 8)} strokeLinecap="round" className={KNOCKOUT} />
              </>
            )}
            <line x1="0" y1="8" x2="24" y2="8" stroke={item.color} strokeOpacity={s?.fillOpacity} strokeWidth={Math.min(item.size ?? 0, 8)} strokeLinecap="round" />
          </svg>
          <span className="text-muted-foreground min-w-0 break-words" title={breakLabel(i, breaks)}>{breakLabel(i, breaks)}</span>
        </li>
      ))}
    </ul>
  );
}

const CLASS_LISTS = { color: ColorClassList, radius: RadiusClassList, width: WidthClassList };

interface LegendClassesListProps {
  classes: LegendClasses[];
  geometryType?: string | null;
  style?: LegendSwatch | null;
}

/**
 * Every classification a layer draws. Size classes are titled, and so are colour
 * classes that follow another classification.
 */
export const LegendClassesList = memo(function LegendClassesList({ classes, geometryType, style }: LegendClassesListProps) {
  const { t } = useTranslation('common');
  return (
    <div className="space-y-1">
      {classes.map((entry, i) => {
        const title = entry.target === 'radius'
          ? t('viewer.legend.sizeLabel', { label: entry.title })
          : entry.target === 'width'
            ? t('viewer.legend.widthLabel', { label: entry.title })
            : i > 0 ? t('viewer.legend.colorLabel', { label: entry.title }) : null;
        const ClassList = CLASS_LISTS[entry.target];
        return (
          <Fragment key={i}>
            {title && (
              <div className={cn('text-mini font-medium text-muted-foreground', i > 0 && 'pt-1')}>{title}</div>
            )}
            <ClassList
              items={entry.items}
              breaks={entry.breaks}
              geometryType={geometryType}
              style={style}
              otherLabel={t('viewer.legend.other')}
            />
          </Fragment>
        );
      })}
    </div>
  );
});


interface HeatmapLegendProps {
  name: string;
  ramp: LegendRamp;
  weightColumn?: string;
  opacity?: number;
  lowLabel: string;
  highLabel: string;
  weightedByLabel?: string;
}

export const HeatmapLegend = memo(function HeatmapLegend({
  name,
  ramp,
  weightColumn,
  opacity = 1,
  lowLabel,
  highLabel,
  weightedByLabel,
}: HeatmapLegendProps) {
  const stops = rampGradient(ramp).map(({ color, offset }) => `${color} ${Math.round(offset * 10000) / 100}%`);
  const gradient = `linear-gradient(to right, ${stops.join(', ')})`;

  return (
    <div style={opacity < 1 ? { opacity } : undefined}>
      {name && <div className="font-medium text-foreground mb-1 truncate">{name}</div>}
      <div
        className={`h-3 rounded-sm w-full ${KEEP_DATA_COLOR} ${SWATCH_EDGE}`}
        style={{ background: gradient }}
      />
      <div className="flex justify-between mt-0.5">
        <span className="text-2xs text-muted-foreground">{lowLabel}</span>
        <span className="text-2xs text-muted-foreground">{highLabel}</span>
      </div>
      {weightColumn && weightedByLabel && (
        <div className="text-2xs text-muted-foreground mt-0.5 truncate">
          {weightedByLabel}
        </div>
      )}
    </div>
  );
});
