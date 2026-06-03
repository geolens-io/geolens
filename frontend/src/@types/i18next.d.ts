import 'i18next';
import type { defaultNS } from '../i18n/config';
import type { resources } from '../i18n/resources';

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: typeof defaultNS;
    resources: typeof resources.en;
  }
}
