import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/hooks/use-admin';
import { formatDate } from '@/lib/format';
// chore(#835): consolidated into the shared formatter (was written out here
// and in settings/MyApiKeySection.tsx).
import { formatLastUsedRelativeTime } from '@/lib/relative-time';
import { activeDotColor } from '@/lib/status-colors';
import type { ApiKeyResponse, ApiKeyCreateResponse, ApiKeyScope } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Loader2, Trash } from 'lucide-react';
import { ApiKeyRevealDialog } from './ApiKeyRevealDialog';
import { ApiKeyScopeSelect } from './ApiKeyScopeSelect';
import { Badge } from '@/components/ui/badge';

interface ApiKeySectionProps {
  userId: string;
}


export function ApiKeySection({ userId }: ApiKeySectionProps) {
  const { t } = useTranslation('admin');
  // fix(#1805 review round 3 P2): the flat limit=200 fetch was itself the
  // backend's hard cap -- a user past 200 keys still had no way to reach
  // the rest, the exact defect #1778 set out to fix. pageCount grows via
  // the "Load more" control below until every key is loaded.
  const [pageCount, setPageCount] = useState(1);
  const {
    items: keys,
    total = 0,
    isLoading,
    hasMore,
    isError: apiKeysError,
    error: apiKeysErrorObj,
    retryFailedPage,
  } = useApiKeys(userId, pageCount);
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [keyName, setKeyName] = useState('');
  const [keyScope, setKeyScope] = useState<ApiKeyScope>('full');
  const [revealKey, setRevealKey] = useState<ApiKeyCreateResponse | null>(null);
  const [revokingKey, setRevokingKey] = useState<ApiKeyResponse | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!keyName.trim()) return;

    try {
      const result = await createApiKey.mutateAsync({
        userId,
        name: keyName.trim(),
        scope: keyScope,
      });
      setKeyName('');
      setKeyScope('full');
      setShowCreateForm(false);
      setRevealKey(result);
    } catch {
      // error displayed via mutation state
    }
  }

  async function handleRevoke() {
    if (!revokingKey) return;

    try {
      await revokeApiKey.mutateAsync({ keyId: revokingKey.id, userId });
      setRevokingKey(null);
    } catch {
      // error displayed via mutation state
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">{t('apiKeys.title')}</h4>
        {!showCreateForm && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowCreateForm(true)}
          >
            {t('apiKeys.createKey')}
          </Button>
        )}
      </div>

      {showCreateForm && (
        <form onSubmit={handleCreate} className="flex items-center gap-2">
          <Input
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            placeholder={t('apiKeys.keyName')}
            className="h-8 text-sm"
            // eslint-disable-next-line jsx-a11y/no-autofocus -- intentional: user just clicked "create" to open this form
            autoFocus
          />
          <ApiKeyScopeSelect
            value={keyScope}
            onChange={setKeyScope}
            disabled={createApiKey.isPending}
          />
          <Button type="submit" size="sm" disabled={createApiKey.isPending || !keyName.trim()}>
            {createApiKey.isPending && <Loader2 className="size-4 animate-spin" />}
            {createApiKey.isPending ? t('apiKeys.creating') : t('common:create')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setShowCreateForm(false);
              setKeyName('');
              setKeyScope('full');
            }}
          >
            {t('common:cancel')}
          </Button>
        </form>
      )}

      {createApiKey.error && (
        <p className="text-sm text-destructive">
          {createApiKey.error instanceof Error ? createApiKey.error.message : t('apiKeys.createError')}
        </p>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">{t('apiKeys.loadingKeys')}</p>}

      {/* fix(#1805 review round 4 P2): a failed page used to be dropped
          silently, so the section fell through to "No API keys" (or just
          stopped growing) with no indication anything went wrong. */}
      {apiKeysError && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
          <p className="text-destructive">
            {apiKeysErrorObj instanceof Error ? apiKeysErrorObj.message : t('apiKeys.loadError')}
          </p>
          <Button variant="outline" size="sm" onClick={() => retryFailedPage()}>
            {t('apiKeys.retry')}
          </Button>
        </div>
      )}

      {!isLoading && !apiKeysError && keys.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('apiKeys.noKeys')}</p>
      )}

      {keys.length > 0 && (
        <div className="space-y-2">
          {/* fix(#1778): `total` used to be fetched and dropped, so a user
              past the 50-key page limit had no indication more existed. */}
          {total > keys.length && (
            <p className="text-xs text-muted-foreground">
              {t('apiKeys.showingOf', { shown: keys.length, total })}
            </p>
          )}
          {keys.map((key) => (
            <div
              key={key.id}
              className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
            >
              <div className="flex-1 min-w-0 space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{key.name}</span>
                  {key.fingerprint && (
                    <code className="text-xs text-muted-foreground">
                      {key.fingerprint}
                    </code>
                  )}
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      activeDotColor[String(key.is_active) as keyof typeof activeDotColor]
                    }`}
                    title={key.is_active ? t('apiKeys.active') : t('apiKeys.revoked')}
                    aria-hidden="true"
                  />
                  {/* #305: state was conveyed by dot color + non-announced title only; add a text alt for assistive tech */}
                  <span className="sr-only">
                    {key.is_active ? t('apiKeys.active') : t('apiKeys.revoked')}
                  </span>
                  {/* fix(#875): an admin auditing another user's keys needs to
                      see which of them can write. */}
                  {key.scope === 'read_only' && (
                    <Badge variant="secondary" className="px-1.5">
                      {t('apiKeys.scopeReadOnly')}
                    </Badge>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">
                  {t('apiKeys.created', { date: formatDate(key.created_at) })} · {t('apiKeys.lastUsed')} {formatLastUsedRelativeTime(key.last_used_at, t)}
                </div>
              </div>
              {key.is_active && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive h-8 w-8 p-0"
                  onClick={() => setRevokingKey(key)}
                >
                  <Trash className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
          {hasMore && (
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => setPageCount((n) => n + 1)}
              disabled={isLoading}
            >
              {isLoading ? t('apiKeys.loadingKeys') : t('apiKeys.loadMore')}
            </Button>
          )}
        </div>
      )}

      {revokeApiKey.error && (
        <p className="text-sm text-destructive">
          {revokeApiKey.error instanceof Error ? revokeApiKey.error.message : t('apiKeys.revokeError')}
        </p>
      )}

      {/* Revoke confirmation dialog */}
      <AlertDialog open={!!revokingKey} onOpenChange={(open) => !open && setRevokingKey(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('apiKeys.revokeDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('apiKeys.revokeDialog.description', { name: revokingKey?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={handleRevoke}
              disabled={revokeApiKey.isPending}
            >
              {revokeApiKey.isPending ? t('apiKeys.revokeDialog.revoking') : t('apiKeys.revokeDialog.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reveal dialog for newly created key */}
      {revealKey && (
        <ApiKeyRevealDialog
          apiKey={revealKey}
          open={!!revealKey}
          onOpenChange={(open) => !open && setRevealKey(null)}
        />
      )}
    </div>
  );
}
