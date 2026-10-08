/**
 * The in-app path to land on after signing in, or `/` for anything else.
 * `//host` and `/\host` start with a slash yet name another origin.
 */
export function postSignInPath(value: string | null | undefined): string {
  if (!value?.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return '/';
  return value;
}
