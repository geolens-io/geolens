// Single source of truth for Mac-platform detection and the Save keyboard chord.
export const IS_MAC =
  typeof navigator !== 'undefined' &&
  (('userAgentData' in navigator &&
    (navigator.userAgentData as { platform?: string })?.platform === 'macOS') ||
    /Mac/i.test(navigator.userAgent));

/** The Save shortcut chord shown in tooltips and the shortcuts sheet (⌘S / Ctrl+S). */
export const SAVE_SHORTCUT = IS_MAC ? '⌘S' : 'Ctrl+S';
