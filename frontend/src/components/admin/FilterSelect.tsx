import { useId } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

const ALL_VALUE = '__all__';

interface FilterSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  className?: string;
  /** Accessible name for the trigger when `label` is intentionally empty
   *  (e.g. a layout that hides the visible label). Must be already localized. */
  ariaLabel?: string;
}

/**
 * Themed filter dropdown using shadcn Select.
 * Converts empty-string values to a sentinel internally since Radix
 * Select does not support empty string values.
 */
export function FilterSelect({ label, value, onChange, options, className, ariaLabel }: FilterSelectProps) {
  const labelId = useId();
  return (
    <div className={className}>
      {label && (
        <label id={labelId} className="mb-1 block text-xs text-muted-foreground">
          {label}
        </label>
      )}
      <Select
        value={value || ALL_VALUE}
        onValueChange={(v) => onChange(v === ALL_VALUE ? '' : v)}
      >
        {/* a11y: associate the visible label with the combobox trigger so it has
            an accessible name (WCAG 4.1.2). When a caller intentionally omits the
            visible label, fall back to the localized `ariaLabel`. */}
        <SelectTrigger
          className="h-8 w-auto min-w-[140px]"
          aria-labelledby={label ? labelId : undefined}
          aria-label={label ? undefined : ariaLabel}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value || ALL_VALUE} value={opt.value || ALL_VALUE}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
