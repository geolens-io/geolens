import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function MapCardSkeleton() {
  return (
    <Card className="!flex-row !gap-0 !py-0 items-start overflow-hidden">
      <div className="w-40 shrink-0 aspect-[8/5]">
        <Skeleton className="w-full h-full" />
      </div>
      <div className="flex-1 min-w-0 p-4 space-y-3">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-3 w-full" />
        <div className="flex gap-2">
          <Skeleton className="h-4 w-16 rounded-full" />
          <Skeleton className="h-4 w-24" />
        </div>
      </div>
    </Card>
  );
}
