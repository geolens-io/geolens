import { useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2, Mail } from 'lucide-react';
import { resendVerification } from '@/api/auth';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';

interface VerificationPendingProps {
  /** The registrant's email address, used for the resend call. */
  email: string;
}

export function VerificationPending({ email }: VerificationPendingProps) {
  const { t } = useTranslation('auth');
  const [resending, setResending] = useState(false);
  const [resendSent, setResendSent] = useState(false);

  async function handleResend() {
    setResending(true);
    try {
      // The backend is enumeration-safe: always returns 200 — show generic
      // confirmation regardless of outcome (T-1231-11).
      await resendVerification(email);
    } catch {
      // Swallow errors to preserve enumeration-safety on the frontend.
    } finally {
      setResending(false);
      setResendSent(true);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="items-center justify-items-center text-center">
        <Mail className="text-primary mb-2 h-10 w-10" />
        <CardTitle className="text-xl">{t('verificationPending.title')}</CardTitle>
        <CardDescription>
          {t('verificationPending.description')}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-3">
        {resendSent ? (
          <p className="text-muted-foreground text-center text-sm">
            {t('verificationPending.resendSent')}
          </p>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={handleResend}
            disabled={resending}
          >
            {resending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t('verificationPending.resending')}
              </>
            ) : (
              t('verificationPending.resend')
            )}
          </Button>
        )}
        <Link
          to="/login"
          className="text-primary text-sm underline hover:text-primary/80"
        >
          {t('backToSignIn')}
        </Link>
      </CardContent>
    </Card>
  );
}
