import { useState, useEffect, useCallback } from 'react';

const SIDEBAR_COLLAPSED_KEY = 'geolens-builder-sidebar-collapsed';

export function useBuilderDialogs(aiAvailable: boolean | undefined, isMobile = false) {
  const [showChat, setShowChat] = useState(false);
  const [showAddData, setShowAddData] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsedRaw] = useState(
    () => isMobile || localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true',
  );
  const setSidebarCollapsed = useCallback((collapsed: boolean) => {
    setSidebarCollapsedRaw(collapsed);
    // Only persist desktop sidebar state — mobile always defaults to collapsed
    if (!isMobile) {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
    }
  }, [isMobile]);

  // Force collapsed when switching to mobile viewport
  useEffect(() => {
    if (isMobile) setSidebarCollapsedRaw(true);
  }, [isMobile]);

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
