import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '@/components/layout/LoadingState';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { RegisterForm } from '@/components/auth/RegisterForm';
import { GeoLensLogo } from '@/components/GeoLensLogo';
import { PendingApproval } from '@/components/auth/PendingApproval';
import { VerificationPending } from '@/components/auth/VerificationPending';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useDocumentTitle } from '@/hooks/use-document-title';

export function RegisterPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle(t('common:pageTitle.register'));
  const [submitted, setSubmitted] = useState(false);
  const [registrantEmail, setRegistrantEmail] = useState('');
  const [nextStep, setNextStep] = useState<
    'verify_email' | 'await_approval' | undefined
  >(undefined);
  const token = useAuthStore((s) => s.token);
  const navigate = useNavigate();

  // A one-time toast explains the redirect instead of silently landing on "/".
  useEffect(() => {
    if (!token) return;
    toast.info(t('alreadySignedIn'));
    navigate('/', { replace: true });
  }, [token, navigate, t]);

  const { data: config, isLoading, isError: configError } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  // Renders nothing while the effect redirects, avoiding a flash of the form.
  if (token) return null;

  if (isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        {/* LoadingState carries role="status" + aria-live. */}
        <LoadingState />
      </main>
    );
  }

  if (configError) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
        <div className="text-center">
          {/* sr-only <h1>: every render branch needs one for heading nav. */}
          <h1 className="sr-only">{t('createAccount')}</h1>
          <GeoLensLogo size="lg" className="justify-center" />
          <p className="text-muted-foreground mt-1 text-sm">
            {t('geospatialDataCatalog')}
          </p>
        </div>
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle level={2} className="text-xl text-destructive">{t('common:error', { defaultValue: 'Error' })}</CardTitle>
            <CardDescription>
              {t('configLoadError', { defaultValue: 'Unable to load registration settings. Please try again.' })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              to="/login"
              className="text-primary underline hover:text-primary/80 text-sm"
            >
              {t('backToSignIn')}
            </Link>
          </CardContent>
        </Card>
      </main>
    );
  }

  // allow_signup is false when password login is off even though registration
  // is on; older servers omit it.
  const signupOpen = config?.allow_signup ?? config?.registration_enabled === true;
  if (!config || !signupOpen) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
        <div className="text-center">
          {/* sr-only <h1>: every render branch needs one for heading nav. */}
          <h1 className="sr-only">{t('createAccount')}</h1>
          <GeoLensLogo size="lg" className="justify-center" />
          <p className="text-muted-foreground mt-1 text-sm">
            {t('geospatialDataCatalog')}
          </p>
        </div>
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle level={2} className="text-xl">{t('registrationDisabled')}</CardTitle>
            <CardDescription>
              {t('registrationDisabledDescription')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              to="/login"
              className="text-primary underline hover:text-primary/80 text-sm"
            >
              {t('backToSignIn')}
            </Link>
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
      <div className="text-center">
        {/* sr-only <h1>: the visual brand mark is a logo, but screen-reader
            heading navigation needs a heading. */}
        <h1 className="sr-only">{t('createAccount')}</h1>
        <GeoLensLogo size="lg" className="justify-center" />
        <p className="text-muted-foreground mt-1 text-sm">
          {t('geospatialDataCatalog')}
        </p>
      </div>
      {submitted ? (
        // The server's outcome (RegisterResponse.next_step), not a cached
        // /auth/config snapshot, which can race.
        nextStep === 'verify_email' ? (
          <VerificationPending email={registrantEmail} />
        ) : (
          <PendingApproval />
        )
      ) : (
        <RegisterForm
          onSuccess={(email, step) => {
            setRegistrantEmail(email);
            setNextStep(step);
            setSubmitted(true);
          }}
        />
      )}
    </main>
  );
}
