import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { DatasetResponse, DatasetRetention } from '@/types/api';
import { useSetDatasetRetention } from '@/components/dataset/hooks/use-dataset';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { formatMutationError } from '@/lib/error-map';
import { formatDate } from '@/lib/format';

const MAX_DAYS = 3650;
// The record types the API gives a feature table; it also requires geometry.
const FEATURE_RECORD_TYPES = new Set(['vector_dataset', 'table']);

// The names the API accepts for a retention column (DatasetRetention.validate_column).
const PLAIN_COLUMN_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

function isTemporalType(type: string): boolean {
  const t = type.toLowerCase();
  return t === 'date' || t.startsWith('timestamp');
}

function parseDays(raw: string): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const days = Number(raw);
  return days >= 1 && days <= MAX_DAYS ? days : null;
}

interface PendingConfirm {
  retention: DatasetRetention;
  rows: number;
  cutoff: string | null;
}

interface RetentionCardProps {
  dataset: DatasetResponse;
  canEdit: boolean;
}

export function RetentionCard({ dataset, canEdit }: RetentionCardProps) {
  const { t, i18n } = useTranslation('dataset');
  const mutation = useSetDatasetRetention();
  const current = dataset.retention ?? null;
  const temporalColumns = useMemo(
    () => (dataset.column_info ?? []).filter(
      (column) => isTemporalType(column.type) && PLAIN_COLUMN_RE.test(column.name),
    ),
    [dataset.column_info],
  );
  const savedColumn = current?.column ?? '';
  const savedDays = current ? String(current.days) : '';
  const [column, setColumn] = useState(savedColumn);
  const [daysInput, setDaysInput] = useState(savedDays);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);

  useEffect(() => {
    setColumn(savedColumn);
    setDaysInput(savedDays);
  }, [savedColumn, savedDays]);

  const isFeatureDataset =
    FEATURE_RECORD_TYPES.has(dataset.record_type ?? 'vector_dataset') && dataset.geometry_type != null;
  if (!canEdit || !isFeatureDataset) return null;

  const days = parseDays(daysInput);
  const canSave = column !== '' && days !== null && !mutation.isPending;

  // A date column's cutoff is UTC midnight of its date; formatted as a
  // local instant it would name the day before west of UTC.
  function formatCutoff({ retention, cutoff }: PendingConfirm): string {
    const type = temporalColumns.find((option) => option.name === retention.column)?.type;
    return formatDate(type?.toLowerCase() === 'date' && cutoff ? cutoff.slice(0, 10) : cutoff);
  }

  async function save(retention: DatasetRetention | null) {
    try {
      await mutation.mutateAsync({ datasetId: dataset.id, retention });
      toast.success(retention ? t('retention.saved') : t('retention.turnedOff'));
    } catch (err) {
      toast.error(formatMutationError('dataset:retention.saveFailed', err));
    }
  }

  async function handleSave() {
    if (days === null || column === '') return;
    const retention = { column, days };
    try {
      const preview = await mutation.mutateAsync({ datasetId: dataset.id, retention, dryRun: true });
      if (preview.rows_past_cutoff > 0) {
        setConfirm({ retention, rows: preview.rows_past_cutoff, cutoff: preview.cutoff ?? null });
        return;
      }
    } catch (err) {
      toast.error(formatMutationError('dataset:retention.saveFailed', err));
      return;
    }
    await save(retention);
  }

  return (
    <Card data-field-anchor="retention">
      <CardHeader>
        <CardTitle level={2} className="text-base">{t('retention.title')}</CardTitle>
        <CardDescription>{t('retention.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm" data-testid="retention-status">
          {current
            ? t('retention.statusOn', { count: current.days, column: current.column })
            : t('retention.statusOff')}
        </p>
        {temporalColumns.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('retention.noTemporalColumns')}</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="retention-column">{t('retention.columnLabel')}</Label>
              <Select value={column} onValueChange={setColumn} disabled={mutation.isPending}>
                <SelectTrigger id="retention-column" className="w-full">
                  <SelectValue placeholder={t('retention.columnPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {temporalColumns.map((option) => (
                      <SelectItem key={option.name} value={option.name}>{option.name}</SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="retention-days">{t('retention.daysLabel')}</Label>
              <Input
                id="retention-days"
                type="number"
                inputMode="numeric"
                min={1}
                max={MAX_DAYS}
                step={1}
                value={daysInput}
                onChange={(event) => setDaysInput(event.target.value)}
                aria-describedby="retention-days-hint"
                aria-invalid={daysInput !== '' && days === null ? true : undefined}
                disabled={mutation.isPending}
              />
              <p id="retention-days-hint" className="text-xs text-muted-foreground">{t('retention.daysHint')}</p>
            </div>
          </div>
        )}
        {(temporalColumns.length > 0 || current) && (
          <div className="flex gap-2">
            {temporalColumns.length > 0 && (
              <Button size="sm" onClick={handleSave} disabled={!canSave}>
                {mutation.isPending ? t('retention.saving') : t('retention.save')}
              </Button>
            )}
            {current && (
              <Button size="sm" variant="outline" onClick={() => save(null)} disabled={mutation.isPending}>
                {t('retention.turnOff')}
              </Button>
            )}
          </div>
        )}
      </CardContent>

      <AlertDialog open={confirm !== null} onOpenChange={(open) => { if (!open) setConfirm(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('retention.confirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirm && t('retention.confirmDescription', {
                count: confirm.rows,
                formattedCount: confirm.rows.toLocaleString(i18n.language),
                cutoff: formatCutoff(confirm),
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={mutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (!confirm) return;
                const { retention } = confirm;
                setConfirm(null);
                void save(retention);
              }}
            >
              {t('retention.confirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
