import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { useBasemaps } from '@/hooks/use-settings';
import { basemapThumbnail } from '@/lib/basemap-utils';
import { cn } from '@/lib/utils';

interface BasemapPickerProps {
  value: string;
  onChange: (id: string) => void;
  showLabels?: boolean;
  onToggleLabels?: (show: boolean) => void;
}

export function BasemapPicker({ value, onChange, showLabels = true, onToggleLabels }: BasemapPickerProps) {
  const { t } = useTranslation('builder');
  const { data: basemaps } = useBasemaps();
  const [open, setOpen] = useState(false);
  const enabled = (basemaps ?? []).filter((b) => b.enabled);
  const current = enabled.find((b) => b.id === value);

  return (
    <div className="px-2">
      {/* Collapsed: compact row with current basemap */}
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label={t('basemap.title')}
        className="flex items-center gap-2 w-full rounded-md px-2 py-1.5 hover:bg-accent/50 transition-colors"
      >
        <img
          src={basemapThumbnail(value)}
          alt={current?.label ?? t('basemap.title')}
          className="w-8 h-8 rounded border"
        />
        <span className="text-sm flex-1 text-start truncate">
          {current?.label ?? t('basemap.title')}
        </span>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-muted-foreground transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {/* Expanded: grid of options */}
      {open && (
        <div className="grid grid-cols-4 gap-2 pt-2">
          {enabled.map((b) => (
            <button
              key={b.id}
              data-testid="basemap-option"
              onClick={() => {
                onChange(b.id);
                setOpen(false);
              }}
              className={cn(
                'flex flex-col items-center gap-0.5 rounded-md p-1 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                value === b.id
                  ? 'ring-2 ring-primary bg-accent'
                  : 'hover:bg-accent/50',
              )}
            >
              <img
                src={basemapThumbnail(b.id)}
                alt={b.label}
                className="w-full aspect-square rounded object-cover"
              />
              <span className="text-[11px] text-center leading-tight truncate w-full">
                {b.label}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Basemap labels toggle */}
      {onToggleLabels && (
        <div role="group" aria-label={t('basemap.options', { defaultValue: 'Basemap options' })}>
          <label className="flex items-center gap-1.5 px-2 pt-1.5 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showLabels}
              onChange={(e) => onToggleLabels(e.target.checked)}
              className="h-4 w-4 rounded accent-primary"
            />
            {t('basemap.showLabels')}
          </label>
        </div>
      )}
    </div>
  );
}
