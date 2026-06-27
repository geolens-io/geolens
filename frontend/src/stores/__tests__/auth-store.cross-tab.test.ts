import { describe, expect, it, vi, afterEach } from 'vitest';
import { useAuthStore } from '../auth-store';

// Guards the cross-tab sync listener: a `storage` event for the auth key (fired
// by another tab rotating the single-use refresh token) must rehydrate this
// tab's store; events for any other key must be ignored. Without this, a tab
// holding a now-revoked refresh token 401s and logs out on the next request.
describe('auth-store cross-tab sync', () => {
  afterEach(() => vi.restoreAllMocks());

  it('rehydrates when the geolens-auth key changes in another tab', () => {
    const spy = vi.spyOn(useAuthStore.persist, 'rehydrate').mockResolvedValue();
    window.dispatchEvent(new StorageEvent('storage', { key: 'geolens-auth' }));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('ignores storage events for unrelated keys', () => {
    const spy = vi.spyOn(useAuthStore.persist, 'rehydrate').mockResolvedValue();
    window.dispatchEvent(new StorageEvent('storage', { key: 'some-other-key' }));
    expect(spy).not.toHaveBeenCalled();
  });
});
