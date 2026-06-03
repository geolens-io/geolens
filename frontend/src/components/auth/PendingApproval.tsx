import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Clock } from 'lucide-react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

export function PendingApproval() {
  const { t } = useTranslation('auth');

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="items-center justify-items-center text-center">
        <Clock className="text-muted-foreground mb-2 h-10 w-10" />
        <CardTitle className="text-xl">{t('pendingApproval')}</CardTitle>
        <CardDescription>
          {t('pendingApprovalDescription')}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-center">
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
