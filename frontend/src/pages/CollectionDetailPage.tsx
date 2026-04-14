import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, Link } from 'react-router';
import { Calendar, Database, MapPin, MoreHorizontal, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/PageShell';
import { PageHeader } from '@/components/layout/PageHeader';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { CollectionDatasetList } from '@/components/collections/CollectionDatasetList';
import { CollectionMembershipManager } from '@/components/collections/CollectionMembershipManager';
import { CollectionEditDialog } from '@/components/collections/CollectionEditDialog';
import { CollectionDeleteDialog } from '@/components/collections/CollectionDeleteDialog';
import { useCollection, useRemoveDatasetFromCollection } from '@/hooks/use-collections';
import { useAuthStore } from '@/stores/auth-store';
import { formatDate, formatNumber } from '@/lib/format';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useDocumentTitle } from '@/hooks/use-document-title';

export function CollectionDetailPage() {
  const { t } = useTranslation('collections');
  const { id } = useParams<{ id: string }>();
  const { data: collection, isLoading, error } = useCollection(id ?? '');
  const removeDataset = useRemoveDatasetFromCollection();
  const isEditor = useAuthStore((s) => s.isEditor());
  const isAdmin = useAuthStore((s) => s.isAdmin());

  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  useDocumentTitle(collection?.name ?? t('common:pageTitle.collection'));

  if (isLoading) {
    return (
      <PageShell maxWidth="narrow">
        <LoadingState message={t('detail.loading')} />
      </PageShell>
    );
  }

  if (error || !collection) {
    return (
      <PageShell maxWidth="narrow">
        <ErrorState
          title={t('detail.notFoundTitle')}
          message={error instanceof Error ? error.message : t('detail.notFoundMessage')}
          action={
            <Link
              to="/collections"
              className="text-sm text-primary hover:underline inline-flex items-center gap-1"
            >
              {t('detail.backToCollections')}
            </Link>
          }
        />
      </PageShell>
    );
  }

  const bbox =
    collection.extent_bbox && collection.extent_bbox.length >= 4
      ? (collection.extent_bbox as [number, number, number, number])
      : null;

  const formatTemporal = (): string => {
    if (!collection.temporal_start && !collection.temporal_end) return t('detail.temporalNotAvailable');
    const start = collection.temporal_start
      ? formatDate(collection.temporal_start)
      : '...';
    const end = collection.temporal_end
      ? formatDate(collection.temporal_end)
      : t('detail.temporalPresent');
    return `${start} - ${end}`;
  };

  async function handleRemoveDataset(datasetId: string) {
    try {
      await removeDataset.mutateAsync({ collectionId: id!, datasetId });
      toast.success(t('toasts.datasetRemoved'));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t('toasts.removeError'),
      );
    }
  }

  /*
   * Collection detail uses a flat card+list layout intentionally distinct
   * from dataset detail's tabbed approach. Collections are lightweight
   * containers — a tabbed interface would over-complicate what is
   * essentially "metadata + member list". See COLL-03.
   */
  return (
    <PageShell maxWidth="narrow">
      <PageHeader
        title={collection.name}
        description={collection.description ?? undefined}
        breadcrumbs={[{ label: t('detail.breadcrumb'), to: '/collections' }]}
        actions={
          (isEditor || isAdmin) ? (
            <>
              {isEditor && (
                <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                  <Pencil className="h-4 w-4 me-1" />
                  {t('common:edit')}
                </Button>
              )}
              {isAdmin && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="sm" aria-label={t('common:moreActions', { defaultValue: 'More actions' })}>
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onSelect={() => setDeleteOpen(true)}
                    >
                      <Trash2 className="h-4 w-4" />
                      {t('common:delete')}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </>
          ) : undefined
        }
      />

      {/* Metadata card */}
      <Card>
        <CardContent className="pt-6">
          <dl aria-label="Collection metadata" className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {/* Left: metadata fields */}
            <div className="space-y-4">
              <div className="space-y-2">
                <dt className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                  <Database className="h-4 w-4" />
                  {t('detail.datasets')}
                </dt>
                <dd className="text-sm">{formatNumber(collection.dataset_count)}</dd>
              </div>
              <div className="space-y-2">
                <dt className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                  <Calendar className="h-4 w-4" />
                  {t('detail.temporalRange')}
                </dt>
                <dd className="text-sm">{formatTemporal()}</dd>
              </div>
              <div className="space-y-2">
                <dt className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                  <Calendar className="h-4 w-4" />
                  {t('detail.created')}
                </dt>
                <dd className="text-sm">{formatDate(collection.created_at)}</dd>
              </div>
              <div className="space-y-2">
                <dt className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                  <Calendar className="h-4 w-4" />
                  {t('detail.lastUpdated')}
                </dt>
                <dd className="text-sm">{formatDate(collection.updated_at)}</dd>
              </div>
            </div>

            {/* Right: spatial extent */}
            <div className="space-y-2">
              <dt className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                <MapPin className="h-4 w-4" />
                {t('detail.spatialExtent')}
              </dt>
              <dd>
                <BBoxPreview bbox={bbox} />
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {/* Datasets section */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">{t('detail.datasets')}</h2>
        <CollectionDatasetList
          collectionId={id!}
          onRemove={isEditor ? handleRemoveDataset : undefined}
        />
      </div>

      {/* Add datasets section (editors only) */}
      {isEditor && (
        <CollectionMembershipManager
          collectionId={id!}
        />
      )}

      {/* Edit dialog */}
      <CollectionEditDialog
        collection={collection}
        open={editOpen}
        onOpenChange={setEditOpen}
      />

      {/* Delete dialog */}
      <CollectionDeleteDialog
        collection={collection}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
      />
    </PageShell>
  );
}
