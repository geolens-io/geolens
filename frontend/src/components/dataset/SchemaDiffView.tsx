import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { formatNumber } from '@/lib/format';
import type { SchemaDiff } from '@/types/api';

interface SchemaDiffViewProps {
  schemaDiff: SchemaDiff;
}

export function SchemaDiffView({ schemaDiff }: SchemaDiffViewProps) {
  const { t } = useTranslation('dataset');
  const hasChanges =
    schemaDiff.columns_added.length > 0 ||
    schemaDiff.columns_removed.length > 0 ||
    schemaDiff.type_changes.length > 0;

  return (
    <div className="space-y-4">
      {/* Row count comparison */}
      <div className="grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="text-xs text-muted-foreground">{t('schemaDiff.currentRows')}</p>
          <p className="text-lg font-semibold">
            {schemaDiff.row_count_old !== null
              ? formatNumber(schemaDiff.row_count_old)
              : t('common:notAvailable')}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('schemaDiff.newRows')}</p>
          <p className="text-lg font-semibold">
            {schemaDiff.row_count_new !== null
              ? formatNumber(schemaDiff.row_count_new)
              : t('common:notAvailable')}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('schemaDiff.delta')}</p>
          <p
            className={cn(
              'text-lg font-semibold',
              schemaDiff.row_count_delta > 0 && 'text-success',
              schemaDiff.row_count_delta < 0 && 'text-destructive',
            )}
          >
            {schemaDiff.row_count_delta > 0 ? '+' : ''}
            {formatNumber(schemaDiff.row_count_delta)}
          </p>
        </div>
      </div>

      {/* Columns Added */}
      {schemaDiff.columns_added.length > 0 && (
        <div className="rounded-md bg-success/10 p-3">
          <p className="text-sm font-medium text-success">
            {t('schemaDiff.columnsAdded', { count: schemaDiff.columns_added.length })}
          </p>
          <div className="mt-2 space-y-1">
            {schemaDiff.columns_added.map((col) => (
              <div
                key={col.name}
                className="flex items-center justify-between text-sm"
              >
                <span className="font-mono text-xs">{col.name}</span>
                <span className="text-xs text-muted-foreground">{col.type}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Columns Removed */}
      {schemaDiff.columns_removed.length > 0 && (
        <div className="rounded-md bg-destructive/10 p-3">
          <p className="text-sm font-medium text-destructive">
            {t('schemaDiff.columnsRemoved', { count: schemaDiff.columns_removed.length })}
          </p>
          <div className="mt-2 space-y-1">
            {schemaDiff.columns_removed.map((col) => (
              <div
                key={col.name}
                className="flex items-center justify-between text-sm"
              >
                <span className="font-mono text-xs">{col.name}</span>
                <span className="text-xs text-muted-foreground">{col.type}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Type Changes */}
      {schemaDiff.type_changes.length > 0 && (
        <div className="rounded-md bg-warning/10 p-3">
          <p className="text-sm font-medium text-warning">
            {t('schemaDiff.typeChanges', { count: schemaDiff.type_changes.length })}
          </p>
          <div className="mt-2 space-y-1">
            {schemaDiff.type_changes.map((col) => (
              <div
                key={col.name}
                className="flex items-center justify-between text-sm"
              >
                <span className="font-mono text-xs">{col.name}</span>
                <span className="text-xs text-muted-foreground">
                  {col.old_type} &rarr; {col.new_type}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* No changes message */}
      {!hasChanges && schemaDiff.row_count_delta === 0 && (
        <p className="text-sm text-muted-foreground">
          {t('schemaDiff.noChanges')}
        </p>
      )}
    </div>
  );
}
