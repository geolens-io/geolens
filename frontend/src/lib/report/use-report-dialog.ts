import { create } from 'zustand';

// Shared open-state for the "Report a problem" wizard so multiple entry points
// can trigger it: the user-menu item (always available, discoverable) and the
// floating button that only appears once errors are captured. ReportProblemHost
// owns the wizard and reads `open` from here.
interface ReportDialogState {
  open: boolean;
  setOpen: (open: boolean) => void;
  openReport: () => void;
  closeReport: () => void;
}

export const useReportDialog = create<ReportDialogState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
  openReport: () => set({ open: true }),
  closeReport: () => set({ open: false }),
}));
