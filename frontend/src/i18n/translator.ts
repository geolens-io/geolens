/** Structural translator accepted by helpers; i18next's own `TFunction` is assignable to it. */
export interface Translator {
  (key: string): string;
  (key: string, options: Record<string, unknown>): string;
}
