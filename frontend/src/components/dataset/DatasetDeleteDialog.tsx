import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';
import { useDeleteDataset } from '@/components/dataset/hooks/use-dataset';
import type { DatasetResponse } from '@/types/api';
import { Input } from '@/components/ui/input';
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

interface DependentVrt {
  vrt_dataset_id: string;
  vrt_dataset_title: string;
}

function parseDependentVrts(error: Error): DependentVrt[] | null {
  try {
    const parsed = JSON.parse(error.message);
    if (parsed?.dependent_vrts && Array.isArray(parsed.dependent_vrts)) {
      return parsed.dependent_vrts;
    }
  } catch {
    // Not a structured VRT error
  }
  return null;
}

/**
 * Whether this delete leaves the operator's PostgreSQL table behind.
 *
 * fix(#1452): registering an existing table copies no data, so deleting the
 * dataset detaches instead of dropping. Both served facts come from the
 * server — `origin` is computed there (#1218) and `origin_ref.managed` is
 * stamped at registration — and `geolens_owns_table` in the backend's
 * platform/dataset_origin.py is the authority this mirrors for copy only.
 *
 * `managed` marks the one postgis-origin dataset GeoLens DID create: an
 * analysis output, CTAS'd and then registered through the same helper. That
 * table is dropped, so it must not get the reassuring wording.
 *
 * `origin_ref` is owner-or-admin only, which is exactly who can delete
 * (`check_dataset_write_access` is the same predicate as
 * `can_view_dataset_provenance`), so it is never redacted from a reader who
 * can act on this dialog.
 */
export function deleteDetachesTable(dataset: DatasetResponse): boolean {
  // fix(#1452 review round 3): the raster-family override comes FIRST, exactly
  // as it does in geolens_owns_table. A raster or VRT row whose source_format
  // is null derives origin 'postgis' — classify_origin reads a null format as
  // registered-in-place — and without this the dialog would promise a
  // PostgreSQL table survives a delete that reaps the dataset's storage
  // artifacts and retires its name. Registration only ever creates vector
  // datasets, so a raster-family record is GeoLens's by construction.
  if (dataset.record_type === 'raster_dataset' || dataset.record_type === 'vrt_dataset') {
    return false;
  }
  if (dataset.origin !== 'postgis') return false;
  return dataset.origin_ref?.managed !== true;
}

/**
 * Which description this delete gets.
 *
 * fix(#1452 review round 2): a registered dataset whose table has already
 * been dropped carries `source_health: 'missing'` — the PostGIS refresh maps
 * SQLSTATE 42P01 to it — and the backend detects that absent relation and
 * retires the name instead of preserving anything. Promising that its data
 * stays intact would be the one wrong thing to tell someone in that state.
 * The wording says "last saw" because the stored verdict is a past probe, not
 * a live check: the operator may have recreated the table since.
 */
export function deleteDescriptionKey(dataset: DatasetResponse): string {
  if (!deleteDetachesTable(dataset)) return 'deleteDialog.description';
  return dataset.source_health === 'missing'
    ? 'deleteDialog.descriptionRegisteredMissing'
    : 'deleteDialog.descriptionRegistered';
}

interface DatasetDeleteDialogProps {
  dataset: DatasetResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DatasetDeleteDialog({ dataset, open, onOpenChange }: DatasetDeleteDialogProps) {
  const { t } = useTranslation('dataset');
  const [confirmName, setConfirmName] = useState('');
  const deleteDataset = useDeleteDataset();
  const navigate = useNavigate();

  useEffect(() => {
    if (open) {
      setConfirmName('');
      // fix(#438): UX-12 — clear a prior failure so reopening the dialog starts
      // clean instead of showing the last attempt's error.
      deleteDataset.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset() identity is stable; reopen is the only trigger we want
  }, [open]);

  const isConfirmed = confirmName === dataset.title;

  async function handleDelete() {
    try {
      await deleteDataset.mutateAsync({ datasetId: dataset.id, confirmName });
      onOpenChange(false);
      navigate('/');
    } catch {
      // error displayed inline -- keep dialog open
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('deleteDialog.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t(deleteDescriptionKey(dataset), { name: dataset.title })}
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-2">
          {/* #305: link the confirm input to the prompt; placeholder is not an accessible name */}
          <p id="dataset-delete-confirm-prompt" className="text-sm font-medium">{t('deleteDialog.confirmPrompt')}</p>
          <Input
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={dataset.title}
            aria-labelledby="dataset-delete-confirm-prompt"
          />
        </div>

        {deleteDataset.error && (() => {
          const dependentVrts = deleteDataset.error instanceof Error
            ? parseDependentVrts(deleteDataset.error)
            : null;
          return (
          <div className="text-sm text-destructive space-y-1">
            {dependentVrts ? (
              <>
                <p>{t('deleteDialog.dependentVrtMessage')}</p>
                <ul className="space-y-0.5">
                  {dependentVrts.map((vrt) => (
                    <li key={vrt.vrt_dataset_id}>
                      <Link
                        to={`/datasets/${vrt.vrt_dataset_id}`}
                        className="underline hover:no-underline"
                        onClick={() => onOpenChange(false)}
                      >
                        {vrt.vrt_dataset_title}
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p>
                {deleteDataset.error instanceof Error
                  ? deleteDataset.error.message
                  : t('deleteDialog.failed')}
              </p>
            )}
          </div>
          );
        })()}

        <AlertDialogFooter>
          <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault();
              handleDelete();
            }}
            disabled={!isConfirmed || deleteDataset.isPending}
            variant="destructive"
          >
            {deleteDataset.isPending ? t('deleteDialog.deleting') : t('deleteDialog.deleteDataset')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
