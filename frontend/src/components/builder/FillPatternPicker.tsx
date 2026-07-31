import { cn } from '@/lib/utils';
import { FILL_PATTERN_IDS } from './layer-adapters/fill-pattern-images';
import { patternPreviewStyle } from '@/lib/fill-pattern-preview';

interface FillPatternPickerProps {
  value: string | undefined;
  onChange: (id: string | undefined) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
  /**
   * fix(#910, codex P2): recovery-only mode — render just the None swatch. A
   * data-driven or extruded layer can arrive carrying a pattern (Advanced JSON, the
   * AI set_style action), and it must stay clearable; but applying one there is
   * impossible by EDIT-05, and handleStyleConfigChange strips it straight back. A
   * swatch that silently reverts is worse than no swatch, so only None is offered.
   */
  clearOnly?: boolean;
}

/**
 * fix(#910, codex P2): display-only stand-in for an expression-valued `fill-pattern`.
 * A pattern IS active, so None must not read as pressed, but no swatch can represent
 * an expression. Not a pattern id: never emitted by onChange, never reaches paint.
 */
export const EXPRESSION_PATTERN = '__expression__';

/**
 * Short keys for the built-in fill patterns (id minus the 'geolens-fill-' prefix).
 * Used to look up i18n labels via t('style.fillPatternName.<shortKey>').
 */
function shortKey(id: string): string {
  return id.replace(/^geolens-fill-/, '');
}

/**
 * IconPicker-style swatch grid for selecting a built-in fill pattern.
 * Renders a "None" (solid) option first, then one swatch per FILL_PATTERN_IDS.
 * Pure presentational — no map access, no network.
 */
export function FillPatternPicker({ value, onChange, t, clearOnly = false }: FillPatternPickerProps) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs text-muted-foreground">
        {clearOnly ? t('style.fillPatternClearOnly') : t('style.fillPattern')}
      </div>
      <div className="grid grid-cols-5 gap-1">
        {/* None (solid fill) swatch */}
        <button
          type="button"
          className={cn(
            'flex cursor-pointer h-8 w-8 items-center justify-center rounded-sm border bg-background text-2xs font-medium',
            !value ? 'border-primary ring-1 ring-ring' : 'border-border hover:bg-accent',
          )}
          onClick={() => onChange(undefined)}
          title={t('style.fillPatternNone')}
          aria-label={t('style.fillPatternNone')}
          aria-pressed={!value}
        >
          {/* fix(#922): a childless button read as an empty square to sighted
              users. A solid block is what "no pattern" actually draws. */}
          <span className="h-5 w-5 rounded-sm bg-current" />
        </button>
        {/* Pattern swatches */}
        {(clearOnly ? [] : FILL_PATTERN_IDS).map((id) => {
          const label = t(`style.fillPatternName.${shortKey(id)}`);
          const isActive = value === id;
          return (
            <button
              key={id}
              type="button"
              className={cn(
                'flex cursor-pointer h-8 w-8 items-center justify-center rounded-sm border bg-background',
                isActive ? 'border-primary ring-1 ring-ring' : 'border-border hover:bg-accent',
              )}
              onClick={() => onChange(id)}
              title={label}
              aria-label={label}
              aria-pressed={isActive}
            >
              <span
                className="h-5 w-5 rounded-sm"
                style={patternPreviewStyle(id)}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default FillPatternPicker;
