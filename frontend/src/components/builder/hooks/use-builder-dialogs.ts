import { useState } from 'react';

// STATE-08 (builder-audit #338 20260626): the former `aiAvailable`/`isMobile`
// positional params were ignored — the sidebar-collapse state they once drove
// was removed as dead code (zero production consumers). Dropped to remove the
// phantom API surface.
export function useBuilderDialogs() {
  const [showChat, setShowChat] = useState(false);
  const [showAddData, setShowAddData] = useState(false);
  const [addDataInitialQuery, setAddDataInitialQuery] = useState('');
  const [showShare, setShowShare] = useState(false);
  const [showInfo, setShowInfo] = useState(false);

  // If AI becomes unavailable while the dock is open on the chat tab,
  // the dock stays open — Attributes and Notes tabs are still useful.

  return {
    showChat, setShowChat,
    showAddData, setShowAddData,
    addDataInitialQuery, setAddDataInitialQuery,
    showShare, setShowShare,
    showInfo, setShowInfo,
  };
}
