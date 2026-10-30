/** The server's upload limits for story images (stories/images.py), checked before sending. */
const STORY_IMAGE_MAX_BYTES = 50 * 1024 * 1024;
export const STORY_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

/**
 * The common error key for a file the server would refuse by its type or
 * size, or null. A file the browser reports no type for goes to the server,
 * which decides by its bytes.
 */
export function precheckStoryImage(file: File): `errors.${string}` | null {
  if (file.type && !STORY_IMAGE_TYPES.includes(file.type)) return 'errors.storyImageUnsupported';
  if (file.size > STORY_IMAGE_MAX_BYTES) return 'errors.storyImageTooLarge';
  return null;
}
