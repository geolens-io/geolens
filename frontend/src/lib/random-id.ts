/* eslint-disable no-restricted-properties -- this module is the guarded wrapper the rule points to */
/**
 * A random RFC 4122 version 4 UUID.
 *
 * Browsers expose `crypto.randomUUID` only in secure contexts (HTTPS or
 * localhost), so on a deployment served over plain HTTP calling it throws.
 * `crypto.getRandomValues` is available in every context and draws from the
 * same CSPRNG, so the fallback is just as collision-resistant.
 */
export function randomId(): string {
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
