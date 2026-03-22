import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { createEmbedToken, listEmbedTokens, updateEmbedTokenOrigins } from '@/api/embed-tokens';

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
      qc.invalidateQueries({ queryKey: ['map-embed-tokens', variables.mapId] });
    },
  });
}

export function useMapEmbedTokens(mapId: string | undefined) {
  return useQuery({
    queryKey: ['map-embed-tokens', mapId],
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
      qc.invalidateQueries({ queryKey: ['map-embed-tokens', variables.mapId] });
    },
  });
}
