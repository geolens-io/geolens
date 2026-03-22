export const defaultNS = 'common';
export const fallbackLng = 'en';

export const supportedLngs = ['en', 'es', 'fr', 'de'] as const;
export type SupportedLng = (typeof supportedLngs)[number];

export const namespaces = [
  'common',
  'auth',
  'search',
  'dataset',
  'import',
  'collections',
  'admin',
  'builder',
] as const;
export type Namespace = (typeof namespaces)[number];

export const languageNames: Record<SupportedLng, string> = {
  en: 'English',
  es: 'Español',
  fr: 'Français',
  de: 'Deutsch',
};

export const languageOptions = supportedLngs.map((value) => ({
  value,
  label: languageNames[value],
}));

export const detectionOptions = {
  order: ['localStorage', 'navigator'],
  caches: ['localStorage'],
  lookupLocalStorage: 'i18nextLng',
} as const;
