import { useState } from 'react';

export function useBuilderDialogs() {
  const [showChat, setShowChat] = useState(false);
  const [showAddData, setShowAddData] = useState(false);
  const [addDataInitialQuery, setAddDataInitialQuery] = useState('');
  const [showShare, setShowShare] = useState(false);
  const [showInfo, setShowInfo] = useState(false);

  // If AI becomes unavailable while the dock is open on the chat tab, the dock
  // stays open: Attributes and Notes are still useful.

  return {
    showChat, setShowChat,
    showAddData, setShowAddData,
    addDataInitialQuery, setAddDataInitialQuery,
    showShare, setShowShare,
    showInfo, setShowInfo,
  };
}
