import { defaultNS, detectionOptions, fallbackLng, namespaces, supportedLngs } from './config';
import { resources } from './resources';

export function getBaseI18nOptions() {
  return {
    defaultNS,
    fallbackLng,
    fallbackNS: defaultNS,
    supportedLngs: [...supportedLngs],
    nonExplicitSupportedLngs: true,
    load: 'languageOnly' as const,
    ns: [...namespaces],
    resources,
    partialBundledLanguages: true,
    interpolation: {
      escapeValue: false,
    },
    returnNull: false,
    debug: false,
  };
}

export function getBrowserI18nOptions() {
  return {
    ...getBaseI18nOptions(),
    detection: {
      ...detectionOptions,
      order: [...detectionOptions.order],
      caches: [...detectionOptions.caches],
    },
  };
}

export function getTestI18nOptions() {
  return {
    ...getBaseI18nOptions(),
    lng: fallbackLng,
    initImmediate: false,
    showSupportNotice: false,
  };
}
