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
 * Registering an existing table copies no data, so deleting the dataset
 * detaches instead of dropping. Both served facts come from the server:
 * `origin` is computed there and `origin_ref.managed` is stamped at
 * registration. `geolens_owns_table` in the backend's
 * platform/dataset_origin.py is the authority this mirrors for copy only.
 *
 * `managed` marks the one postgis-origin dataset GeoLens DID create: an
 * analysis output, CTAS'd and registered through the same helper. That table
 * is dropped, so it must not get the reassuring wording.
 *
 * A readable `origin_ref` is REQUIRED before this promises anything.
 * `origin_ref` is owner-or-admin only, but the response carrying it is cached
 * under `['dataset', id]` with no identity in the key and a 60s staleTime, and
 * login invalidates only the auth caches. So an owner can be handed the
 * redacted response a non-owner or anonymous reader populated earlier, where
 * `origin_ref` is null for a reason unrelated to ownership. Null is also what
 * migration 0036's backfill leaves on rows it could not resolve. Reading
 * either as "not managed" would promise that an analysis output's table
 * survives a delete that drops it, the one direction this dialog must never be
 * wrong in. Absent evidence therefore falls back to the copy that warns the
 * data is destroyed: over-warning a registered table whose provenance we can't
 * read costs less than a false assurance.
 */
export function deleteDetachesTable(dataset: DatasetResponse): boolean {
  // The raster-family override comes FIRST, as in geolens_owns_table. A raster
  // or VRT row whose source_format is null derives origin 'postgis'
  // (classify_origin reads a null format as registered-in-place), and without
  // this the dialog would promise a PostgreSQL table survives a delete that
  // reaps the dataset's storage artifacts and retires its name. Registration
  // only creates vector datasets, so a raster-family record is GeoLens's.
  if (dataset.record_type === 'raster_dataset' || dataset.record_type === 'vrt_dataset') {
    return false;
  }
  if (dataset.origin !== 'postgis') return false;
  const ref = dataset.origin_ref;
  if (!ref || typeof ref !== 'object') return false;
  return ref.managed !== true;
}

/**
 * Which description this delete gets.
 *
 * The registered copy states what GEOLENS will do (not drop the table) rather
 * than what the world contains. `source_health` is a past observation: a table
 * dropped since the last probe still reads `healthy`, and one never probed
 * reads `unknown`; copy asserting the relation and its rows exist would be
 * wrong in both cases, and the backend's live `_relation_exists` probe would
 * find nothing and retire the name.
 *
 * That is a contract on the STRING, in all five locales, and no gate can check
 * it. When editing `descriptionRegistered`, describe what GeoLens does to the
 * table and never what the table holds.
 *
 * The `missing` variant remains for when the refresh has seen the table gone
 * (tasks_postgis_refresh maps SQLSTATE 42P01 to that verdict), where "we will
 * not drop it" is odd to say about a table that is not there. It is a courtesy,
 * and says "last saw" for the same reason the main copy avoids world-state
 * claims.
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
      // Clear a prior failure so reopening starts clean.
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
