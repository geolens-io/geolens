import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';

/**
 * Invalidate every cache that holds a list of login providers.
 *
 * The admin surfaces (OAuthProvidersSection in
 * `components/admin/settings/SettingsAuthTab.tsx`, `SamlProvidersSection`) hold
 * `settingsOAuth.providers`, while the login page's buttons read
 * `authConfig.oauthProviders` (`components/auth/OAuthButtons.tsx`). Invalidating
 * only the admin key would leave a stale button set after logout until a full
 * reload. Both surfaces write the same `catalog.oauth_providers` rows and the
 * login page lists every enabled row regardless of provider_type, so SAML edits
 * change that button set too; one invalidator keeps the pairing together.
 */
export function useInvalidateAuthProviders(): () => void {
  const queryClient = useQueryClient();
  return useCallback(() => {
    // Admin provider tables (Settings → Auth, Admin → SAML).
    queryClient.invalidateQueries({ queryKey: queryKeys.settingsOAuth.providers });
    // Login-page provider buttons.
    queryClient.invalidateQueries({ queryKey: queryKeys.authConfig.oauthProviders });
  }, [queryClient]);
}
