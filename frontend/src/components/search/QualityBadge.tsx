import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { qualityScoreClasses } from '@/lib/status-colors';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

export function QualityBadge({ score }: { score: number | null | undefined }) {
  const { t } = useTranslation('search');
  if (score == null) return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge className={cn('cursor-help', qualityScoreClasses(score))}>
          {t('quality.label', { score })}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>
        <p className="text-xs">{t('qualityBadge.tooltip')}</p>
      </TooltipContent>
    </Tooltip>
  );
}
