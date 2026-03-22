import { Outlet, useMatch } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Navbar } from './Navbar';

const GEOLENS_GITHUB_URL = 'https://github.com/geolens-io/geolens';

export function AppLayout() {
  const { t } = useTranslation();
  const isMapBuilder = useMatch('/maps/:id');
  const isDatasetDetail = useMatch('/datasets/:id');

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex-1 animate-fade-in">
        <Outlet />
      </main>
      {!isMapBuilder && !isDatasetDetail && (
        <footer className="py-2 text-center text-xs text-muted-foreground">
          <a
            href={GEOLENS_GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-foreground transition-colors"
          >
            {t('footer.poweredBy')}
          </a>
        </footer>
      )}
    </div>
  );
}
