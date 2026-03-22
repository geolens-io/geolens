import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface FilterChipProps {
  label: string;
  onRemove: () => void;
}

export function FilterChip({ label, onRemove }: FilterChipProps) {
  const { t } = useTranslation('search');
  return (
    <Badge variant="secondary" className="gap-1 pr-1">
      {label}
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onRemove(); }}
        className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20 transition-colors duration-150"
        aria-label={t('filters.removeFilter', { label })}
      >
        <X className="size-3" />
      </button>
    </Badge>
  );
}
