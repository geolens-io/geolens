import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';
import { useDeleteDataset } from '@/hooks/use-dataset';
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
    }
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
            {t('deleteDialog.description', { name: dataset.title })}
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-2">
          <p className="text-sm font-medium">{t('deleteDialog.confirmPrompt')}</p>
          <Input
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={dataset.title}
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
