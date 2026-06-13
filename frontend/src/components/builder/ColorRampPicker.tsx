import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  SEQUENTIAL_RAMPS,
  DIVERGING_RAMPS,
  QUALITATIVE_RAMPS,
  getRampColors,
  cvdSafeRamps,
} from '@/lib/color-ramps';
import { cn } from '@/lib/utils';

interface RampEntry {
  readonly name: string;
  readonly label: string;
  readonly cvdSafe: boolean;
}

// PERF-N15: Ramp arrays are static — hoist to module scope instead of
// allocating fresh arrays in each render via useMemo(..., []).
const GRADUATED_RAMPS: RampEntry[] = [...SEQUENTIAL_RAMPS, ...DIVERGING_RAMPS];
const CATEGORICAL_RAMPS: RampEntry[] = [...QUALITATIVE_RAMPS];

interface ColorRampPickerProps {
  rampName: string;
  onChange: (name: string) => void;
  mode: 'categorical' | 'graduated';
  customColors?: string[];
  count?: number;
  reversed?: boolean;
  onReversedChange?: (v: boolean) => void;
}

export function ColorRampPicker({ rampName, onChange, mode, customColors, count, reversed = false, onReversedChange }: ColorRampPickerProps) {
  const { t } = useTranslation('builder');
  const allRamps = mode === 'categorical' ? CATEGORICAL_RAMPS : GRADUATED_RAMPS;

  const [cvdOnly, setCvdOnly] = useState(false);
  const ramps = cvdOnly ? cvdSafeRamps(allRamps) : allRamps;

  return (
    <div className="space-y-1.5">
      {/* Reverse + CVD-safe toggles */}
      <div className="flex items-center gap-3 px-0.5">
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={reversed}
            onChange={(e) => onReversedChange?.(e.target.checked)}
            className="h-3 w-3 rounded border-border accent-primary"
            aria-label={t('dataDriven.reverseRamp')}
            data-testid="reverse-ramp-toggle"
          />
          <span className="text-2xs text-muted-foreground">{t('dataDriven.reverseRamp')}</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={cvdOnly}
            onChange={(e) => setCvdOnly(e.target.checked)}
            className="h-3 w-3 rounded border-border accent-primary"
            aria-label={t('dataDriven.cvdSafeOnly')}
            data-testid="cvd-safe-toggle"
          />
          <span className="text-2xs text-muted-foreground">{t('dataDriven.cvdSafeOnly')}</span>
        </label>
      </div>

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
            <div className="text-2xs italic text-muted-foreground">
              {t('dataDriven.customColors')}
            </div>
          </div>
        )}
        {ramps.map((ramp) => {
          const colors = getRampColors(ramp.name, count ?? 7, reversed);
          const isSelected = ramp.name === rampName;
          return (
            <button
              key={ramp.name}
              type="button"
              onClick={() => onChange(ramp.name)}
              aria-label={ramp.label}
              className={cn(
                'flex cursor-pointer items-center gap-2 w-full px-1.5 py-1 rounded text-start transition-colors',
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
              <span className="text-2xs text-muted-foreground w-24 truncate shrink-0">
                {ramp.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
