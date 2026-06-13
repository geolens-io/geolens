import { useState } from 'react';

// Phase 1199 STACK-06: the `isMobile` parameter is retained as part of the
// documented positional hook contract (MapBuilderPage calls
// useBuilderDialogs(aiAvailable, isEditorHidden)) even though the sidebar-collapse
// state it once drove has been removed as dead code (zero production consumers).
export function useBuilderDialogs(_aiAvailable: boolean | undefined, _isMobile = false) {
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
