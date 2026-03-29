import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { useBasemaps } from '@/hooks/use-settings';
import { cn } from '@/lib/utils';
import positronThumb from '@/assets/basemaps/positron.png';
import darkThumb from '@/assets/basemaps/dark.png';
import osmThumb from '@/assets/basemaps/osm.png';
import brightThumb from '@/assets/basemaps/bright.png';

const BUILTIN_THUMBNAILS: Record<string, string> = {
  'openfreemap-positron': positronThumb,
  'openfreemap-dark': darkThumb,
  'openstreetmap': osmThumb,
  'osm-standard': osmThumb,
  'openfreemap-bright': brightThumb,
};

const FALLBACK_THUMBNAIL = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">' +
  '<rect fill="#e5e7eb" width="160" height="160" rx="8"/>' +
  '<circle cx="80" cy="72" r="36" fill="none" stroke="#9ca3af" stroke-width="2"/>' +
  '<ellipse cx="80" cy="72" rx="16" ry="36" fill="none" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="44" y1="72" x2="116" y2="72" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="80" y1="36" x2="80" y2="108" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<text x="80" y="136" text-anchor="middle" font-size="12" fill="#9ca3af" font-family="system-ui,sans-serif">Map</text>' +
  '</svg>'
)}`;

function basemapThumbnail(id: string): string {
  return BUILTIN_THUMBNAILS[id] ?? FALLBACK_THUMBNAIL;
}

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
        className="flex items-center gap-2 w-full rounded-md px-2 py-1.5 hover:bg-accent/50 transition-colors"
      >
        <img
          src={basemapThumbnail(value)}
          alt={current?.label ?? t('basemap.title')}
          className="w-8 h-8 rounded border"
        />
        <span className="text-sm flex-1 text-left truncate">
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
                'flex flex-col items-center gap-0.5 rounded-md p-1 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out',
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
              <span className="text-[9px] text-center leading-tight truncate w-full">
                {b.label}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Basemap labels toggle */}
      {onToggleLabels && (
        <label className="flex items-center gap-1.5 px-2 pt-1.5 text-xs text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showLabels}
            onChange={(e) => onToggleLabels(e.target.checked)}
            className="rounded"
          />
          {t('basemap.showLabels')}
        </label>
      )}
    </div>
  );
}
