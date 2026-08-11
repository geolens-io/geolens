import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { formatMutationError } from '@/lib/error-map';
import {
  listContacts,
  createContact,
  deleteContact,
  listKeywords,
  createKeyword,
  deleteKeyword,
  listDistributions,
  updateDistribution,
} from '@/api/records';
import { fetchRelatedDatasets } from '@/api/datasets';
import type { ContactCreate, KeywordCreate } from '@/types/api';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';

export function useContacts(recordId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.records.contacts(recordId),
    queryFn: () => listContacts(recordId!),
    enabled: !!recordId,
    staleTime: 5 * 60_000,
  });
}

export function useCreateContact(recordId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ContactCreate) => createContact(recordId!, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.records.contacts(recordId) });
      qc.invalidateQueries({ queryKey: queryKeys.records.validation });
    },
    onError: () => { toast.error(i18n.t('dataset:contacts.addFailed')); },
  });
}

export function useDeleteContact(recordId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (contactId: string) => deleteContact(recordId!, contactId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.records.contacts(recordId) });
      qc.invalidateQueries({ queryKey: queryKeys.records.validation });
    },
    // fix(#438): UX-07 — ContactsEditor also toasted; the hook now owns it.
    onError: (err) => { toast.error(formatMutationError('dataset:contacts.removeFailed', err)); },
  });
}

export function useKeywords(recordId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.records.keywords(recordId),
    queryFn: () => listKeywords(recordId!),
    enabled: !!recordId,
    staleTime: 5 * 60_000,
  });
}

export function useCreateKeyword(recordId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: KeywordCreate) => createKeyword(recordId!, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.records.keywords(recordId) });
      qc.invalidateQueries({ queryKey: queryKeys.records.validation });
    },
    onError: () => { toast.error(i18n.t('dataset:keywords.addFailed')); },
  });
}

export function useDeleteKeyword(recordId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keywordId: string) => deleteKeyword(recordId!, keywordId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.records.keywords(recordId) });
      qc.invalidateQueries({ queryKey: queryKeys.records.validation });
    },
    // fix(#438): UX-07 — KeywordsEditor also toasted; the hook now owns it.
    onError: (err) => { toast.error(formatMutationError('dataset:keywords.removeFailed', err)); },
  });
}

export function useDistributions(recordId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.records.distributions(recordId),
    queryFn: () => listDistributions(recordId!),
    enabled: !!recordId,
    staleTime: 5 * 60_000,
  });
}

// feat(#1395): set-primary control. mutationFn's argument is the
// distributionId being promoted — the row that ends up carrying is_primary
// after the backend demotes every other row on the record in the same write.
//
// fix(#1395 codex round 4): onSuccess returns the invalidateQueries promise
// so the mutation stays pending until the refetch lands, not just until the
// PATCH resolves — DistributionsList's disabled-while-mutating guard reads
// isPending, and an onSuccess that fires-and-forgets the invalidation would
// let it flip back to enabled while the list still shows the pre-PATCH
// primary, opening a window for a second click to race the first.
export function useSetPrimaryDistribution(recordId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (distributionId: string) =>
      updateDistribution(recordId!, distributionId, { is_primary: true }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: queryKeys.records.distributions(recordId) });
      toast.success(i18n.t('dataset:distributions.primaryUpdated'));
    },
    onError: (err) => { toast.error(formatMutationError('dataset:distributions.setPrimaryFailed', err)); },
  });
}

export function useRelatedDatasets(datasetId: string) {
  return useQuery({
    queryKey: queryKeys.datasets.related(datasetId),
    queryFn: () => fetchRelatedDatasets(datasetId),
    enabled: !!datasetId,
    staleTime: 5 * 60_000,
    retry: false,
  });
}
