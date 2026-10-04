import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface FilterChipProps {
  label: string;
  onRemove: () => void;
  /** Makes the label itself a button; remove stays a sibling control. */
  onSelect?: () => void;
}

export function FilterChip({ label, onRemove, onSelect }: FilterChipProps) {
  const { t } = useTranslation('search');
  return (
    <Badge variant="secondary" className="gap-1 pe-1">
      {onSelect ? (
        <button
          type="button"
          onClick={onSelect}
          className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {label}
        </button>
      ) : (
        label
      )}
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onRemove(); }}
        className="ms-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20 transition-colors duration-150"
        aria-label={t('filters.removeFilter', { label })}
      >
        <X className="size-3" />
      </button>
    </Badge>
  );
}
