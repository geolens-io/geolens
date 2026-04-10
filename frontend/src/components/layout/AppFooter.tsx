import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import {
  GEOLENS_GITHUB_URL,
  GEOLENS_DISCUSSIONS_URL,
  GEOLENS_LICENSE_URL,
  GEOLENS_DOCS_URL,
  GEOLENS_API_DOCS_URL,
} from '@/lib/external-links';

interface AppFooterProps {
  showBranding?: boolean;
  className?: string;
  navClassName?: string;
  linkClassName?: string;
}

export function AppFooter({
  showBranding = true,
  className,
  navClassName,
  linkClassName,
}: AppFooterProps) {
  const { t } = useTranslation();

  const footerLinks = [
    { href: GEOLENS_GITHUB_URL, label: t('footer.github') },
    { href: GEOLENS_DOCS_URL, label: t('footer.docs') },
    { href: GEOLENS_DISCUSSIONS_URL, label: t('footer.community') },
    { href: GEOLENS_API_DOCS_URL, label: t('footer.api') },
    { href: GEOLENS_LICENSE_URL, label: t('footer.license') },
  ];

  return (
    <footer className={cn('py-3 text-center text-xs text-muted-foreground', className)}>
      <nav
        aria-label={showBranding ? t('footer.poweredBy') : t('appName')}
        className={cn('flex items-center justify-center flex-wrap gap-x-1.5', navClassName)}
      >
        {showBranding && <span>{t('footer.poweredBy')}</span>}
        {footerLinks.map((link, index) => (
          <Fragment key={link.label}>
            {(showBranding || index > 0) && <span aria-hidden="true">·</span>}
            <a
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className={cn('hover:text-foreground transition-colors', linkClassName)}
            >
              {link.label}
            </a>
          </Fragment>
        ))}
      </nav>
    </footer>
  );
}
