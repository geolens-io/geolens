import { PageShell } from '@/components/layout/PageShell';
import { Skeleton } from '@/components/ui/skeleton';

interface DatasetDetailSkeletonProps {
  isTable?: boolean;
}

export function DatasetDetailSkeleton({ isTable }: DatasetDetailSkeletonProps = {}) {
  return (
    <PageShell>
      {/* Breadcrumb skeleton */}
      <div className="space-y-3">
        <Skeleton className="h-4 w-40" />
        <div className="flex items-start justify-between gap-4">
          <Skeleton className="h-7 w-64" />
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-8 w-20" />
          </div>
        </div>
      </div>

      {/* Stats line skeleton */}
      <div className="flex items-center gap-2">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-16" />
      </div>

      {/* Hero placeholder — compact card for tables, tall map for spatial */}
      {isTable ? (
        <div className="rounded-lg border bg-muted/20 px-4 py-4">
          <div className="flex items-start gap-3">
            <Skeleton className="h-9 w-9 rounded-lg" />
            <div className="space-y-2 flex-1">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-80" />
            </div>
          </div>
        </div>
      ) : (
        <Skeleton className="w-full rounded-lg h-72 lg:h-96" data-testid="hero-skeleton" />
      )}

      {/* Tab bar skeleton */}
      <div className="flex items-center gap-1">
        <Skeleton className="h-9 w-24 rounded-md" />
        <Skeleton className="h-9 w-16 rounded-md" />
        <Skeleton className="h-9 w-20 rounded-md" />
        <Skeleton className="h-9 w-14 rounded-md" />
      </div>

      {/* Content area skeleton (resembles overview tab) */}
      <div className="space-y-6">
        {/* Metadata card skeleton */}
        <div className="rounded-lg border p-6 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-5 w-40" />
              </div>
            ))}
          </div>
          <Skeleton className="h-px w-full" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-5 w-36" />
              </div>
            ))}
          </div>
        </div>

        {/* Quality score card skeleton */}
        <div className="rounded-lg border p-6 space-y-3">
          <div className="flex items-center justify-between">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="h-6 w-10 rounded-full" />
          </div>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="space-y-1">
              <Skeleton className="h-3 w-40" />
              <Skeleton className="h-2 w-full rounded-full" />
            </div>
          ))}
        </div>
      </div>
    </PageShell>
  );
}
