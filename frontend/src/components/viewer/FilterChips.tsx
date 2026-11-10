import { useRef, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { LinkedPick } from './linked-filters';

/**
 * One button per pick, which clears it. Focus then moves to the next chip,
 * else the previous, else `fallbackFocus`.
 */
export function FilterChips({
  picks,
  layerName,
  pickLabel,
  onRemove,
  fallbackFocus,
  className,
}: {
  picks: readonly LinkedPick[];
  layerName: (layerId: string) => string;
  /** The pick as its chip reads. */
  pickLabel: (pick: LinkedPick) => string;
  onRemove: (pick: LinkedPick) => void;
  fallbackFocus: RefObject<HTMLElement | null>;
  className?: string;
}) {
  const { t } = useTranslation('widgets');
  const chips = useRef(new Map<string, HTMLButtonElement>());
  if (picks.length === 0) return null;

  const remove = (index: number) => {
    onRemove(picks[index]);
    const neighbour = picks[index + 1] ?? picks[index - 1];
    (neighbour ? chips.current.get(neighbour.widgetId) : fallbackFocus.current)?.focus();
  };

  return (
    <div role="group" aria-label={t('dashboard.filters')} className={cn('flex flex-wrap gap-1.5', className)}>
      {picks.map((pick, index) => (
        <Button
          key={pick.widgetId}
          ref={(button) => {
            if (button) chips.current.set(pick.widgetId, button);
            else chips.current.delete(pick.widgetId);
          }}
          type="button"
          variant="secondary"
          size="xs"
          className="max-w-full"
          aria-label={t('dashboard.removeFilter', { filter: pickLabel(pick), layer: layerName(pick.layerId) })}
          onClick={() => remove(index)}
        >
          <span className="truncate">{pickLabel(pick)}</span>
          <X aria-hidden="true" />
        </Button>
      ))}
    </div>
  );
}
