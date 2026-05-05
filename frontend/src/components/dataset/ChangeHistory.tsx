import { useTranslation } from 'react-i18next';
import { useDatasetHistory } from '@/components/dataset/hooks/use-dataset';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatDate } from '@/lib/format';
import { History } from 'lucide-react';
import { LoadingState } from '@/components/layout/LoadingState';
import type { AuditLogResponse } from '@/types/api';

interface ChangeHistoryProps {
  datasetId: string;
}

const actionLabelKeys: Record<string, string> = {
  'metadata.edit': 'changeHistory.actions.metadataEdit',
  'dataset.delete': 'changeHistory.actions.datasetDelete',
  'dataset.create': 'changeHistory.actions.datasetCreate',
};

export function ChangeHistory({ datasetId }: ChangeHistoryProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading, isError } = useDatasetHistory(datasetId, 0, 20);

  function getActionLabel(action: string): string {
    const key = actionLabelKeys[action];
    return key ? t(key) : action.charAt(0).toUpperCase() + action.slice(1);
  }

  function formatDetails(log: AuditLogResponse): string | null {
    if (!log.details || Object.keys(log.details).length === 0) return null;
    if (log.action === 'metadata.edit') {
      return `${t('changeHistory.changed')} ${Object.keys(log.details).join(', ')}`;
    }
    return Object.keys(log.details).join(', ');
  }

  const entries =
    data?.logs.filter((log) => log.action !== 'dataset.view') ?? [];
  const total = entries.length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="h-5 w-5" />
          {t('changeHistory.title', { count: total })}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingState className="py-6" />
        ) : isError ? (
          <p className="text-sm text-muted-foreground">{t('changeHistory.loadFailed')}</p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('changeHistory.noChanges')}</p>
        ) : (
          <div className="space-y-4">
            {entries.map((log) => {
              const details = formatDetails(log);
              return (
                <div
                  key={log.id}
                  className="border-s-2 border-muted ps-4 space-y-0.5"
                >
                  <p className="text-sm font-medium">{getActionLabel(log.action)}</p>
                  <p className="text-xs text-muted-foreground">
                    {log.username ?? t('changeHistory.system')} &middot; {formatDate(log.created_at)}
                  </p>
                  {details && (
                    <p className="text-xs text-muted-foreground">{details}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
