import * as React from "react"

// Locked breakpoints from UI-SPEC §"Responsive breakpoints" (Phase 1034)
// At < BUILDER_RAIL_BREAKPOINT: sidebar collapses to 64px icon rail
// At < BUILDER_EDITOR_HIDDEN_BREAKPOINT: editor column hidden entirely
const BUILDER_RAIL_BREAKPOINT = 1100
const BUILDER_EDITOR_HIDDEN_BREAKPOINT = 800
// fix(#438): UX-06 — below this the top bar cramps (LIVE-03) and the builder is
// not a real editing surface; we show a "desktop recommended" affordance.
const BUILDER_MOBILE_BREAKPOINT = 768

export function useBuilderLayout() {
  const [isRail, setIsRail] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_RAIL_BREAKPOINT
  )
  const [isEditorHidden, setIsEditorHidden] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_EDITOR_HIDDEN_BREAKPOINT
  )
  const [isMobile, setIsMobile] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_MOBILE_BREAKPOINT
  )

  React.useEffect(() => {
    const railMql = window.matchMedia(`(max-width: ${BUILDER_RAIL_BREAKPOINT - 1}px)`)
    const editorHiddenMql = window.matchMedia(`(max-width: ${BUILDER_EDITOR_HIDDEN_BREAKPOINT - 1}px)`)
    const mobileMql = window.matchMedia(`(max-width: ${BUILDER_MOBILE_BREAKPOINT - 1}px)`)
    const onRail = () => setIsRail(railMql.matches)
    const onEditorHidden = () => setIsEditorHidden(editorHiddenMql.matches)
    const onMobile = () => setIsMobile(mobileMql.matches)
    railMql.addEventListener("change", onRail)
    editorHiddenMql.addEventListener("change", onEditorHidden)
    mobileMql.addEventListener("change", onMobile)
    return () => {
      railMql.removeEventListener("change", onRail)
      editorHiddenMql.removeEventListener("change", onEditorHidden)
      mobileMql.removeEventListener("change", onMobile)
    }
  }, [])

  // STATE-08 (builder-audit #338 20260626): the deprecated isCompact/isMobile aliases
  // were removed — the only production consumer (MapBuilderPage) reads
  // isRail/isEditorHidden directly.
  return {
    isRail,
    isEditorHidden,
    isMobile,
  }
}
