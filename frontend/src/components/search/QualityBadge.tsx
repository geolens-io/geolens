import { useTranslation } from 'react-i18next';
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
        <span
          className={`text-xs px-2 py-0.5 border rounded-full font-medium transition-colors duration-150 cursor-help ${qualityScoreClasses(score)}`}
        >
          {t('quality.label', { score })}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="text-xs">Metadata completeness score based on title, description, keywords, CRS, and temporal extent</p>
      </TooltipContent>
    </Tooltip>
  );
}
