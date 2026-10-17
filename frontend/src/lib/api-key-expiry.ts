export type ApiKeyExpiryPreset = 'never' | '30d' | '90d' | '1y';

export const API_KEY_EXPIRY_PRESETS: readonly ApiKeyExpiryPreset[] = ['never', '30d', '90d', '1y'];

/** ISO timestamp for a preset counted from `now`, or null for a key that never expires. */
export function expiryPresetToIso(preset: ApiKeyExpiryPreset, now: Date = new Date()): string | null {
  if (preset === 'never') return null;
  const at = new Date(now);
  if (preset === '1y') at.setUTCFullYear(at.getUTCFullYear() + 1);
  else at.setTime(at.getTime() + (preset === '30d' ? 30 : 90) * 86_400_000);
  return at.toISOString();
}

/** An expired key still reports is_active but no longer authenticates. */
export function isApiKeyExpired(expiresAt: string | null | undefined, now: Date = new Date()): boolean {
  return !!expiresAt && new Date(expiresAt).getTime() <= now.getTime();
}

export type ApiKeyStatus = 'active' | 'expired' | 'revoked';

/** Revoked wins over expired: a revoked key stays revoked whatever its expiry says. */
export function apiKeyStatus(
  key: { is_active: boolean; expires_at?: string | null },
  now: Date,
): ApiKeyStatus {
  if (!key.is_active) return 'revoked';
  return isApiKeyExpired(key.expires_at, now) ? 'expired' : 'active';
}
