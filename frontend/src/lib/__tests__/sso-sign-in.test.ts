import { nonceMatches, ssoSignInUrl, takeSsoNonce } from '@/lib/sso-sign-in';

describe('sso sign-in nonce', () => {
  beforeEach(() => sessionStorage.clear());

  it('keeps the nonce it sends and hands it back once', () => {
    const nonce = new URL(ssoSignInUrl('oauth', 'corp'), 'http://localhost').searchParams.get('nonce');
    expect(nonce).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(takeSsoNonce()).toBe(nonce);
    expect(takeSsoNonce()).toBeNull();
  });

  it.each([
    ['abc', 'abc', true],
    ['abc', 'abd', false],
    ['abc', 'ab', false],
    ['abc', 'abcd', false],
    ['', '', true],
  ])('compares %j with %j', (expected, received, matches) => {
    expect(nonceMatches(expected, received)).toBe(matches);
  });
});
