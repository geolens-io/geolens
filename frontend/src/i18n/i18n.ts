import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import { detectionOptions, defaultNS, fallbackLng, namespaces, supportedLngs } from './config';
import { getBrowserI18nOptions } from './options';
import { loadLocaleResources, resources } from './resources';

const rtlLanguages = new Set(['ar', 'he', 'fa', 'ur']);

function updateDocumentLanguage(lng?: string) {
  if (typeof document === 'undefined') {
    return;
  }

  const resolvedLng = lng ?? fallbackLng;
  document.documentElement.lang = resolvedLng;
  // Set dir attribute for RTL support
  document.documentElement.dir = rtlLanguages.has(resolvedLng) ? 'rtl' : 'ltr';
}

function normalizeLanguage(value?: string | null) {
  const baseLanguage = value?.toLowerCase().split('-')[0];
  return supportedLngs.find((lng) => lng === baseLanguage) ?? fallbackLng;
}

function detectInitialLanguage() {
  if (typeof window === 'undefined') {
    return fallbackLng;
  }

  try {
    const storedLanguage = window.localStorage.getItem(detectionOptions.lookupLocalStorage);
    if (storedLanguage) {
      return normalizeLanguage(storedLanguage);
    }
  } catch {
    // Ignore storage access issues and fall back to browser settings.
  }

  const browserLanguage =
    window.navigator.languages?.find((candidate) => {
      const baseLanguage = candidate.toLowerCase().split('-')[0];
      return supportedLngs.includes(baseLanguage as (typeof supportedLngs)[number]);
    }) ??
    window.navigator.language;

  return normalizeLanguage(browserLanguage);
}

async function buildInitialResources() {
  const initialLanguage = detectInitialLanguage();

  if (initialLanguage === fallbackLng) {
    return {
      initialLanguage,
      initialResources: resources,
    };
  }

  return {
    initialLanguage,
    initialResources: {
      ...resources,
      [initialLanguage]: await loadLocaleResources(initialLanguage),
    },
  };
}

let initializationPromise: Promise<typeof i18n> | null = null;

export async function initializeI18n() {
  if (i18n.isInitialized) {
    return i18n;
  }

  if (!initializationPromise) {
    initializationPromise = (async () => {
      const { initialLanguage, initialResources } = await buildInitialResources();

      await i18n
        .use(initReactI18next)
        .init({
          ...getBrowserI18nOptions(),
          lng: initialLanguage,
          resources: initialResources,
        });

      i18n.off('languageChanged', updateDocumentLanguage);
      i18n.on('languageChanged', updateDocumentLanguage);
      updateDocumentLanguage(i18n.resolvedLanguage ?? i18n.language);

      return i18n;
    })();
  }

  return initializationPromise;
}

export async function changeAppLanguage(lng: string) {
  const nextLanguage = normalizeLanguage(lng);
  await initializeI18n();

  if (!i18n.hasLoadedNamespace(defaultNS, { lng: nextLanguage })) {
    const localeResources = await loadLocaleResources(nextLanguage);
    for (const ns of namespaces) {
      i18n.addResourceBundle(nextLanguage, ns, localeResources[ns], true, true);
    }
  }

  await i18n.changeLanguage(nextLanguage);

  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(detectionOptions.lookupLocalStorage, nextLanguage);
    } catch {
      // Ignore storage access issues; language will still change for this session.
    }
  }
}

export { defaultNS, fallbackLng, namespaces, resources, supportedLngs };
export type { Namespace, SupportedLng } from './config';
export default i18n;
