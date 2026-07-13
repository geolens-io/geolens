import { useState, useEffect, useRef, useCallback } from 'react';
import { HexColorPicker, HexColorInput } from 'react-colorful';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { MAP_COLORS } from '@/lib/map-colors';

interface StyleColorPickerProps {
  label: string;
  color: string;
  onChange: (hex: string) => void;
}

// builder-audit #338 DRY-02: single source for the 6-digit hex validation regex.
// Previously copied inline in DataDrivenStyleEditor (two sites).
export const HEX_REGEX = /^#[0-9a-fA-F]{6}$/;

// Map symbol preset colors — not UI chrome. Reuse the centralized map palette
// so a newly created layer always has a selected preset swatch.
export const PRESET_COLORS = [
  ...MAP_COLORS.categorical,
  MAP_COLORS.selection.fill,
  MAP_COLORS.drawing.fill,
  MAP_COLORS.closing.point,
  MAP_COLORS.ephemeral.color,
  MAP_COLORS.icon.outline,
  MAP_COLORS.label.color,
  MAP_COLORS.cluster.text,
  MAP_COLORS.canvas.background,
] as const;

/**
 * builder-audit #338 DRY-02: compact swatch button + popover hex editor shared by the
 * DataDrivenStyleEditor categorical and graduated color lists. Replaces two
 * near-identical inline Popover+HexColorPicker+HexColorInput blocks (each with
 * its own copy of the hex regex). Debouncing, if any, is owned by the caller's
 * onChange (the data-driven editor debounces map repaints there).
 */
export function SwatchColorPopover({
  color,
  onChange,
  label,
}: {
  color: string;
  onChange: (hex: string) => void;
  label?: string;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="w-5 h-5 rounded-sm border border-border shrink-0 cursor-pointer hover:ring-2 hover:ring-ring/30 transition-shadow"
          style={{ background: color }}
          title={color}
          aria-label={label ?? color}
        />
      </PopoverTrigger>
      <PopoverContent className="w-auto p-3" align="start" side="right">
        <HexColorPicker color={color} onChange={onChange} />
        <HexColorInput
          color={color}
          onChange={(hex) => {
            if (HEX_REGEX.test(hex)) onChange(hex);
          }}
          className="mt-2 w-full text-xs border rounded-sm px-2 py-1 bg-background text-foreground"
          prefixed
        />
      </PopoverContent>
    </Popover>
  );
}

export function StyleColorPicker({ label, color, onChange }: StyleColorPickerProps) {
  const [localColor, setLocalColor] = useState(color);
  useEffect(() => { setLocalColor(color); }, [color]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const debouncedChange = useCallback((c: string) => {
    setLocalColor(c);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => onChange(c), 100);
  }, [onChange]);

  function handleInputChange(hex: string) {
    if (HEX_REGEX.test(hex)) {
      onChange(hex);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground w-20">{label}</span>
      <Popover>
        <PopoverTrigger asChild>
          <button
            className="w-8 h-6 rounded-sm border border-border cursor-pointer"
            style={{ background: localColor }}
            title={localColor}
            aria-label={label}
          />
        </PopoverTrigger>
        <PopoverContent className="w-auto p-3" align="start">
          {/* Preset swatches */}
          <div className="grid grid-cols-8 gap-1 mb-3">
            {PRESET_COLORS.map((hex) => (
              <button
                key={hex}
                type="button"
                onClick={() => onChange(hex)}
                className={cn(
                  'cursor-pointer w-5 h-5 rounded-sm border transition-transform hover:scale-125',
                  localColor === hex ? 'ring-2 ring-primary ring-offset-1 ring-offset-background' : 'border-border',
                )}
                style={{ background: hex }}
                title={hex}
                aria-label={hex}
              />
            ))}
          </div>

          {/* Full color picker */}
          <HexColorPicker color={localColor} onChange={debouncedChange} />
          <HexColorInput
            color={localColor}
            onChange={handleInputChange}
            className="mt-2 w-full text-xs border rounded-sm px-2 py-1 bg-background text-foreground"
            prefixed
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
