import { create } from 'zustand';

interface PluginState {
  activePlugins: Set<string>;
  toggle: (id: string) => void;
  open: (id: string) => void;
  close: (id: string) => void;
  replace: (ids: Iterable<string>) => void;
}

export const usePluginStore = create<PluginState>()((set) => ({
  activePlugins: new Set<string>(),
  toggle: (id) =>
    set((s) => {
      const next = new Set(s.activePlugins);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return { activePlugins: next };
    }),
  open: (id) =>
    set((s) => {
      const next = new Set(s.activePlugins);
      next.add(id);
      return { activePlugins: next };
    }),
  close: (id) =>
    set((s) => {
      const next = new Set(s.activePlugins);
      next.delete(id);
      return { activePlugins: next };
    }),
  replace: (ids) => set({ activePlugins: new Set(ids) }),
}));
