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

  // Auto-collapse on mobile, auto-expand when returning to desktop
  // (unless user explicitly collapsed via button — tracked by localStorage)
  useEffect(() => {
    if (isMobile) {
      setSidebarCollapsedRaw(true);
    } else {
      const persisted = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      if (persisted !== 'true') setSidebarCollapsedRaw(false);
    }
  }, [isMobile]);

  // If AI becomes unavailable while the dock is open on the chat tab,
  // the dock stays open — Attributes and Notes tabs are still useful.

  return {
    showChat, setShowChat,
    showAddData, setShowAddData,
    showShare, setShowShare,
    showInfo, setShowInfo,
    sidebarCollapsed, setSidebarCollapsed,
  };
}
