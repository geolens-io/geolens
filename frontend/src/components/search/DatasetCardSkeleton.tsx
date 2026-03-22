import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function DatasetCardSkeleton() {
  return (
    <div className="block">
      <Card className="flex flex-col sm:flex-row gap-0 py-0 overflow-hidden cursor-pointer">
        <div className="flex-1 p-3 space-y-2">
          <Skeleton className="h-5 w-3/4" />
          <div className="space-y-1.5">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-4 w-16 rounded-full" />
            <Skeleton className="h-4 w-20 rounded-full" />
            <Skeleton className="h-4 w-12 rounded-full" />
            <Skeleton className="h-4 w-24 rounded-full" />
          </div>
          <div className="flex gap-1">
            <Skeleton className="h-4 w-14 rounded-full" />
            <Skeleton className="h-4 w-18 rounded-full" />
          </div>
          <Skeleton className="h-3 w-48" />
        </div>
        <div className="sm:w-40 sm:flex-shrink-0 p-3 sm:p-3 sm:border-l border-t sm:border-t-0 border-border/50">
          <Skeleton className="w-full h-[120px] rounded" />
        </div>
      </Card>
    </div>
  );
}
