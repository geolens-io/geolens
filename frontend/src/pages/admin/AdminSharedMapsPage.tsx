import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import {
  useShareTokens,
  useAdminRevokeShareToken,
  useAdminEmbedTokens,
  useBulkRevokeEmbedTokens,
} from '@/hooks/use-admin';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { DataTablePagination } from '@/components/admin/DataTablePagination';
import { DataTableSkeleton } from '@/components/admin/DataTableSkeleton';
import { Link } from 'react-router';
import { Input } from '@/components/ui/input';
import { Link2Off, ChevronDown, ChevronRight, Key, ShieldOff, Search } from 'lucide-react';
import { toast } from 'sonner';
import type { AdminShareTokenResponse, AdminEmbedTokenResponse } from '@/types/api';
import { formatDate } from '@/lib/format';
import { useDocumentTitle } from '@/hooks/use-document-title';

const PAGE_SIZE = 50;

type EmbedTokenStatus = 'active' | 'expiring_soon' | 'expired' | 'revoked';

function getShareStatus(token: AdminShareTokenResponse): 'active' | 'revoked' | 'expired' {
  if (!token.is_active) return 'revoked';
  if (token.expires_at && new Date(token.expires_at) < new Date()) return 'expired';
  return 'active';
}

function getDaysLeft(expiresAt: string): number {
  return Math.ceil(
    (new Date(expiresAt).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
  );
}

function getEmbedStatus(token: AdminEmbedTokenResponse): EmbedTokenStatus {
  if (!token.is_active) return 'revoked';
  const daysLeft = getDaysLeft(token.expires_at);
  if (daysLeft <= 0) return 'expired';
  if (daysLeft <= 7) return 'expiring_soon';
  return 'active';
}

// ---------------------------------------------------------------------------
// Embed tokens sub-table shown when a share link row is expanded
// ---------------------------------------------------------------------------

function EmbedTokensSubTable({ mapId }: { mapId: string }) {
  const { t } = useTranslation('admin');
  const { data, isLoading, isError } = useAdminEmbedTokens({ map_id: mapId, limit: 200 });
  const bulkRevoke = useBulkRevokeEmbedTokens();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const tokens = data?.tokens ?? [];

  const allSelected = useMemo(
    () => tokens.length > 0 && tokens.every((tk) => selectedIds.has(tk.id)),
    [tokens, selectedIds],
  );

  function toggleSelectAll() {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        for (const tk of tokens) next.delete(tk.id);
      } else {
        for (const tk of tokens) next.add(tk.id);
      }
      return next;
    });
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function embedStatusBadge(token: AdminEmbedTokenResponse) {
    const s = getEmbedStatus(token);
    switch (s) {
      case 'active':
        return <Badge variant="default" className="bg-green-600 text-white">{t('embedTokens.active')}</Badge>;
      case 'expiring_soon': {
        const days = getDaysLeft(token.expires_at); // reuses already-computed logic
        return (
          <Badge className="bg-amber-500 text-white">
            {days <= 0 ? t('embedTokens.expiresToday') : t('embedTokens.expiringSoon', { days })}
          </Badge>
        );
      }
      case 'expired':
        return <Badge variant="destructive">{t('embedTokens.expired')}</Badge>;
      case 'revoked':
        return <Badge variant="secondary">{t('embedTokens.revoked')}</Badge>;
    }
  }

  async function handleBulkRevoke() {
    try {
      const result = await bulkRevoke.mutateAsync(Array.from(selectedIds));
      toast.success(t('embedTokens.bulkRevokeSuccess', { count: result.revoked_count }));
      setSelectedIds(new Set());
    } catch {
      toast.error(t('embedTokens.bulkRevokeFailed'));
    }
  }

  if (isLoading) {
    return <div className="py-3 text-xs text-muted-foreground">{t('sharedMaps.loadingEmbedTokens')}</div>;
  }

  if (isError) {
    return <div className="py-3 text-xs text-destructive">{t('sharedMaps.loadEmbedTokensFailed')}</div>;
  }

  if (tokens.length === 0) {
    return <div className="py-3 text-xs text-muted-foreground">{t('sharedMaps.noEmbedTokens')}</div>;
  }

  return (
    <div className="space-y-2">
      {selectedIds.size > 0 && (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" size="sm">
              <ShieldOff className="mr-1 h-3 w-3" />
              {t('embedTokens.revokeSelected', { count: selectedIds.size })}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('embedTokens.bulkRevokeTitle')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('embedTokens.bulkRevokeDescription', { count: selectedIds.size })}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('embedTokens.bulkRevokeCancel')}</AlertDialogCancel>
              <AlertDialogAction onClick={handleBulkRevoke}>{t('embedTokens.bulkRevokeConfirm')}</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8">
              <Checkbox checked={allSelected} onCheckedChange={toggleSelectAll} aria-label={t('common:selectAll')} />
            </TableHead>
            <TableHead className="text-xs">{t('embedTokens.tokenHint')}</TableHead>
            <TableHead className="text-xs">{t('embedTokens.status')}</TableHead>
            <TableHead className="text-xs">{t('embedTokens.useCount')}</TableHead>
            <TableHead className="text-xs">{t('embedTokens.lastUsed')}</TableHead>
            <TableHead className="text-xs">{t('embedTokens.expires')}</TableHead>
            <TableHead className="text-xs">{t('embedTokens.origins')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tokens.map((token) => (
            <TableRow key={token.id}>
              <TableCell>
                <Checkbox
                  checked={selectedIds.has(token.id)}
                  onCheckedChange={() => toggleSelect(token.id)}
                  aria-label={t('common:selectItem', { item: token.token_hint })}
                />
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{token.token_hint}</TableCell>
              <TableCell>{embedStatusBadge(token)}</TableCell>
              <TableCell className="text-xs">{token.use_count}</TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {token.last_used_at ? formatDate(token.last_used_at) : t('embedTokens.never')}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatDate(token.expires_at)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate" title={token.allowed_origins?.join(', ') ?? undefined}>
                {token.allowed_origins ? token.allowed_origins.join(', ') : t('embedTokens.noOrigins')}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function AdminSharedMapsPage() {
  const { t } = useTranslation('admin');
  useDocumentTitle('Admin Published Maps');
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const skip = page * PAGE_SIZE;
  const { data, isLoading, isError } = useShareTokens(skip, PAGE_SIZE, debouncedSearch || undefined, statusFilter || undefined);
  const revoke = useAdminRevokeShareToken();

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const total = data?.total ?? 0;
  const tokens = data?.tokens ?? [];
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const rangeStart = total > 0 ? skip + 1 : 0;
  const rangeEnd = Math.min(skip + PAGE_SIZE, total);

  function shareStatusBadge(s: 'active' | 'revoked' | 'expired') {
    if (s === 'active') return <Badge variant="default" className="bg-green-600 text-white">{t('shareTokens.active')}</Badge>;
    if (s === 'expired') return <Badge variant="secondary">{t('shareTokens.expired')}</Badge>;
    return <Badge variant="secondary">{t('shareTokens.revoked')}</Badge>;
  }

  async function handleRevoke(tokenId: string) {
    try {
      await revoke.mutateAsync(tokenId);
      toast.success(t('shareTokens.revokeSuccess'));
    } catch {
      toast.error(t('shareTokens.revokeFailed'));
    }
  }

  return (
    <>
      <PageHeader
        title={t('sharedMaps.title')}
        breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]}
      />
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t('sharedMaps.searchPlaceholder')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <div className="flex gap-1">
              {(['', 'active', 'expired', 'revoked'] as const).map((value) => (
                <Button
                  key={value}
                  variant={statusFilter === value ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => { setStatusFilter(value); setPage(0); }}
                >
                  {t(`sharedMaps.filter${value ? value.charAt(0).toUpperCase() + value.slice(1) : 'All'}`)}
                </Button>
              ))}
            </div>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <TableHead>{t('sharedMaps.mapName')}</TableHead>
                <TableHead>{t('sharedMaps.linkStatus')}</TableHead>
                <TableHead>{t('sharedMaps.embedTokens')}</TableHead>
                <TableHead>{t('sharedMaps.expires')}</TableHead>
                <TableHead>{t('sharedMaps.created')}</TableHead>
                <TableHead>{t('sharedMaps.creator')}</TableHead>
                <TableHead className="text-right">{t('sharedMaps.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isError ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-12 text-destructive">
                    {t('sharedMaps.loadFailed')}
                  </TableCell>
                </TableRow>
              ) : isLoading && !data ? (
                <DataTableSkeleton
                  columns={[
                    { width: 'w-6' },
                    { width: 'w-24' },
                    { width: 'w-14', rounded: true },
                    { width: 'w-14' },
                    { width: 'w-20' },
                    { width: 'w-20' },
                    { width: 'w-16' },
                    { width: 'w-16' },
                  ]}
                />
              ) : tokens.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-12 text-muted-foreground">
                    {t('sharedMaps.empty')}
                  </TableCell>
                </TableRow>
              ) : (
                tokens.map((token) => {
                  const s = getShareStatus(token);
                  const isExpanded = expandedId === token.id;
                  return (
                    <TableRow key={token.id}>
                      <TableCell colSpan={8} className="p-0">
                        <div className="flex items-center px-4 py-3">
                          {/* Expand toggle */}
                          <div className="w-10 shrink-0">
                            {token.embed_token_count > 0 ? (
                              <button
                                type="button"
                                className="text-muted-foreground hover:text-foreground"
                                onClick={() => setExpandedId(isExpanded ? null : token.id)}
                                aria-label={t('sharedMaps.embedTokensFor', { map: token.map_name })}
                              >
                                {isExpanded ? (
                                  <ChevronDown className="h-4 w-4" />
                                ) : (
                                  <ChevronRight className="h-4 w-4" />
                                )}
                              </button>
                            ) : (
                              <span className="inline-block w-4" />
                            )}
                          </div>
                          {/* Map name */}
                          <div className="flex-1 min-w-0 font-medium">
                            <Link to={`/maps/${token.map_id}`} className="hover:underline text-foreground">
                              {token.map_name}
                            </Link>
                          </div>
                          {/* Link status */}
                          <div className="w-24 shrink-0">{shareStatusBadge(s)}</div>
                          {/* Embed tokens count */}
                          <div className="w-28 shrink-0">
                            {token.embed_token_count > 0 ? (
                              <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                                <Key className="h-3 w-3" />
                                {t('sharedMaps.activeCount', { count: token.embed_token_count })}
                              </span>
                            ) : (
                              <span className="text-sm text-muted-foreground">—</span>
                            )}
                          </div>
                          {/* Expires */}
                          <div className="w-28 shrink-0 text-sm text-muted-foreground">
                            {token.expires_at ? formatDate(token.expires_at) : t('shareTokens.never')}
                          </div>
                          {/* Created */}
                          <div className="w-28 shrink-0 text-sm text-muted-foreground">
                            {formatDate(token.created_at)}
                          </div>
                          {/* Creator */}
                          <div className="w-28 shrink-0 text-sm text-muted-foreground truncate" title={token.created_by ?? undefined}>
                            {token.created_by ?? '—'}
                          </div>
                          {/* Actions */}
                          <div className="w-24 shrink-0 text-right">
                            {s === 'active' && (
                              <AlertDialog>
                                <AlertDialogTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    disabled={revoke.isPending}
                                    className="text-destructive hover:text-destructive"
                                  >
                                    <Link2Off className="h-3.5 w-3.5 mr-1" />
                                    {t('shareTokens.revoke')}
                                  </Button>
                                </AlertDialogTrigger>
                                <AlertDialogContent>
                                  <AlertDialogHeader>
                                    <AlertDialogTitle>{t('shareTokens.revokeDialogTitle')}</AlertDialogTitle>
                                    <AlertDialogDescription>
                                      {t('shareTokens.revokeDialogDescription', { map: token.map_name })}
                                    </AlertDialogDescription>
                                  </AlertDialogHeader>
                                  <AlertDialogFooter>
                                    <AlertDialogCancel>{t('shareTokens.revokeDialogCancel')}</AlertDialogCancel>
                                    <AlertDialogAction onClick={() => handleRevoke(token.id)}>
                                      {t('shareTokens.revokeDialogConfirm')}
                                    </AlertDialogAction>
                                  </AlertDialogFooter>
                                </AlertDialogContent>
                              </AlertDialog>
                            )}
                          </div>
                        </div>

                        {/* Expanded embed tokens */}
                        {isExpanded && (
                          <div className="border-t bg-muted/30 px-6 py-4">
                            <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                              {t('sharedMaps.embedTokensFor', { map: token.map_name })}
                            </h4>
                            <EmbedTokensSubTable mapId={token.map_id} />
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>

          <DataTablePagination
            page={page}
            totalPages={totalPages}
            rangeStart={rangeStart}
            rangeEnd={rangeEnd}
            total={total}
            onPageChange={setPage}
          />
        </CardContent>
      </Card>
    </>
  );
}
