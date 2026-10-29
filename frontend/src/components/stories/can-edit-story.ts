import type { Capability } from '@/lib/capabilities';

/** The story draft endpoints need the caller to own the story (or be an admin) and to hold edit_metadata. */
export function canEditStory(can: (capability: Capability) => boolean, story: { can_edit: boolean }): boolean {
  return story.can_edit && can('edit_metadata');
}
