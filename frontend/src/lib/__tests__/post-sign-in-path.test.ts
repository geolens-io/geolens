import { postSignInPath } from '@/lib/post-sign-in-path';

describe('postSignInPath', () => {
  it.each([
    ['/maps/1?tab=layers', '/maps/1?tab=layers'],
    ['/', '/'],
    ['//evil.example/x', '/'],
    ['/\\evil.example/x', '/'],
    ['https://evil.example/x', '/'],
    ['maps/1', '/'],
    ['', '/'],
    [null, '/'],
    [undefined, '/'],
  ])('maps %j to %j', (value, expected) => {
    expect(postSignInPath(value)).toBe(expected);
  });
});
