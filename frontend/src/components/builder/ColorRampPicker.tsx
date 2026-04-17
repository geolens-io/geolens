import { useTranslation } from 'react-i18next';
import {
  SEQUENTIAL_RAMPS,
  DIVERGING_RAMPS,
  QUALITATIVE_RAMPS,
  getRampColors,
} from '@/lib/color-ramps';
import { cn } from '@/lib/utils';

// PERF-N15: Ramp arrays are static — hoist to module scope instead of
// allocating fresh arrays in each render via useMemo(..., []).
const GRADUATED_RAMPS = [...SEQUENTIAL_RAMPS, ...DIVERGING_RAMPS];
const CATEGORICAL_RAMPS = [...QUALITATIVE_RAMPS];

interface ColorRampPickerProps {
  rampName: string;
  onChange: (name: string) => void;
  mode: 'categorical' | 'graduated';
  customColors?: string[];
  count?: number;
}

export function ColorRampPicker({ rampName, onChange, mode, customColors, count }: ColorRampPickerProps) {
  const { t } = useTranslation('builder');
  const ramps = mode === 'categorical' ? CATEGORICAL_RAMPS : GRADUATED_RAMPS;

  return (
    <div className="max-h-40 overflow-y-auto space-y-1">
      {rampName === 'custom' && (
        <div className="px-1.5 py-1 space-y-1">
          {customColors && customColors.length > 0 && (
            <div className="flex h-4 rounded-sm overflow-hidden">
              {customColors.map((color, i) => (
                <div key={i} className="flex-1" style={{ backgroundColor: color }} />
              ))}
            </div>
          )}
          <div className="text-[10px] italic text-muted-foreground">
            {t('dataDriven.customColors')}
          </div>
        </div>
      )}
      {ramps.map((ramp) => {
        const colors = getRampColors(ramp.name, count ?? 7);
        const isSelected = ramp.name === rampName;
        return (
          <button
            key={ramp.name}
            type="button"
            onClick={() => onChange(ramp.name)}
            aria-label={ramp.label}
            className={cn(
              'flex items-center gap-2 w-full px-1.5 py-1 rounded text-start transition-colors',
              isSelected
                ? 'bg-accent ring-1 ring-primary'
                : 'hover:bg-accent/50',
            )}
          >
            <div className="flex h-4 flex-1 rounded-sm overflow-hidden">
              {colors.map((color, i) => (
                <div
                  key={i}
                  className="flex-1"
                  style={{ backgroundColor: color }}
                />
              ))}
            </div>
            <span className="text-[10px] text-muted-foreground w-24 truncate shrink-0">
              {ramp.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
