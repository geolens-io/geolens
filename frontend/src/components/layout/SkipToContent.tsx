import { useTranslation } from 'react-i18next';

/**
 * Accessible skip link — visible only on focus, lets keyboard users
 * jump past the navbar directly to the main content area.
 */
export function SkipToContent() {
  const { t } = useTranslation('common');
  return (
    <a
      href="#map-viewport"
      className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-2 focus:left-2 focus:px-4 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-md focus:text-sm focus:font-medium focus:shadow-lg"
    >
      {t('viewer.skipToMap')}
    </a>
  );
}
