import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { ChevronDown, Link2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { listRelationships, getRelatedRecords } from '@/api/datasets';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/layout/ErrorState';
import { cn } from '@/lib/utils';
import type { DatasetRelationship, DatasetRowsResponse } from '@/types/api';

interface RelatedRecordsPanelProps {
  datasetId: string;
  featureGid: number;
}

function RelatedSection({
  datasetId,
  featureGid,
  relationship,
}: {
  datasetId: string;
  featureGid: number;
  relationship: DatasetRelationship;
}) {
  const { t } = useTranslation('dataset');
  const [open, setOpen] = useState(false);

  const { data, isLoading, isError } = useQuery<DatasetRowsResponse>({
    queryKey: queryKeys.relationships.records(datasetId, featureGid, relationship.id),
    queryFn: () => getRelatedRecords(datasetId, featureGid, relationship.id, { limit: 50 }),
    enabled: open,
  });

  const label = relationship.label || relationship.target_dataset_title || t('relatedRecords.title');

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-muted/50 transition-colors">
        <Link2 className="size-4 text-muted-foreground flex-shrink-0" />
        <span className="flex-1 text-left truncate">{label}</span>
        <span className="text-xs text-muted-foreground">
          {relationship.source_column} &rarr; {relationship.target_column}
        </span>
        <ChevronDown className={cn('size-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-3 pb-3">
          {isLoading && (
            <div className="space-y-2 py-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          )}
          {isError && (
            <p className="text-sm text-muted-foreground py-2">{t('relatedRecords.loadError')}</p>
          )}
          {data && data.rows.length === 0 && (
            <p className="text-sm text-muted-foreground py-2">{t('relatedRecords.noRecords')}</p>
          )}
          {data && data.rows.length > 0 && (
            <div className="overflow-x-auto rounded border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-muted/50 border-b">
                    {data.columns.map((col) => (
                      <th key={col.name} className="px-2 py-1.5 text-left font-medium whitespace-nowrap">
                        {col.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={row.gid != null ? String(row.gid) : i} className="border-b last:border-0 hover:bg-muted/30">
                      {data.columns.map((col) => (
                        <td key={col.name} className="px-2 py-1.5 whitespace-nowrap max-w-[200px] truncate">
                          {row[col.name] != null ? String(row[col.name]) : ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.approximate_total > data.rows.length && (
                <div className="text-xs text-muted-foreground text-center py-1.5 border-t bg-muted/30">
                  {t('relatedRecords.showingCount', { shown: data.rows.length, total: data.approximate_total })}
                </div>
              )}
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function RelatedRecordsPanel({ datasetId, featureGid }: RelatedRecordsPanelProps) {
  const { t } = useTranslation('dataset');

  const { data: relationships, isLoading, isError } = useQuery<DatasetRelationship[]>({
    queryKey: queryKeys.relationships.list(datasetId),
    queryFn: () => listRelationships(datasetId),
  });

  if (isLoading) {
    return (
      <div className="space-y-2 p-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (isError) {
    return <ErrorState message={t('relatedRecords.error')} />;
  }

  if (!relationships || relationships.length === 0) {
    return null;
  }

  return (
    <div className="border rounded-lg bg-card">
      <div className="px-3 py-2 border-b">
        <h4 className="text-sm font-medium">
          {t('relatedRecords.title')}
        </h4>
      </div>
      <div className="divide-y">
        {relationships.map((rel) => (
          <RelatedSection
            key={rel.id}
            datasetId={datasetId}
            featureGid={featureGid}
            relationship={rel}
          />
        ))}
      </div>
    </div>
  );
}
