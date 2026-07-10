import type { OAuthProviderCreateData, OAuthProviderType } from '@/api/settings';

interface OAuthEndpointForm {
  provider_type: OAuthProviderType;
  discovery_url: string;
  authorize_url: string;
  token_url: string;
  userinfo_url: string;
}

export function buildOAuthEndpointFields(
  form: OAuthEndpointForm,
): Pick<
  OAuthProviderCreateData,
  'discovery_url' | 'authorize_url' | 'token_url' | 'userinfo_url'
> {
  if (form.provider_type === 'github') {
    return {
      discovery_url: null,
      authorize_url: form.authorize_url || null,
      token_url: form.token_url || null,
      userinfo_url: form.userinfo_url || null,
    };
  }
  if (form.discovery_url) {
    return {
      discovery_url: form.discovery_url,
      authorize_url: null,
      token_url: null,
      userinfo_url: null,
    };
  }
  return {
    discovery_url: null,
    authorize_url: form.authorize_url || null,
    token_url: form.token_url || null,
    userinfo_url: form.userinfo_url || null,
  };
}
