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
}

/**
 * Themed filter dropdown using shadcn Select.
 * Converts empty-string values to a sentinel internally since Radix
 * Select does not support empty string values.
 */
export function FilterSelect({ label, value, onChange, options, className }: FilterSelectProps) {
  return (
    <div className={className}>
      {label && (
        <label className="mb-1 block text-xs text-muted-foreground">
          {label}
        </label>
      )}
      <Select
        value={value || ALL_VALUE}
        onValueChange={(v) => onChange(v === ALL_VALUE ? '' : v)}
      >
        <SelectTrigger className="h-8 w-auto min-w-[140px]">
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
