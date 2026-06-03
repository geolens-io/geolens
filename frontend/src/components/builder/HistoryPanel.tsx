import { AlertCircle, Clock3, History, Loader2, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useMapHistory } from '@/hooks/use-maps';
import { formatProvenanceTime } from '@/lib/provenance-attribution';
import { cn } from '@/lib/utils';
import type { MapHistoryEntryResponse } from '@/types/api';

interface HistoryPanelProps {
  mapId?: string;
  limit?: number;
  className?: string;
}

function HistoryPanelState({
  icon: Icon,
  title,
  description,
  role,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  role?: 'status' | 'alert';
}) {
  return (
    <div
      role={role}
      className="flex h-full flex-col items-center justify-center gap-2 px-5 py-8 text-center"
    >
      <Icon
        className={cn(
          'h-5 w-5 text-muted-foreground',
          Icon === Loader2 && 'animate-spin',
        )}
        aria-hidden="true"
      />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {description && (
        <p className="max-w-56 text-xs leading-5 text-muted-foreground">{description}</p>
      )}
    </div>
  );
}

function HistoryEntry({ event }: { event: MapHistoryEntryResponse }) {
  const { t, i18n } = useTranslation('builder');
  const fallbackTime = t('history.unknownTime', { defaultValue: 'Unknown time' });
  const timestamp = formatProvenanceTime(event.created_at, {
    fallbackRelative: fallbackTime,
    fallbackAbsolute: fallbackTime,
    locale: i18n.language,
  });
  const actor = event.actor_username ?? t('history.unknownActor', { defaultValue: 'Unknown user' });
  const target = event.target_name ?? null;

  return (
    <li className="group relative min-w-0 pb-4 ps-5 last:pb-0">
      <span
        className="absolute start-1.5 top-1.5 h-2 w-2 rounded-full bg-primary"
        aria-hidden="true"
      />
      <span
        className="absolute bottom-0 start-[0.5625rem] top-4 w-px bg-border group-last:hidden"
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="text-sm leading-5 text-foreground">
          <time
            className="font-medium"
            dateTime={event.created_at}
            title={timestamp.absolute}
          >
            {timestamp.relative}
          </time>
          <span className="text-muted-foreground"> - </span>
          <span>{event.summary}</span>
        </p>
        <p className="mt-1 truncate text-xs text-muted-foreground">
          {target
            ? t('history.actorTarget', {
                actor,
                target,
                defaultValue: '{{actor}} - {{target}}',
              })
            : actor}
        </p>
      </div>
    </li>
  );
}

export function HistoryPanel({ mapId, limit = 50, className }: HistoryPanelProps) {
  const { t } = useTranslation('builder');
  const historyQuery = useMapHistory(mapId, 0, limit);

  if (!mapId) {
    return (
      <HistoryPanelState
        icon={History}
        title={t('history.notAvailableTitle', { defaultValue: 'Save this map to see history' })}
        description={t('history.notAvailableDescription', {
          defaultValue: 'Edit history is available after the map exists.',
        })}
      />
    );
  }

  if (historyQuery.isLoading) {
    return (
      <HistoryPanelState
        icon={Loader2}
        title={t('history.loading', { defaultValue: 'Loading history...' })}
        role="status"
      />
    );
  }

  if (historyQuery.isError) {
    return (
      <HistoryPanelState
        icon={AlertCircle}
        title={t('history.errorTitle', { defaultValue: 'History could not be loaded' })}
        description={t('history.errorDescription', {
          defaultValue: 'Try closing and reopening this panel.',
        })}
        role="alert"
      />
    );
  }

  const events = historyQuery.data?.events ?? [];
  if (events.length === 0) {
    return (
      <HistoryPanelState
        icon={Clock3}
        title={t('history.emptyTitle', { defaultValue: 'No edit history yet' })}
        description={t('history.emptyDescription', {
          defaultValue: 'History starts after saved edits are recorded for this map.',
        })}
      />
    );
  }

  return (
    <div className={cn('h-full overflow-y-auto px-3.5 py-3', className)}>
      <ol aria-label={t('history.timelineLabel', { defaultValue: 'Map edit history' })}>
        {events.map((event) => (
          <HistoryEntry key={event.id} event={event} />
        ))}
      </ol>
    </div>
  );
}
