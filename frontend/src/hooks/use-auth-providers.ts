import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';

/**
 * Invalidate every cache that holds a list of login providers.
 *
 * The admin surfaces that CRUD providers (OAuthProvidersSection in
 * `components/admin/settings/SettingsAuthTab.tsx`, `SamlProvidersSection`) hold
 * `settingsOAuth.providers` — their own admin table. The login page's buttons
 * read a different key, `authConfig.oauthProviders`
 * (`components/auth/OAuthButtons.tsx`), so invalidating only the admin key
 * would leave an admin who added or removed a provider and then logged out
 * seeing the old button set until a full reload.
 *
 * The two key families always move together: both admin surfaces write the same
 * `catalog.oauth_providers` rows through `/settings/oauth-providers/`, and the login
 * page's `/auth/oauth/providers/` returns every enabled row with no provider_type
 * filter — so SAML edits change that button set too. One invalidator called from both
 * surfaces keeps the pairing from drifting apart.
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
