import { memo } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import type { MapStackGroup } from '@/components/builder/map-stack';

interface MapStackSectionProps {
  group: MapStackGroup;
  entryCount: number;
  children: ReactNode;
}

export const MapStackSection = memo(function MapStackSection({
  group,
  entryCount,
  children,
}: MapStackSectionProps) {
  const { t } = useTranslation('builder');
  const titleId = `map-stack-section-${group.id}`;

  return (
    <section
      className="border-t py-2 first:border-t-0"
      aria-labelledby={titleId}
    >
      <div className="mb-1 flex h-7 items-center justify-between gap-2 px-2">
        <h3 id={titleId} className="truncate text-xs font-semibold uppercase tracking-normal text-muted-foreground">
          {t(`mapStack.groups.${group.id}.title`, { defaultValue: group.title })}
        </h3>
        <Badge variant="secondary" className="h-5 min-w-5 rounded px-1.5 text-[10px]">
          {entryCount}
        </Badge>
      </div>
      <div className="space-y-1">
        {children}
      </div>
    </section>
  );
});
