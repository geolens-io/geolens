import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
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

  // ROUTE-03: emit a one-time info toast before redirecting so the user
  // understands why they were bounced instead of silently landing on "/".
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

  // Render nothing while the effect redirects (prevents flash of register form).
  if (token) return null;

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (configError) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
        <div className="text-center">
          <GeoLensLogo size="lg" className="justify-center" />
          <p className="text-muted-foreground mt-1 text-sm">
            {t('geospatialDataCatalog')}
          </p>
        </div>
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle className="text-xl text-destructive">{t('common:error', { defaultValue: 'Error' })}</CardTitle>
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
      </div>
    );
  }

  if (!config || config.registration_enabled === false) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
        <div className="text-center">
          <GeoLensLogo size="lg" className="justify-center" />
          <p className="text-muted-foreground mt-1 text-sm">
            {t('geospatialDataCatalog')}
          </p>
        </div>
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle className="text-xl">{t('registrationDisabled')}</CardTitle>
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
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
      <div className="text-center">
        {/* sr-only level-1 heading: the visual brand mark is the GeoLensLogo, but
            screen-reader heading navigation still needs an <h1> on the page. */}
        <h1 className="sr-only">{t('createAccount')}</h1>
        <GeoLensLogo size="lg" className="justify-center" />
        <p className="text-muted-foreground mt-1 text-sm">
          {t('geospatialDataCatalog')}
        </p>
      </div>
      {submitted ? (
        // Use the server's authoritative outcome (RegisterResponse.next_step)
        // rather than inferring from a cached /auth/config snapshot — race-free
        // and matches exactly what the backend did (M1 follow-up — Phase 1234).
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
    </div>
  );
}
