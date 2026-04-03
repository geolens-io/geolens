import { Fragment } from 'react';
import { Outlet, useMatch } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Navbar } from './Navbar';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';
import { SkipToContent } from './SkipToContent';
import {
  GEOLENS_GITHUB_URL,
  GEOLENS_DISCUSSIONS_URL,
  GEOLENS_LICENSE_URL,
  GEOLENS_DOCS_URL,
  GEOLENS_API_DOCS_URL,
} from '@/lib/external-links';

export function AppLayout() {
  const { t } = useTranslation();
  const isMapBuilder = useMatch('/maps/:id');
  const isDatasetDetail = useMatch('/datasets/:id');
  const { isEnterprise } = useEdition();
  const { data: branding } = useBranding();
  const showFooterBadge = !isEnterprise || branding?.show_badge !== false;

  const footerLinks = [
    { href: GEOLENS_GITHUB_URL, label: t('footer.poweredBy') },
    { href: GEOLENS_DOCS_URL, label: t('footer.docs') },
    { href: GEOLENS_GITHUB_URL, label: t('footer.github') },
    { href: GEOLENS_DISCUSSIONS_URL, label: t('footer.community') },
    { href: GEOLENS_API_DOCS_URL, label: t('footer.api') },
    { href: GEOLENS_LICENSE_URL, label: t('footer.license') },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <SkipToContent />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="flex-1 animate-fade-in focus:outline-none">
        <Outlet />
      </main>
      {!isMapBuilder && !isDatasetDetail && showFooterBadge && (
        <footer className="py-3 text-center text-xs text-muted-foreground">
          <nav aria-label={t('footer.poweredBy')} className="flex items-center justify-center flex-wrap gap-x-1.5">
            {footerLinks.map((link, i) => (
              <Fragment key={link.label}>
                {i > 0 && <span aria-hidden="true">·</span>}
                <a
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-foreground transition-colors"
                >
                  {link.label}
                </a>
              </Fragment>
            ))}
          </nav>
        </footer>
      )}
    </div>
  );
}
