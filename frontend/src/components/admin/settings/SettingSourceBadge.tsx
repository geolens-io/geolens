import { useTranslation } from 'react-i18next';
import { Lock, RotateCcw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface SettingSourceBadgeProps {
  source: 'default' | 'overridden' | 'env_only';
  settingKey?: string;
  onReset?: (key: string) => void;
}

export function SettingSourceBadge({ source, settingKey, onReset }: SettingSourceBadgeProps) {
  const { t } = useTranslation('admin');

  if (source === 'overridden' && settingKey && onReset) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-5 px-1.5 text-[10px] text-muted-foreground hover:text-foreground gap-1"
              onClick={() => onReset(settingKey)}
            >
              <RotateCcw className="h-3 w-3" />
              {t('settings.sourceBadge.reset')}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">
            {t('settings.sourceBadge.resetToDefault')}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  if (source === 'env_only') {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 cursor-help gap-1">
              <Lock className="h-3 w-3" />
              {t('settings.sourceBadge.envVar')}
            </Badge>
          </TooltipTrigger>
          <TooltipContent side="top">
            {t('settings.sourceBadge.envVarTooltip')}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // default — no badge shown
  return null;
}
