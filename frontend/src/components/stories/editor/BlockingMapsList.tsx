import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';

/** The maps that keep a story from reaching its audience, linked so the author can change their visibility. */
export function BlockingMapsList({
  maps,
  unreadableMaps,
}: {
  maps: { id: string; name: string }[];
  unreadableMaps: number;
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
