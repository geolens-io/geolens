import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DashboardConfig } from '@/types/api';

type Theme = 'dark' | 'light' | 'system';
type ResolvedTheme = Exclude<Theme, 'system'>;

type ThemeProviderProps = {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string; // Must match FOUC script in index.html
};

type ThemeProviderState = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  resolvedTheme: ResolvedTheme;
  /** The theme a reader-facing page imposes, or null when the reader's own applies. */
  forcedTheme: ResolvedTheme | null;
};

type ForcedThemeSetter = (owner: object, theme: ResolvedTheme | null) => void;

const ThemeProviderContext = createContext<ThemeProviderState>({
  theme: 'system',
  setTheme: () => null,
  resolvedTheme: 'light',
  forcedTheme: null,
});

// Its own context so a page that forces a theme doesn't re-render when the theme changes.
const ForcedThemeContext = createContext<ForcedThemeSetter>(() => null);

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// localStorage access throws in storage-blocked contexts (Safari
// private-mode iframes, strict cookie settings) — exactly the embed surface.
// Guard reads/writes so the app still mounts with an in-memory theme, matching
// how theme-init.js and the persisted zustand stores tolerate blocked storage.
function readStoredTheme(storageKey: string): Theme | null {
  try {
    return localStorage.getItem(storageKey) as Theme | null;
  } catch {
    return null;
  }
}

function writeStoredTheme(storageKey: string, theme: Theme): void {
  try {
    localStorage.setItem(storageKey, theme);
  } catch {
    // Storage blocked — theme still applies in-memory for this session.
  }
}

export function ThemeProvider({
  children,
  defaultTheme = 'system',
  storageKey = 'geolens-theme', // Must match FOUC script in index.html
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(
    () => readStoredTheme(storageKey) || defaultTheme,
  );
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(getSystemTheme);

  // One slot, cleared only by the page that filled it, so a page that
  // unmounts after its successor mounted can't undo the successor's theme.
  const [forced, setForced] = useState<{ owner: object; theme: ResolvedTheme } | null>(null);
  const forcedTheme = forced?.theme ?? null;
  const resolvedTheme: ResolvedTheme =
    forcedTheme ?? (theme === 'system' ? systemTheme : theme);

  const setForcedTheme = useCallback<ForcedThemeSetter>(
    (owner, next) =>
      setForced((current) => {
        if (next) return { owner, theme: next };
        return current?.owner === owner ? null : current;
      }),
    [],
  );

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mq) return;
    const handler = () => setSystemTheme(mq.matches ? 'dark' : 'light');
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  // A forced theme paints before the first frame only when the page renders
  // with a warm query cache; on a cold load the stored theme shows through the
  // loading state and flips when the document arrives.
  useLayoutEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove('light', 'dark');
    root.classList.add(resolvedTheme);
  }, [resolvedTheme]);

  const setTheme = (t: Theme) => {
    writeStoredTheme(storageKey, t);
    setThemeState(t);
  };

  return (
    <ForcedThemeContext.Provider value={setForcedTheme}>
      <ThemeProviderContext.Provider value={{ theme, setTheme, resolvedTheme, forcedTheme }}>
        {children}
      </ThemeProviderContext.Provider>
    </ForcedThemeContext.Provider>
  );
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext);
  if (context === undefined)
    throw new Error('useTheme must be used within a ThemeProvider');
  return context;
};

/**
 * Shows the calling page in `theme` while it is mounted, leaving the stored
 * preference alone. `follow` and null both leave the reader's own theme.
 */
export function useForcedTheme(theme: DashboardConfig['theme'] | null | undefined) {
  const setForcedTheme = useContext(ForcedThemeContext);
  const owner = useRef({}).current;
  const forced = theme === 'light' || theme === 'dark' ? theme : null;
  useLayoutEffect(() => {
    setForcedTheme(owner, forced);
    return () => setForcedTheme(owner, null);
  }, [setForcedTheme, owner, forced]);
}
