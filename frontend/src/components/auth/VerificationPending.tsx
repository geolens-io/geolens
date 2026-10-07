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
  const [resendFailed, setResendFailed] = useState(false);

  async function handleResend() {
    setResending(true);
    setResendFailed(false);
    try {
      // The backend answers every accepted request with the same 200, whether
      // or not the email is registered, so only that 200 earns the generic
      // confirmation. A failure says nothing about the account and keeps the
      // button for another try.
      await resendVerification(email);
      setResendSent(true);
    } catch {
      setResendFailed(true);
    } finally {
      setResending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="items-center justify-items-center text-center">
        <Mail className="text-primary mb-2 h-10 w-10" />
        <CardTitle level={2} className="text-xl">{t('verificationPending.title')}</CardTitle>
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
          <>
            {resendFailed && (
              <p role="alert" className="text-destructive text-center text-sm">
                {t('verificationPending.resendFailed')}
              </p>
            )}
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
          </>
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
