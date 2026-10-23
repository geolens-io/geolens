import { useEffect, useMemo, useRef, useState } from 'react';
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
  const listRef = useRef<HTMLUListElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  // Where focus goes once the removed row is gone: a member id, or null for Close.
  const focusAfterRefresh = useRef<string | null | undefined>(undefined);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [outcome, setOutcome] = useState({ text: '', n: 0 });

  const memberIds = useMemo(() => new Set((members.data ?? []).map((m) => m.id)), [members.data]);
  // Until the member list has loaded, nobody can be ruled out, and an add of
  // someone already in the group would be skipped by the server yet announced.
  const candidates = useMemo(
    () => (members.data ? (names.data ?? []).filter((u) => !memberIds.has(u.id)) : []),
    [names.data, members.data, memberIds],
  );
  const error = add.error ?? remove.error ?? (canListUsers ? names.error : null);

  useEffect(() => {
    const target = focusAfterRefresh.current;
    if (target === undefined) return;
    focusAfterRefresh.current = undefined;
    const button =
      target === null ? closeRef.current : listRef.current?.querySelector<HTMLElement>(`[data-remove-id="${target}"]`);
    button?.focus();
  }, [members.data]);

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
      // The removed row's button is gone; land on the picker, or without one
      // on a neighbouring row once the list refreshes.
      if (pickerRef.current) pickerRef.current.focus();
      else {
        const rows = members.data ?? [];
        const index = rows.findIndex((m) => m.id === user.id);
        focusAfterRefresh.current = (rows[index + 1] ?? rows[index - 1])?.id ?? null;
      }
    } catch {
      // error displayed inline
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        // Radix handles Escape on the document first; leave the first press to the picker's list.
        onEscapeKeyDown={(event) => {
          if (pickerOpen) event.preventDefault();
        }}
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
            onOpenChange={setPickerOpen}
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
            <ul ref={listRef} aria-label={t('groups.members.listLabel', { name: group.name })} className="max-h-64 divide-y overflow-auto rounded-md border">
              {members.data.map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm">
                  <span>{member.username}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={remove.isPending}
                    data-remove-id={member.id}
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
          <Button ref={closeRef} variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
