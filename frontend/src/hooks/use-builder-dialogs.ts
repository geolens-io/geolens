import { useState, useEffect } from 'react';

export function useBuilderDialogs(aiAvailable: boolean | undefined) {
  const [showChat, setShowChat] = useState(false);
  const [showAddData, setShowAddData] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Close chat panel if AI becomes unavailable
  useEffect(() => {
    if (!aiAvailable && showChat) {
      setShowChat(false);
    }
  }, [aiAvailable, showChat]);

  return {
    showChat, setShowChat,
    showAddData, setShowAddData,
    showShare, setShowShare,
    showInfo, setShowInfo,
    sidebarCollapsed, setSidebarCollapsed,
  };
}
