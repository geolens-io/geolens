import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { useBasemaps } from '@/hooks/use-settings';
import { cn } from '@/lib/utils';

function basemapThumbnail(id: string): string {
  const thumbnails: Record<string, string> = {
    'openfreemap-positron': `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect fill="#e8e8e8" width="160" height="160"/><g stroke="#fff" stroke-width="0.5" opacity="0.6"><line x1="0" y1="40" x2="160" y2="40"/><line x1="0" y1="80" x2="160" y2="80"/><line x1="0" y1="120" x2="160" y2="120"/><line x1="40" y1="0" x2="40" y2="160"/><line x1="80" y1="0" x2="80" y2="160"/><line x1="120" y1="0" x2="120" y2="160"/></g></svg>')}`,
    'openfreemap-dark': `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect fill="#1a1a2e" width="160" height="160"/><g stroke="#333" stroke-width="0.5" opacity="0.5"><line x1="0" y1="40" x2="160" y2="40"/><line x1="0" y1="80" x2="160" y2="80"/><line x1="0" y1="120" x2="160" y2="120"/><line x1="40" y1="0" x2="40" y2="160"/><line x1="80" y1="0" x2="80" y2="160"/><line x1="120" y1="0" x2="120" y2="160"/></g></svg>')}`,
    'openfreemap-bright': `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect fill="#f5f0e8" width="160" height="160"/><g stroke="#ddd" stroke-width="0.5"><line x1="0" y1="40" x2="160" y2="40"/><line x1="0" y1="80" x2="160" y2="80"/><line x1="0" y1="120" x2="160" y2="120"/><line x1="40" y1="0" x2="40" y2="160"/><line x1="80" y1="0" x2="80" y2="160"/><line x1="120" y1="0" x2="120" y2="160"/></g><rect fill="#b8d4a0" x="20" y="60" width="50" height="40" rx="3" opacity="0.4"/><rect fill="#a0c8e0" x="90" y="30" width="40" height="60" rx="3" opacity="0.3"/></svg>')}`,
    'osm-standard': `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect fill="#f0ede8" width="160" height="160"/><rect fill="#aad3a2" x="10" y="50" width="60" height="50" rx="4" opacity="0.5"/><rect fill="#a8cce8" x="80" y="20" width="70" height="30" rx="4" opacity="0.4"/><g stroke="#ccc" stroke-width="0.5"><line x1="0" y1="40" x2="160" y2="40"/><line x1="0" y1="80" x2="160" y2="80"/><line x1="0" y1="120" x2="160" y2="120"/><line x1="40" y1="0" x2="40" y2="160"/><line x1="80" y1="0" x2="80" y2="160"/><line x1="120" y1="0" x2="120" y2="160"/></g></svg>')}`,
  };
  const defaultSvg = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect fill="#d0d0d0" width="160" height="160"/><g stroke="#bbb" stroke-width="0.5"><line x1="0" y1="40" x2="160" y2="40"/><line x1="0" y1="80" x2="160" y2="80"/><line x1="0" y1="120" x2="160" y2="120"/><line x1="40" y1="0" x2="40" y2="160"/><line x1="80" y1="0" x2="80" y2="160"/><line x1="120" y1="0" x2="120" y2="160"/></g></svg>')}`;
  return thumbnails[id] ?? defaultSvg;
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
          className="w-6 h-6 rounded border"
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
        <div className="grid grid-cols-4 gap-1.5 pt-2">
          {enabled.map((b) => (
            <button
              key={b.id}
              data-testid="basemap-option"
              onClick={() => {
                onChange(b.id);
                setOpen(false);
              }}
              className={cn(
                'flex flex-col items-center gap-0.5 rounded-md p-1 transition-all',
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
