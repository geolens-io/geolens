import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listContacts,
  createContact,
  deleteContact,
  listKeywords,
  createKeyword,
  deleteKeyword,
  listDistributions,
} from '@/api/records';
import { fetchRelatedDatasets } from '@/api/datasets';
import type { ContactCreate, KeywordCreate } from '@/types/api';

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

export function useRelatedDatasets(datasetId: string) {
  return useQuery({
    queryKey: queryKeys.datasets.related(datasetId),
    queryFn: () => fetchRelatedDatasets(datasetId),
    enabled: !!datasetId,
    staleTime: 5 * 60_000,
    retry: false,
  });
}
