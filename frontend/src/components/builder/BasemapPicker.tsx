import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { useBasemaps } from '@/hooks/use-settings';
import { basemapThumbnail, BLANK_BASEMAP_ID } from '@/lib/basemap-utils';
import { cn } from '@/lib/utils';
import { Switch } from '@/components/ui/switch';
import type { BasemapEntry } from '@/api/settings';

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
  const blankEntry: BasemapEntry = { id: BLANK_BASEMAP_ID, label: t('basemap.blank'), url: BLANK_BASEMAP_ID, enabled: true, is_preset: false };
  const options = [blankEntry, ...enabled];
  const current = options.find((b) => b.id === value);

  return (
    <div className="px-2">
      {/* Collapsed: compact row with current basemap */}
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label={`${t('basemap.title')}: ${current?.label ?? t('basemap.title')}`}
        className="flex cursor-pointer items-center gap-2 w-full rounded-lg px-2 py-1.5 bg-muted/40 hover:bg-accent/50 transition-colors border border-border/40"
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

      {/* Expanded: grid of options — always in DOM, animated via grid-rows transition */}
      <div className={cn(
        "grid transition-[grid-template-rows] duration-200 ease-out",
        open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
      )}>
        <div className="overflow-hidden">
          <div className="grid grid-cols-4 gap-2 pt-2">
            {options.map((b) => (
              <button
                key={b.id}
                data-testid="basemap-option"
                aria-pressed={value === b.id}
                onClick={() => {
                  onChange(b.id);
                  setOpen(false);
                }}
                className={cn(
                  'flex cursor-pointer flex-col items-center gap-0.5 rounded-md p-1 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                  value === b.id
                    ? 'ring-2 ring-primary ring-offset-2 ring-offset-background bg-accent'
                    : 'hover:bg-accent/50',
                )}
              >
                <img
                  src={basemapThumbnail(b.id)}
                  alt={b.label}
                  className="w-full aspect-square rounded object-cover max-h-14"
                />
                <span className="text-[11px] text-center leading-tight truncate w-full">
                  {b.label}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Basemap labels toggle */}
      {onToggleLabels && (
        <label className="flex items-center gap-2 px-2 pt-2 pb-1 text-xs text-muted-foreground cursor-pointer select-none">
          <Switch
            size="sm"
            checked={showLabels}
            onCheckedChange={onToggleLabels}
            aria-label={t('basemap.showLabels')}
          />
          {t('basemap.showLabels')}
        </label>
      )}
    </div>
  );
}
