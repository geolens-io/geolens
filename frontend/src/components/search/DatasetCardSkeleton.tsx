import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function DatasetCardSkeleton() {
  return (
    <div className="block">
      <Card className="overflow-hidden border-border/60 py-0">
        <div className="flex flex-col md:grid md:grid-cols-[minmax(0,1fr)_14rem]">
          <div className="space-y-3.5 p-4 sm:p-5">
            <div className="flex flex-wrap gap-2">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-24 rounded-full" />
              <Skeleton className="h-6 w-28 rounded-full" />
            </div>
            <div className="space-y-2">
              <Skeleton className="h-6 w-4/5" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
            <div className="flex flex-wrap gap-2">
              <Skeleton className="h-6 w-24 rounded-full" />
              <Skeleton className="h-6 w-28 rounded-full" />
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
            <div className="flex flex-wrap gap-2">
              <Skeleton className="h-5 w-16 rounded-full" />
              <Skeleton className="h-5 w-20 rounded-full" />
            </div>
            <Skeleton className="h-4 w-48" />
          </div>
          <div className="hidden border-t border-border/50 p-4 md:flex md:border-l md:border-t-0">
            <Skeleton className="h-[140px] w-full rounded-[20px]" />
          </div>
        </div>
      </Card>
    </div>
  );
}
