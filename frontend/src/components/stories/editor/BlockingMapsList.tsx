import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { BlockingMap } from '@/api/stories';

/** The sentence that explains why a publish, or a share with groups, was refused. */
export function blockedDescriptionKey(toGroups: boolean, canShareMaps: boolean): string {
  if (!toGroups) return 'publish.blockedDescription';
  return canShareMaps ? 'groups.blockedCanShare' : 'groups.blockedCannotShare';
}

/**
 * The maps that keep a story from reaching its audience, linked so the author
 * can change their visibility. With `sharing`, each map the author can't share
 * with the story's groups says so.
 */
export function BlockingMapsList({
  maps,
  unreadableMaps,
  sharing = false,
}: {
  maps: BlockingMap[];
  unreadableMaps: number;
  sharing?: boolean;
}) {
  const { t } = useTranslation('stories');
  return (
    <>
      {maps.length > 0 && (
        <ul className="list-disc space-y-1 ps-5">
          {maps.map((map) => (
            <li key={map.id}>
              <Link to={`/maps/${map.id}`} target="_blank" rel="noopener" className="text-primary underline">
                {map.name}
              </Link>
              {sharing && !map.canShare && (
                <span className="text-muted-foreground"> {t('groups.cannotShareMap')}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {unreadableMaps > 0 && (
        <p className="text-muted-foreground">{t('publish.unreadableMaps', { count: unreadableMaps })}</p>
      )}
    </>
  );
}
