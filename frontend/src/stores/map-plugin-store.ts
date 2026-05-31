import { create } from 'zustand';

/**
 * Map plugin store: tracks which plugins are currently open/active on the map.
 */
interface PluginState {
  activePlugins: Set<string>;
  open: (id: string) => void;
  close: (id: string) => void;
  toggle: (id: string) => void;
  isOpen: (id: string) => boolean;
}

export const usePluginStore = create<PluginState>((set, get) => ({
  activePlugins: new Set<string>(),
  open: (id) =>
    set((s) => ({ activePlugins: new Set(s.activePlugins).add(id) })),
  close: (id) =>
    set((s) => {
      const next = new Set(s.activePlugins);
      next.delete(id);
      return { activePlugins: next };
    }),
  toggle: (id) =>
    set((s) => {
      const next = new Set(s.activePlugins);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { activePlugins: next };
    }),
  isOpen: (id) => get().activePlugins.has(id),
}));
