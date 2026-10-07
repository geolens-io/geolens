import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useDatasetVersions } from '@/components/dataset/hooks/use-dataset';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatDate } from '@/lib/format';
import { GitBranch } from 'lucide-react';
import { LoadingState } from '@/components/layout/LoadingState';
import type { DatasetResponse, DatasetVersionResponse } from '@/types/api';
import { getGeometryTypeLabel, getSourceFormatLabel } from '@/i18n/labels';

interface VersionHistoryProps {
  datasetId: string;
  dataset: DatasetResponse;
}

export function VersionHistory({ datasetId, dataset }: VersionHistoryProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading, isError } = useDatasetVersions(datasetId);

  const { versions, originalUnrecorded } = useMemo(() => {
    const fetched = data?.versions ?? [];
    const hasVersion1 = fetched.some((v) => v.version_number === 1);
    // Version 1 is synthesized only when the whole history is loaded, so a
    // page that stops short of it never invents a row that may exist.
    const wholeHistory = data !== undefined && fetched.length >= data.total;
    // A replaced dataset's own facts describe its latest data, not its first.
    const unrecorded = dataset.current_version > 1;
    const allVersions: DatasetVersionResponse[] =
      hasVersion1 || !wholeHistory
        ? [...fetched]
        : [
            ...fetched,
            {
              id: 'v1-synthetic',
              dataset_id: datasetId,
              version_number: 1,
              source_filename: unrecorded ? null : dataset.source_filename,
              source_format: unrecorded ? null : dataset.source_format,
              feature_count: unrecorded ? null : dataset.feature_count,
              srid: unrecorded ? null : dataset.srid,
              geometry_type: unrecorded ? null : dataset.geometry_type,
              file_hash: null,
              uploaded_by: dataset.created_by,
              uploaded_at: dataset.created_at,
            },
          ];

    return {
      versions: allVersions.sort((a, b) => b.version_number - a.version_number),
      originalUnrecorded: !hasVersion1 && wholeHistory && unrecorded,
    };
  }, [data, datasetId, dataset]);

  return (
    <Card>
      <CardHeader>
        <CardTitle level={3} className="flex items-center gap-2">
          <GitBranch className="h-5 w-5" />
          {t('versionHistory.title')}
          <Badge variant="secondary" className="ms-1">
            {dataset.current_version}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingState className="py-6" />
        ) : isError ? (
          <p className="text-sm text-muted-foreground">{t('versionHistory.loadFailed')}</p>
        ) : versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('versionHistory.noVersions')}</p>
        ) : (
          <div className="space-y-4">
            {versions.map((version) => {
              const isCurrent =
                version.version_number === dataset.current_version;

              // Build metadata line: feature count, geometry type, SRID
              const metaParts: string[] = [];
              if (version.feature_count !== null) {
                metaParts.push(
                  t('versionHistory.features', { count: version.feature_count }),
                );
              }
              if (version.geometry_type) {
                metaParts.push(getGeometryTypeLabel(t, version.geometry_type));
              }
              if (version.srid !== null) {
                metaParts.push(t('versionHistory.srid', { value: version.srid }));
              }

              return (
                <div
                  key={version.id}
                  className="border-s-2 border-muted ps-4 space-y-0.5"
                >
                  <p className="text-sm font-medium flex items-center gap-2">
                    {t('versionHistory.version', { number: version.version_number })}
                    {version.source_format && (
                      <Badge variant="outline" className="text-xs">
                        {getSourceFormatLabel(t, version.source_format)}
                      </Badge>
                    )}
                    {isCurrent && (
                      <Badge
                        variant="default"
                        className="bg-success text-xs"
                      >
                        {t('versionHistory.current')}
                      </Badge>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(version.uploaded_at)} &middot;{' '}
                    {version.source_filename ?? t('versionHistory.unknownFile')}
                  </p>
                  {metaParts.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      {metaParts.join(' \u00B7 ')}
                    </p>
                  )}
                  {originalUnrecorded && version.version_number === 1 && (
                    <p className="text-xs text-muted-foreground">
                      {t('versionHistory.detailsUnrecorded')}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
