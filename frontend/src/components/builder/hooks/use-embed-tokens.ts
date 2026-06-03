import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { createEmbedToken, listEmbedTokens, updateEmbedTokenOrigins, revokeEmbedToken } from '@/api/embed-tokens';

export function useCreateEmbedToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      mapId,
      expiresInDays,
      allowedOrigins,
    }: {
      mapId: string;
      expiresInDays?: number;
      allowedOrigins?: string[];
    }) => createEmbedToken(mapId, expiresInDays, allowedOrigins),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.embedTokens(variables.mapId) });
    },
  });
}

export function useMapEmbedTokens(mapId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maps.embedTokens(mapId),
    queryFn: () => listEmbedTokens(mapId!),
    enabled: !!mapId,
  });
}

export function useUpdateEmbedToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      mapId,
      tokenId,
      allowedOrigins,
    }: {
      mapId: string;
      tokenId: string;
      allowedOrigins: string[] | null;
    }) => updateEmbedTokenOrigins(mapId, tokenId, allowedOrigins),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.embedTokens(variables.mapId) });
    },
  });
}

export function useRevokeEmbedToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, tokenId }: { mapId: string; tokenId: string }) =>
      revokeEmbedToken(mapId, tokenId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.embedTokens(variables.mapId) });
      qc.invalidateQueries({ queryKey: queryKeys.admin.allEmbedTokens });
    },
  });
}
