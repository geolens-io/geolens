import { useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Trash2, Map as MapIcon, Globe, Lock, Users, User, Layers, Calendar } from 'lucide-react';
import { API_BASE } from '@/lib/constants';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { formatDate } from '@/lib/format';
import { getVisibilityLabel } from '@/i18n/labels';
import type { MapCardProps } from './MapCard';

function VisibilityIcon({ visibility }: { visibility: string }) {
  if (visibility === 'public') return <Globe className="h-3.5 w-3.5 text-success" />;
  if (visibility === 'internal') return <Users className="h-3.5 w-3.5 text-amber-500" />;
  return <Lock className="h-3.5 w-3.5 text-muted-foreground" />;
}

export function MapCardGrid({ map, onDelete }: MapCardProps) {
  const { t } = useTranslation();
  const [imgError, setImgError] = useState(false);

  return (
    <TooltipProvider>
      <Card className="flex flex-col overflow-hidden hover:shadow-md hover:border-primary/20 hover:bg-accent/50 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out">
        {/* Thumbnail */}
        <Link
          to={`/maps/${map.id}`}
          className="aspect-video bg-muted flex items-center justify-center overflow-hidden"
        >
          {map.thumbnail_url && !imgError ? (
            <img
              src={`${API_BASE}${map.thumbnail_url}`}
              alt={t('maps.card.previewAlt', { name: map.name })}
              className="w-full h-full object-cover"
              loading="lazy"
              onError={() => setImgError(true)}
            />
          ) : (
            <MapIcon className="h-10 w-10 text-muted-foreground/40" />
          )}
        </Link>

        {/* Content */}
        <div className="p-4 flex flex-col gap-2 flex-1">
          <div className="flex items-center gap-2">
            <Link
              to={`/maps/${map.id}`}
              className="text-sm font-semibold text-foreground hover:text-primary transition-colors truncate flex-1 min-w-0"
            >
              {map.name}
            </Link>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="shrink-0">
                  <VisibilityIcon visibility={map.visibility} />
                </span>
              </TooltipTrigger>
              <TooltipContent side="top">
                {getVisibilityLabel(t, map.visibility)}
              </TooltipContent>
            </Tooltip>
          </div>

          {map.description && (
            <p className="text-xs text-muted-foreground line-clamp-1">
              {map.description}
            </p>
          )}

          <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1">
            <Badge variant="secondary" className="text-xs gap-1">
              <Layers className="h-3 w-3" />
              {t('maps.layerCount', { count: map.layer_count })}
            </Badge>
            {map.created_by_username && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <User className="h-3 w-3" />
                {map.created_by_username}
              </span>
            )}
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Calendar className="h-3 w-3" />
              {t('maps.card.updated', { date: formatDate(map.updated_at) })}
            </span>
          </div>

          <div className="flex justify-end">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive transition-colors duration-150"
                  onClick={() => onDelete(map.id)}
                  aria-label={t('maps.card.delete')}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">{t('maps.card.delete')}</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </Card>
    </TooltipProvider>
  );
}
