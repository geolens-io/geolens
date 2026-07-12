import { useState, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import type { DatasetResponse, DatasetUpdateRequest } from '@/types/api';

export type PendingDraftField =
  | 'summary'
  | 'lineage_summary'
  | 'source_url'
  | 'source_organization'
  | 'update_frequency'
  | 'usage_constraints'
  | 'access_constraints'
  | 'sensitivity_classification'
  | 'quality_statement';

type PendingDrafts = Partial<Record<PendingDraftField, string | null>>;

function normalizeDraftValue(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeDatasetValue(value: string | null | undefined): string | null {
  const normalized = value?.trim() ?? '';
  return normalized.length > 0 ? normalized : null;
}

interface UseDraftEditingOptions {
  datasetId: string | undefined;
  dataset: DatasetResponse | undefined;
  isGeometryEditDirty: boolean;
}

export function useDraftEditing({ datasetId, dataset, isGeometryEditDirty }: UseDraftEditingOptions) {
  const { t } = useTranslation('dataset');
  const updateDataset = useUpdateDataset();
  const [pendingDrafts, setPendingDrafts] = useState<PendingDrafts>({});
  const [dirtyFields, setDirtyFields] = useState<Set<PendingDraftField>>(() => new Set());
  const [isSaving, setIsSaving] = useState(false);
  // fix(#458 E-17): mirror pendingDrafts in a ref, updated synchronously with the
  // state. savePendingDrafts blurs the focused input to flush its edit through
  // stagePendingDraft — the blur event fires synchronously, so the ref carries
  // that just-staged field, whereas the callback's pendingDrafts closure does not
  // and used to drop it (then setPendingDrafts({}) discarded it for good).
  const pendingDraftsRef = useRef<PendingDrafts>({});

  const stagePendingDraft = useCallback(
    (field: PendingDraftField, value: string) => {
      const normalizedNext = normalizeDraftValue(value);
      const currentDatasetValue = normalizeDatasetValue(
        (dataset?.[field] as string | null | undefined) ?? null,
      );

      setPendingDrafts((prev) => {
        const next = { ...prev };
        if (normalizedNext === currentDatasetValue) {
          delete next[field];
        } else {
          next[field] = normalizedNext;
        }
        // Keep the ref in lockstep. Idempotent in prev, so StrictMode's
        // double-invoke of this updater lands on the same value.
        pendingDraftsRef.current = next;
        return next;
      });
    },
    [dataset],
  );

  const handleDraftDirtyChange = useCallback((field: PendingDraftField, isDirty: boolean) => {
    setDirtyFields((prev) => {
      const next = new Set(prev);
      if (isDirty) {
        next.add(field);
      } else {
        next.delete(field);
      }
      return next;
    });
  }, []);

  const resolveDraftValue = useCallback(
    (field: PendingDraftField) => {
      const staged = pendingDrafts[field];
      if (staged !== undefined) {
        return staged ?? '';
      }
      return (dataset?.[field] as string | null | undefined) ?? '';
    },
    [dataset, pendingDrafts],
  );

  const pendingFields = useMemo(() => {
    const fields = new Set<PendingDraftField>(Object.keys(pendingDrafts) as PendingDraftField[]);
    for (const field of dirtyFields) {
      fields.add(field);
    }
    return fields;
  }, [dirtyFields, pendingDrafts]);

  const pendingCount = pendingFields.size;

  const savePendingDrafts = useCallback(async (): Promise<boolean> => {
    if (!datasetId) return false;

    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }

    // Read from the ref, not the closure — it includes the field just staged by
    // the blur above (fix(#458 E-17)).
    const entries = Object.entries(pendingDraftsRef.current) as Array<
      [PendingDraftField, string | null]
    >;
    if (entries.length === 0) {
      return true;
    }

    const payload = entries.reduce<Record<PendingDraftField, string | null>>((acc, [field, value]) => {
      acc[field] = value;
      return acc;
    }, {} as Record<PendingDraftField, string | null>);

    setIsSaving(true);
    try {
      await updateDataset.mutateAsync({ datasetId, data: payload as DatasetUpdateRequest });
      setPendingDrafts({});
      pendingDraftsRef.current = {};
      setDirtyFields(new Set());
      toast.success(
        t('affordances.pending.saved', {
          defaultValue: 'Changes saved.',
        }),
      );
      if (isGeometryEditDirty) {
        toast.info(
          t('affordances.pending.geometryHint', {
            defaultValue: 'Field changes saved. Save geometry changes from the map toolbar.',
          }),
        );
      }
      return true;
    } catch {
      toast.error(
        t('affordances.pending.saveFailed', {
          defaultValue: 'Failed to save pending edits.',
        }),
      );
      return false;
    } finally {
      setIsSaving(false);
    }
    // pendingDrafts is intentionally not a dep — savePendingDrafts reads the ref,
    // which stays current without re-creating this callback on every keystroke.
  }, [datasetId, isGeometryEditDirty, t, updateDataset]);

  const discardPendingDrafts = useCallback(() => {
    setPendingDrafts({});
    pendingDraftsRef.current = {};
    setDirtyFields(new Set());
    toast.message(
      t('affordances.pending.canceled', {
        defaultValue: 'All changes discarded.',
      }),
    );
  }, [t]);

  return {
    stagePendingDraft,
    handleDraftDirtyChange,
    resolveDraftValue,
    pendingCount,
    isSaving,
    savePendingDrafts,
    discardPendingDrafts,
  };
}
