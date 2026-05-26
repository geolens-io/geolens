import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { GitHubIcon } from '@/components/icons/GitHubIcon';
import { GEOLENS_BUG_REPORT_URL } from '@/lib/external-links';

export function ErrorReportButton({
  size = 'sm',
  variant = 'outline',
}: {
  size?: 'sm' | 'xs';
  variant?: 'outline' | 'secondary';
}) {
  const { t } = useTranslation('common');

  return (
    <Button asChild variant={variant} size={size}>
      <a
        href={GEOLENS_BUG_REPORT_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <GitHubIcon className="size-4" />
        {t('errorBoundary.reportBug')}
      </a>
    </Button>
  );
}
