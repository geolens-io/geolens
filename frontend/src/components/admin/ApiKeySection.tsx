import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/hooks/use-admin';
import { formatDate } from '@/lib/format';
import { activeDotColor } from '@/lib/status-colors';
import type { ApiKeyResponse, ApiKeyCreateResponse } from '@/types/api';
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

interface ApiKeySectionProps {
  userId: string;
}

function relativeTime(
  dateStr: string | null,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (!dateStr) return t('apiKeys.neverUsed');
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return t('apiKeys.justNow');
  if (minutes < 60) return t('apiKeys.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('apiKeys.hoursAgo', { count: hours });
  const days = Math.floor(hours / 24);
  return t('apiKeys.daysAgo', { count: days });
}

export function ApiKeySection({ userId }: ApiKeySectionProps) {
  const { t } = useTranslation('admin');
  const { data: keys, isLoading } = useApiKeys(userId);
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [keyName, setKeyName] = useState('');
  const [revealKey, setRevealKey] = useState<ApiKeyCreateResponse | null>(null);
  const [revokingKey, setRevokingKey] = useState<ApiKeyResponse | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!keyName.trim()) return;

    try {
      const result = await createApiKey.mutateAsync({ userId, name: keyName.trim() });
      setKeyName('');
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

      {!isLoading && (!keys || keys.length === 0) && (
        <p className="text-sm text-muted-foreground">{t('apiKeys.noKeys')}</p>
      )}

      {keys && keys.length > 0 && (
        <div className="space-y-2">
          {keys.map((key) => (
            <div
              key={key.id}
              className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
            >
              <div className="flex-1 min-w-0 space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{key.name}</span>
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      activeDotColor[String(key.is_active) as keyof typeof activeDotColor]
                    }`}
                    title={key.is_active ? t('apiKeys.active') : t('apiKeys.revoked')}
                  />
                </div>
                <div className="text-xs text-muted-foreground">
                  {t('apiKeys.created', { date: formatDate(key.created_at) })} · {t('apiKeys.lastUsed')} {relativeTime(key.last_used_at, t)}
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
