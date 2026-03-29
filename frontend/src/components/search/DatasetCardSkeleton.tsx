import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function DatasetCardSkeleton() {
  return (
    <div className="block">
      <Card className="overflow-hidden border-border/60 py-0">
        <div className="p-4 sm:p-5">
          <div className="flex flex-col gap-3">
            {/* Band 1 — Header */}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_80px]">
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap gap-2">
                  <Skeleton className="h-6 w-16 rounded-full" />
                </div>
                <Skeleton className="h-6 w-4/5" />
                <Skeleton className="h-4 w-2/3" />
              </div>
              <div className="hidden md:block">
                <Skeleton className="h-[80px] w-[80px] rounded-lg" />
              </div>
            </div>
            {/* Band 2 — Facts */}
            <div className="flex flex-wrap gap-1.5">
              <Skeleton className="h-6 w-24 rounded-full" />
              <Skeleton className="h-6 w-28 rounded-full" />
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
            {/* Band 3 — Tags */}
            <div className="flex flex-wrap gap-1.5">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
            {/* Band 4 — Footer */}
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-36" />
              <Skeleton className="h-5 w-14 rounded-full" />
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
