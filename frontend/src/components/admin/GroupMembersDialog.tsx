import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, X } from 'lucide-react';
import { useUserNames } from '@/hooks/use-admin';
import { usePermissions } from '@/hooks/use-permissions';
import {
  useGroupMembers,
  useAddGroupMember,
  useRemoveGroupMember,
} from '@/hooks/use-admin-groups';
import type { GroupResponse } from '@/types/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { UserPicker, type PickerUser } from './UserPicker';

interface GroupMembersDialogProps {
  group: GroupResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function GroupMembersDialog({ group, open, onOpenChange }: GroupMembersDialogProps) {
  const { t } = useTranslation('admin');
  const members = useGroupMembers(group.id);
  // The names endpoint needs manage_users, which a multi-tenant operator
  // managing groups through manage_tenants may not hold.
  const canListUsers = usePermissions().can('manage_users');
  const names = useUserNames({ enabled: canListUsers });
  const add = useAddGroupMember(group.id);
  const remove = useRemoveGroupMember(group.id);
  const pickerRef = useRef<HTMLInputElement>(null);
  const [outcome, setOutcome] = useState({ text: '', n: 0 });

  const memberIds = useMemo(() => new Set((members.data ?? []).map((m) => m.id)), [members.data]);
  const candidates = useMemo(
    () => (names.data ?? []).filter((u) => !memberIds.has(u.id)),
    [names.data, memberIds],
  );
  const error = add.error ?? remove.error ?? (canListUsers ? names.error : null);

  function announce(text: string) {
    setOutcome((prev) => ({ text, n: prev.n + 1 }));
  }

  async function handleAdd(user: PickerUser) {
    if (add.isPending) return;
    remove.reset();
    try {
      await add.mutateAsync(user.id);
      announce(t('groups.members.added', { name: user.username }));
    } catch {
      // error displayed inline
    }
  }

  async function handleRemove(user: PickerUser) {
    add.reset();
    try {
      await remove.mutateAsync(user.id);
      announce(t('groups.members.removed', { name: user.username }));
      // The removed row's button is gone; the picker is the stable place to land.
      pickerRef.current?.focus();
    } catch {
      // error displayed inline
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        onOpenAutoFocus={(event) => {
          if (!pickerRef.current) return;
          event.preventDefault();
          pickerRef.current.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>{t('groups.members.title', { name: group.name })}</DialogTitle>
          <DialogDescription>{t('groups.members.description')}</DialogDescription>
        </DialogHeader>

        {canListUsers ? (
          <UserPicker
            ref={pickerRef}
            label={t('groups.members.addLabel')}
            users={candidates}
            onSelect={handleAdd}
          />
        ) : (
          <p className="text-sm text-muted-foreground">{t('groups.members.needsUserManagement')}</p>
        )}

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error.message}
          </p>
        )}

        <div className="space-y-2">
          <h3 className="text-sm font-medium">
            {t('groups.members.listHeading', { count: members.data?.length ?? group.member_count })}
          </h3>
          {members.isLoading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" /> {t('common:loading')}
            </p>
          ) : members.error ? (
            <p role="alert" className="text-sm text-destructive">
              {t('groups.members.errorLoading', { message: members.error.message })}
            </p>
          ) : members.data && members.data.length > 0 ? (
            <ul aria-label={t('groups.members.listLabel', { name: group.name })} className="max-h-64 divide-y overflow-auto rounded-md border">
              {members.data.map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm">
                  <span>{member.username}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={remove.isPending}
                    aria-label={t('groups.members.removeLabel', { name: member.username, group: group.name })}
                    onClick={() => handleRemove(member)}
                  >
                    <X className="size-4" aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p role="status" className="rounded-md border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">
              {t('groups.members.empty')}
            </p>
          )}
        </div>

        <LiveAnnouncement text={outcome.text} trigger={String(outcome.n)} />

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
