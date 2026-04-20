import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Search, X } from 'lucide-react';

interface DataTableSearchProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** When set, debounces the onChange callback by this many ms.
   *  The input updates immediately but onChange fires after the delay. */
  debounceMs?: number;
}

export function DataTableSearch({ value, onChange, placeholder, debounceMs }: DataTableSearchProps) {
  const { t } = useTranslation('common');
  const [internal, setInternal] = useState(value);
  const isControlled = useRef(true);

  // Sync external value → internal (e.g. when parent resets)
  useEffect(() => {
    if (isControlled.current) {
      setInternal(value);
    }
    isControlled.current = true;
  }, [value]);

  // Debounced onChange
  useEffect(() => {
    if (!debounceMs) return;
    const timer = setTimeout(() => onChange(internal), debounceMs);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [internal, debounceMs]);

  function handleChange(v: string) {
    setInternal(v);
    if (!debounceMs) {
      onChange(v);
    } else {
      isControlled.current = false;
    }
  }

  function handleClear() {
    setInternal('');
    onChange('');
  }

  return (
    <div className="relative">
      <Search className="absolute start-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={debounceMs ? internal : value}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder ?? t('search')}
        className="h-8 ps-8 pe-8 text-sm"
      />
      {(debounceMs ? internal : value) && (
        <button
          type="button"
          onClick={handleClear}
          className="absolute end-2 top-1/2 -translate-y-1/2 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
