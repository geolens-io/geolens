import { useState, type FormEvent } from 'react';
import { ArrowRight, Globe, LogIn, Shield } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useLocation, useNavigate } from 'react-router';
import { GitHubIcon } from '@/components/icons/GitHubIcon';
import { PageShell } from '@/components/layout/PageShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useAuthStore } from '@/stores/auth-store';
import {
  GEOLENS_DOCS_URL,
  GEOLENS_GITHUB_URL,
  GEOLENS_LICENSE_URL,
} from '@/lib/external-links';

const trustSignals = [
  { icon: Shield, labelKey: 'trust.license', href: GEOLENS_LICENSE_URL },
  { icon: Globe, labelKey: 'trust.ogc', href: 'https://ogcapi.ogc.org/' },
  { icon: GitHubIcon, labelKey: 'trust.github', href: GEOLENS_GITHUB_URL },
] as const;

function TrustSignalStrip() {
  const { t } = useTranslation('search');

  return (
    <div className="flex flex-wrap items-center gap-2">
      {trustSignals.map((signal) => (
        <a
          key={signal.labelKey}
          href={signal.href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-10 items-center gap-2 rounded-full border border-border/50 bg-background/80 px-3.5 py-2 text-xs font-medium text-muted-foreground shadow-sm transition-colors hover:text-foreground"
        >
          <signal.icon className="size-3.5 shrink-0" aria-hidden="true" />
          {t(signal.labelKey)}
        </a>
      ))}
    </div>
  );
}

export function LandingPage() {
  const { t } = useTranslation('search');
  const { t: tAuth } = useTranslation('auth');
  const { t: tCommon } = useTranslation('common');
  useDocumentTitle(tCommon('appName'));
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const redirectTarget = token ? '/search' : location.search ? `/search${location.search}` : null;
  if (redirectTarget) return <Navigate to={redirectTarget} replace />;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextQuery = query.trim();
    navigate({
      pathname: '/search',
      search: nextQuery ? `?${new URLSearchParams({ q: nextQuery }).toString()}` : '',
    });
  };

  return (
    <PageShell maxWidth="wide" className="space-y-6 pb-10 pt-8 sm:pt-10">
      <section className="relative overflow-hidden rounded-[32px] border border-border/60 bg-[linear-gradient(140deg,_hsl(var(--background))_12%,_hsl(var(--muted)/0.26)_100%)] px-5 py-7 shadow-sm sm:px-7 sm:py-9 lg:px-10 lg:py-10">
        <div className="absolute right-0 top-0 h-48 w-48 rounded-full bg-primary/8 blur-3xl" aria-hidden="true" />
        <div className="absolute bottom-0 left-10 h-36 w-36 rounded-full bg-emerald-500/10 blur-3xl" aria-hidden="true" />

        <div className="relative grid gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:items-start">
          <div className="space-y-6">
            <p className="inline-flex rounded-full border border-border/60 bg-background/85 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              {t('landing.eyebrow')}
            </p>

            <div className="space-y-4">
              <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl lg:text-[3.2rem] lg:leading-[1.05]">
                {t('title')}
              </h1>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
                {t('subtitle')}
              </p>
              <p className="max-w-2xl text-sm text-muted-foreground">
                {t('landing.searchHelper')}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row">
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label={t('placeholder')}
                placeholder={t('placeholder')}
                className="h-12 rounded-2xl border-border/60 bg-background/92 text-base shadow-sm"
              />
              <Button type="submit" className="h-12 rounded-2xl px-5">
                {t('landing.primaryCta')}
                <ArrowRight className="size-4" />
              </Button>
              <Button asChild variant="outline" className="h-12 rounded-2xl px-5">
                <a href={GEOLENS_DOCS_URL} target="_blank" rel="noopener noreferrer">
                  {tCommon('footer.docs')}
                </a>
              </Button>
            </form>

            <TrustSignalStrip />
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
            <article className="rounded-[24px] border border-border/60 bg-background/88 p-5 shadow-sm backdrop-blur-sm">
              <p className="text-sm font-semibold">
                {t('landing.openSourceTitle')}
              </p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {t('landing.openSourceBody')}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild size="sm" variant="secondary">
                  <a href={GEOLENS_DOCS_URL} target="_blank" rel="noopener noreferrer">
                    {tCommon('footer.docs')}
                  </a>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <a href={GEOLENS_GITHUB_URL} target="_blank" rel="noopener noreferrer">
                    {tCommon('footer.github')}
                  </a>
                </Button>
              </div>
            </article>

            <article className="rounded-[24px] border border-border/60 bg-background/88 p-5 shadow-sm backdrop-blur-sm">
              <p className="text-sm font-semibold">
                {t('landing.workspaceTitle')}
              </p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {t('landing.workspaceBody')}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild size="sm">
                  <Link to="/login">
                    <LogIn className="size-4" />
                    {tAuth('signIn')}
                  </Link>
                </Button>
                <Button asChild size="sm" variant="ghost">
                  <Link to="/search">{t('landing.primaryCta')}</Link>
                </Button>
              </div>
            </article>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
