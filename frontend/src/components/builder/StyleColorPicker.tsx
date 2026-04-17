import { useState, useEffect, useRef, useCallback } from 'react';
import { HexColorPicker, HexColorInput } from 'react-colorful';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

interface StyleColorPickerProps {
  label: string;
  color: string;
  onChange: (hex: string) => void;
}

const HEX_REGEX = /^#[0-9a-fA-F]{6}$/;

// Map symbol preset colors — not UI chrome; exempt from design token rule
const PRESET_COLORS = [
  '#3b82f6', // blue
  '#ef4444', // red
  '#22c55e', // green
  '#f59e0b', // amber
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#f97316', // orange
  '#14b8a6', // teal
  '#6366f1', // indigo
  '#84cc16', // lime
  '#a855f7', // purple
  '#0ea5e9', // sky
  '#d946ef', // fuchsia
  '#64748b', // slate
  '#1e293b', // dark
];

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
            className="w-8 h-6 rounded border border-border cursor-pointer"
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
                  'w-5 h-5 rounded-sm border transition-transform hover:scale-125',
                  localColor === hex ? 'ring-2 ring-primary ring-offset-background' : 'border-border',
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
            className="mt-2 w-full text-xs border rounded px-2 py-1 bg-background text-foreground"
            prefixed
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
