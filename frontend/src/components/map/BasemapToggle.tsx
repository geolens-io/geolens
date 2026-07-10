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

const POPOVER_ID = 'basemap-toggle-popover';

/** Basemap selector — keyboard-complete disclosure (PR #330: aria-expanded/controls,
 *  aria-current on options, Escape-to-close, focus-return to trigger). */
export function BasemapToggle({ value, onChange, title = 'Change basemap', className }: BasemapToggleProps) {
  const { data: basemaps } = useBasemaps();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const enabled = (basemaps ?? []).filter((b) => b.enabled);
  const current = enabled.find((b) => b.id === value);

  // Shared close-and-return-focus helper
  function closeAndReturnFocus() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        closeAndReturnFocus();
      }
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [open]);

  // Escape to close (mirrors LayerLegend pattern)
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeAndReturnFocus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  if (enabled.length <= 1) return null;

  return (
    <div ref={containerRef} className={cn('relative', className)}>
      {/* Trigger: shows current basemap thumbnail */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(!open)}
        className="rounded-lg border-2 border-background shadow-lg overflow-hidden hover:border-primary/50 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        title={title}
        aria-label={title}
        aria-expanded={open}
        aria-controls={open ? POPOVER_ID : undefined}
        aria-haspopup="menu"
      >
        <img
          src={basemapThumbnail(value)}
          alt={current?.label ?? title}
          className="w-16 h-16 object-cover"
        />
      </button>

      {/* Popover: list of basemap options with labels */}
      {open && (
        <div
          id={POPOVER_ID}
          role="group"
          aria-label={title}
          className="absolute bottom-0 left-full ms-2 bg-background/95 backdrop-blur-sm border rounded-lg shadow-lg p-2 flex flex-col gap-1.5 min-w-[140px]"
        >
          {enabled.map((b) => {
            const isActive = value === b.id;
            return (
              <button
                key={b.id}
                type="button"
                aria-current={isActive ? true : undefined}
                onClick={() => { onChange(b.id); closeAndReturnFocus(); }}
                className={cn(
                  'flex items-center gap-2 rounded-md px-1.5 py-1 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  isActive
                    ? 'bg-accent'
                    : 'hover:bg-accent/50',
                )}
                aria-label={b.label}
              >
                <img
                  src={basemapThumbnail(b.id)}
                  alt={b.label}
                  className="w-9 h-9 rounded-sm border object-cover shrink-0"
                />
                <span className="text-xs font-medium truncate flex-1">{b.label}</span>
                {isActive && <Check className="h-3.5 w-3.5 text-primary shrink-0" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
