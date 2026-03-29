import { create } from 'zustand';

interface WidgetState {
  activeWidgets: Set<string>;
  toggle: (id: string) => void;
  open: (id: string) => void;
  close: (id: string) => void;
}

export const useWidgetStore = create<WidgetState>()((set) => ({
  activeWidgets: new Set<string>(),
  toggle: (id) =>
    set((s) => {
      const next = new Set(s.activeWidgets);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return { activeWidgets: next };
    }),
  open: (id) =>
    set((s) => {
      const next = new Set(s.activeWidgets);
      next.add(id);
      return { activeWidgets: next };
    }),
  close: (id) =>
    set((s) => {
      const next = new Set(s.activeWidgets);
      next.delete(id);
      return { activeWidgets: next };
    }),
}));
