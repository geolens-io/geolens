import { create } from 'zustand';

// Shared open-state for the "Report a problem" wizard, triggered by the user
// menu item and the floating button shown once errors are captured.
// ReportProblemHost owns the wizard.
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
