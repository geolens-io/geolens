import { cn } from '@/lib/utils';
import { FILL_PATTERN_IDS } from './layer-adapters/fill-pattern-images';
import { patternPreviewStyle } from '@/lib/fill-pattern-preview';

interface FillPatternPickerProps {
  value: string | undefined;
  onChange: (id: string | undefined) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

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
export function FillPatternPicker({ value, onChange, t }: FillPatternPickerProps) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs text-muted-foreground">{t('style.fillPattern')}</div>
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
        />
        {/* Pattern swatches */}
        {FILL_PATTERN_IDS.map((id) => {
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
