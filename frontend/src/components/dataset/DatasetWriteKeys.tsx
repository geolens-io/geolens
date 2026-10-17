import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Trash } from 'lucide-react';
import {
  useCreateDatasetApiKey,
  useDatasetApiKeys,
  useRevokeDatasetApiKey,
} from '@/components/dataset/hooks/use-dataset-api-keys';
import { ApiKeyRevealDialog } from '@/components/admin/ApiKeyRevealDialog';
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldLabel } from '@/components/ui/field-label';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { isApiKeyExpired } from '@/lib/api-key-expiry';
import { formatDate } from '@/lib/format';
import { formatLastUsedRelativeTime } from '@/lib/relative-time';
import { semanticBadgeColors } from '@/lib/status-colors';
import { useAuthStore } from '@/stores/auth-store';
import type { ApiKeyCreateResponse, DatasetApiKeyResponse } from '@/types/api';

type ExpiryDays = '30' | '90' | '365';

const DAY_MS = 24 * 60 * 60 * 1000;
// Short of the full span, so a client clock running ahead of the server's
// still lands inside the server's 365-day cap.
const CLOCK_SKEW_MS = 5 * 60 * 1000;

function expiryFromNow(days: ExpiryDays): string {
  return new Date(Date.now() + Number(days) * DAY_MS - CLOCK_SKEW_MS).toISOString();
}

/** Mint, list and revoke this dataset's write keys. Shown only to its editors. */
export function DatasetWriteKeys({ datasetId }: { datasetId: string }) {
  const { t } = useTranslation('dataset');
  const expiryLabelId = useId();
  const currentUserId = useAuthStore((s) => s.user?.id);
  const { data: keys, isLoading, isError } = useDatasetApiKeys(datasetId);
  const createKey = useCreateDatasetApiKey(datasetId);
  const revokeKey = useRevokeDatasetApiKey(datasetId);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [expiry, setExpiry] = useState<ExpiryDays>('90');
  const [revealKey, setRevealKey] = useState<ApiKeyCreateResponse | null>(null);
  const [revokingKey, setRevokingKey] = useState<DatasetApiKeyResponse | null>(null);
  const [now] = useState(() => new Date());

  function resetForm() {
    setShowForm(false);
    setName('');
    setExpiry('90');
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const result = await createKey.mutateAsync({
        name: name.trim(),
        expires_at: expiryFromNow(expiry),
      });
      resetForm();
      setRevealKey(result);
    } catch {
      // The mutation's onError reports it.
    }
  }

  async function handleRevoke() {
    if (!revokingKey) return;
    try {
      await revokeKey.mutateAsync(revokingKey.id);
      setRevokingKey(null);
    } catch {
      // The mutation's onError reports it.
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle level={2} className="text-base">{t('writeKeys.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{t('writeKeys.description')}</p>

        {!showForm && (
          <Button variant="outline" size="sm" onClick={() => setShowForm(true)}>
            {t('writeKeys.createKey')}
          </Button>
        )}

        {showForm && (
          <form onSubmit={handleCreate} className="flex flex-wrap items-center gap-2">
            <FieldLabel htmlFor="dataset-write-key-name">{t('admin:apiKeys.keyName')}</FieldLabel>
            <Input
              id="dataset-write-key-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('admin:apiKeys.keyName')}
              className="h-8 w-56 text-sm"
              maxLength={255}
              // eslint-disable-next-line jsx-a11y/no-autofocus -- intentional: user just clicked "create" to open this form
              autoFocus
            />
            {/* One unit, so a narrow screen wraps the pair rather than between them. */}
            <div className="flex items-center gap-2">
              <span id={expiryLabelId} className="text-xs text-muted-foreground">
                {t('writeKeys.expiresIn')}
              </span>
              <Select
                value={expiry}
                onValueChange={(v) => setExpiry(v as ExpiryDays)}
                disabled={createKey.isPending}
              >
                <SelectTrigger className="h-8 w-auto min-w-[110px] text-sm" aria-labelledby={expiryLabelId}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="30">{t('writeKeys.expiry30')}</SelectItem>
                  <SelectItem value="90">{t('writeKeys.expiry90')}</SelectItem>
                  <SelectItem value="365">{t('writeKeys.expiry365')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" size="sm" disabled={createKey.isPending || !name.trim()}>
              {createKey.isPending && <Loader2 className="size-4 animate-spin" />}
              {createKey.isPending ? t('admin:apiKeys.creating') : t('common:create')}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={resetForm}>
              {t('common:cancel')}
            </Button>
          </form>
        )}

        {isLoading && <p className="text-sm text-muted-foreground">{t('admin:apiKeys.loadingKeys')}</p>}
        {isError && (
          <p role="alert" className="text-sm text-destructive">{t('writeKeys.loadError')}</p>
        )}
        {!isLoading && !isError && keys?.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('writeKeys.noKeys')}</p>
        )}

        {keys && keys.length > 0 && (
          <ul className="space-y-2">
            {keys.map((key) => {
              const expired = isApiKeyExpired(key.expires_at, now);
              return (
                <li
                  key={key.id}
                  className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                >
                  <div className="flex-1 min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{key.name}</span>
                      {key.fingerprint && (
                        <code className="text-xs text-muted-foreground">{key.fingerprint}</code>
                      )}
                      {expired ? (
                        <Badge className={`px-1.5 ${semanticBadgeColors.destructive}`}>
                          {t('admin:apiKeys.expired')}
                        </Badge>
                      ) : (
                        key.expires_at && (
                          <span className="text-xs text-muted-foreground">
                            {t('admin:apiKeys.expiresOn', { date: formatDate(key.expires_at) })}
                          </span>
                        )
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {key.user_id !== currentUserId && (
                        <>{t('writeKeys.createdBy', { name: key.username })} · </>
                      )}
                      {t('admin:apiKeys.created', { date: formatDate(key.created_at) })} · {t('admin:apiKeys.lastUsed')} {formatLastUsedRelativeTime(key.last_used_at, t)}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive h-8 w-8 p-0"
                    onClick={() => setRevokingKey(key)}
                    aria-label={t('writeKeys.revokeKey', { name: key.name })}
                  >
                    <Trash className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>

      <AlertDialog open={!!revokingKey} onOpenChange={(open) => !open && setRevokingKey(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('admin:apiKeys.revokeDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('admin:apiKeys.revokeDialog.description', { name: revokingKey?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={handleRevoke}
              disabled={revokeKey.isPending}
            >
              {revokeKey.isPending
                ? t('admin:apiKeys.revokeDialog.revoking')
                : t('admin:apiKeys.revokeDialog.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {revealKey && (
        <ApiKeyRevealDialog
          apiKey={revealKey}
          open={!!revealKey}
          onOpenChange={(open) => !open && setRevealKey(null)}
        />
      )}
    </Card>
  );
}
