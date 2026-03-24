import { useState, useEffect, useCallback } from 'react';

const SIDEBAR_COLLAPSED_KEY = 'geolens-builder-sidebar-collapsed';

export function useBuilderDialogs(aiAvailable: boolean | undefined) {
  const [showChat, setShowChat] = useState(false);
  const [showAddData, setShowAddData] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsedRaw] = useState(
    () => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true',
  );
  const setSidebarCollapsed = useCallback((collapsed: boolean) => {
    setSidebarCollapsedRaw(collapsed);
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
  }, []);

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
