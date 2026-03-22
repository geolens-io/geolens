import { Link } from 'react-router';
import { Map } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useDatasetMaps } from '@/hooks/use-maps';
import { formatRelativeDate } from '@/lib/format';

interface UsedInMapsProps {
  datasetId: string;
}

export function UsedInMaps({ datasetId }: UsedInMapsProps) {
  const { data, isLoading, isError } = useDatasetMaps(datasetId);

  if (isLoading || isError || !data || data.maps.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Map className="h-5 w-5" />
          Used in Maps
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {data.maps.map((map) => (
            <Link
              key={map.id}
              to={`/maps/${map.id}`}
              className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-muted"
            >
              <span className="text-sm font-medium truncate min-w-0">
                {map.name}
              </span>
              <div className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
                {map.created_by_username && (
                  <span>{map.created_by_username}</span>
                )}
                <span>{formatRelativeDate(map.updated_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
