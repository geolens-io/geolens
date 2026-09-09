import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import { detectionOptions, defaultNS, fallbackLng, namespaces, supportedLngs } from './config';
import { getBrowserI18nOptions } from './options';
import { loadLocaleResources, resources } from './resources';

// fix(#438): I18N-09 — RTL infrastructure is live (the <html dir> below flips
// for these languages), but no RTL locale is shipped yet, so it is untested in
// practice and no logical-property (start/end vs left/right) audit has run.
// Adding an RTL locale must be paired with that audit.
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

// fix(#2029 review): `zh` here is Simplified Chinese only. A bare
// `split('-')[0]` would also route Traditional or region-only tags
// (zh-TW, zh-Hant, zh-MY) to it, so ask Intl.Locale for the tag's actual
// script rather than guessing from a region allowlist — CLDR maximizes
// zh-MY to zh-Hans-MY but zh-TW to zh-Hant-TW.
function isSimplifiedChineseTag(tag: string): boolean {
  try {
    return new Intl.Locale(tag).maximize().script === 'Hans';
  } catch {
    return false;
  }
}

function matchSupportedLanguage(value: string): (typeof supportedLngs)[number] | undefined {
  const lowerTag = value.toLowerCase();
  if (lowerTag === 'zh' || lowerTag.startsWith('zh-')) {
    return isSimplifiedChineseTag(value) ? 'zh' : undefined;
  }
  const baseLanguage = lowerTag.split('-')[0];
  return supportedLngs.find((lng) => lng === baseLanguage);
}

function normalizeLanguage(value?: string | null) {
  if (!value) return fallbackLng;
  return matchSupportedLanguage(value) ?? fallbackLng;
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
    window.navigator.languages?.find((candidate) => matchSupportedLanguage(candidate) !== undefined) ??
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

export { defaultNS, fallbackLng, namespaces, normalizeLanguage, resources, supportedLngs };
export type { Namespace, SupportedLng } from './config';
export default i18n;
