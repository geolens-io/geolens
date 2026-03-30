import { useState, useRef, useEffect } from 'react';
import { Map as MapIcon } from 'lucide-react';
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

interface BasemapToggleProps {
  value: string;
  onChange: (id: string) => void;
  className?: string;
}

/** Compact basemap selector button with popover for map overlays */
export function BasemapToggle({ value, onChange, className }: BasemapToggleProps) {
  const { data: basemaps } = useBasemaps();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const enabled = (basemaps ?? []).filter((b) => b.enabled);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  if (enabled.length <= 1) return null;

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="bg-background border rounded shadow-sm p-1.5 hover:bg-accent"
        title="Change basemap"
        aria-label="Change basemap"
      >
        <MapIcon className="h-4 w-4" />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 mb-1 bg-background border rounded-lg shadow-lg p-1.5 flex gap-1">
          {enabled.map((b) => (
            <button
              key={b.id}
              type="button"
              onClick={() => { onChange(b.id); setOpen(false); }}
              className={cn(
                'rounded overflow-hidden border-2 transition-colors',
                value === b.id ? 'border-primary' : 'border-transparent hover:border-muted-foreground/30',
              )}
              title={b.label}
              aria-label={b.label}
            >
              <img
                src={BUILTIN_THUMBNAILS[b.id] ?? positronThumb}
                alt={b.label}
                className="w-10 h-10 object-cover"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
