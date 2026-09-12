import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import type { DatasetResponse, DatasetUpdateRequest } from '@/types/api';
import { useAuthStore } from '@/stores/auth-store';

export type PendingDraftField =
  | 'summary'
  | 'lineage_summary'
  | 'source_url'
  | 'source_organization'
  | 'update_frequency'
  | 'usage_constraints'
  | 'access_constraints'
  | 'sensitivity_classification'
  | 'quality_statement'
  | 'attribution';

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
  const pendingDraftsRef = useRef<PendingDrafts>({});
  const dirtyFieldsRef = useRef(new Set<PendingDraftField>());
  const sessionEpoch = useAuthStore((state) => state.sessionEpoch);
  const userId = useAuthStore((state) => state.user?.id);
  const scope = useMemo(() => ({ datasetId, sessionEpoch, userId }), [datasetId, sessionEpoch, userId]);
  const scopeRef = useRef<typeof scope | null>(scope);
  scopeRef.current = scope;
  const saveRef = useRef<{ payload?: PendingDrafts } | null>(null);
  const isCurrent = useCallback(
    () => scopeRef.current === scope
      && useAuthStore.getState().sessionEpoch === scope.sessionEpoch
      && useAuthStore.getState().user?.id === scope.userId,
    [scope],
  );

  const resetDrafts = useCallback(() => {
    pendingDraftsRef.current = {};
    dirtyFieldsRef.current = new Set();
    setPendingDrafts({});
    setDirtyFields(new Set());
  }, []);

  useEffect(() => {
    scopeRef.current = scope;
    saveRef.current = null;
    resetDrafts();
    setIsSaving(false);
    return () => {
      if (scopeRef.current === scope) scopeRef.current = null;
    };
  }, [scope, resetDrafts]);

  const stagePendingDraft = useCallback(
    (field: PendingDraftField, value: string) => {
      if (!isCurrent()) return;
      const normalizedNext = normalizeDraftValue(value);
      const submitted = saveRef.current?.payload?.[field];
      const next = { ...pendingDraftsRef.current };
      // Keep the submitted value staged until success; failure must remain retryable.
      if (submitted === undefined && normalizedNext === normalizeDatasetValue(dataset?.[field])) {
        delete next[field];
      } else {
        next[field] = normalizedNext;
      }
      pendingDraftsRef.current = next;
      setPendingDrafts(next);
    },
    [dataset, isCurrent],
  );

  const handleDraftDirtyChange = useCallback(
    (field: PendingDraftField, isDirty: boolean) => {
      if (!isCurrent()) return;
      const next = new Set(dirtyFieldsRef.current);
      if (isDirty) next.add(field);
      else next.delete(field);
      dirtyFieldsRef.current = next;
      setDirtyFields(next);
    },
    [isCurrent],
  );

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
    if (!datasetId || !isCurrent() || saveRef.current) return false;

    const request = { payload: undefined as PendingDrafts | undefined };
    saveRef.current = request;
    setIsSaving(true);
    try {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
      if (!isCurrent()) return false;

      // Blur can stage another field before React renders the updated state.
      const payload = { ...pendingDraftsRef.current };
      const entries = Object.entries(payload) as Array<[PendingDraftField, string | null]>;
      if (entries.length === 0) return true;
      request.payload = payload;
      await updateDataset.mutateAsync({
        datasetId,
        data: payload as DatasetUpdateRequest,
      });
      if (!isCurrent()) return false;

      // Clear only submitted values that have not been edited again.
      const remaining = { ...pendingDraftsRef.current };
      for (const [field, value] of entries) {
        if (remaining[field] === value && !dirtyFieldsRef.current.has(field))
          delete remaining[field];
      }
      pendingDraftsRef.current = remaining;
      setPendingDrafts(remaining);
      toast.success(t('affordances.pending.saved'));
      if (isGeometryEditDirty) toast.info(t('affordances.pending.geometryHint'));
      return true;
    } catch {
      if (isCurrent()) toast.error(t('affordances.pending.saveFailed'));
      return false;
    } finally {
      if (saveRef.current === request) {
        saveRef.current = null;
        if (isCurrent()) setIsSaving(false);
      }
    }
  }, [datasetId, isCurrent, isGeometryEditDirty, t, updateDataset]);

  const discardPendingDrafts = useCallback(() => {
    if (!isCurrent()) return;
    resetDrafts();
    toast.message(t('affordances.pending.canceled'));
  }, [isCurrent, resetDrafts, t]);

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
