import { useState, useRef, useEffect } from 'react';
import { Check } from 'lucide-react';
import { useBasemaps } from '@/hooks/use-settings';
import { basemapThumbnail } from '@/lib/basemap-utils';
import { cn } from '@/lib/utils';

interface BasemapToggleProps {
  value: string;
  onChange: (id: string) => void;
  title?: string;
  className?: string;
}

/** Basemap selector — shows current basemap thumbnail as button, opens a labeled picker on click */
export function BasemapToggle({ value, onChange, title = 'Change basemap', className }: BasemapToggleProps) {
  const { data: basemaps } = useBasemaps();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const enabled = (basemaps ?? []).filter((b) => b.enabled);
  const current = enabled.find((b) => b.id === value);

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
      {/* Trigger: shows current basemap thumbnail */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="rounded-lg border-2 border-background shadow-lg overflow-hidden hover:border-primary/50 transition-colors"
        title={title}
        aria-label={title}
      >
        <img
          src={basemapThumbnail(value)}
          alt={current?.label ?? title}
          className="w-16 h-16 object-cover"
        />
      </button>

      {/* Popover: grid of basemap options with labels */}
      {open && (
        <div className="absolute bottom-0 left-full ml-2 bg-background/95 backdrop-blur-sm border rounded-lg shadow-lg p-2 flex flex-col gap-1.5 min-w-[140px]">
          {enabled.map((b) => {
            const isActive = value === b.id;
            return (
              <button
                key={b.id}
                type="button"
                onClick={() => { onChange(b.id); setOpen(false); }}
                className={cn(
                  'flex items-center gap-2 rounded-md px-1.5 py-1 transition-colors text-left',
                  isActive
                    ? 'bg-accent'
                    : 'hover:bg-accent/50',
                )}
                aria-label={b.label}
              >
                <img
                  src={basemapThumbnail(b.id)}
                  alt={b.label}
                  className="w-9 h-9 rounded border object-cover shrink-0"
                />
                <span className="text-xs font-medium truncate flex-1">{b.label}</span>
                {isActive && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
