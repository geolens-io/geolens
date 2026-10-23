import { useState } from 'react';
import type { GroupRef } from '@/types/api';

/** Which sentence says what saving does to the audience at the current visibility. */
export function groupEffectKey(visibility: string, hadGroups: boolean, hasGroups: boolean) {
  if (visibility === 'private') return hasGroups ? 'effectToRestricted' : 'effectPrivateEmpty';
  if (visibility === 'restricted') return hasGroups || !hadGroups ? 'effectRestricted' : 'effectToPrivate';
  return 'effectKept';
}

/**
 * The group list being edited, the server's list as the baseline until the
 * user changes it, and the text a section's one live region announces.
 */
export function useGroupDraft(current: GroupRef[]) {
  const [draft, setDraft] = useState<GroupRef[] | null>(null);
  const [announcement, setAnnouncement] = useState({ text: '', n: 0 });

  const selected = draft ?? current;
  const dirty =
    selected.length !== current.length || selected.some((g) => !current.some((c) => c.id === g.id));

  return {
    selected,
    dirty,
    edit: setDraft,
    reset: () => setDraft(null),
    announcement,
    announce: (text: string) => setAnnouncement((prev) => ({ text, n: prev.n + 1 })),
  };
}
