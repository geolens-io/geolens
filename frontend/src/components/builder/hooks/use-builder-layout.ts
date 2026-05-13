import * as React from "react"

// Locked breakpoints from UI-SPEC §"Responsive breakpoints" (Phase 1034)
// At < BUILDER_RAIL_BREAKPOINT: sidebar collapses to 64px icon rail
// At < BUILDER_EDITOR_HIDDEN_BREAKPOINT: editor column hidden entirely
const BUILDER_RAIL_BREAKPOINT = 1100
const BUILDER_EDITOR_HIDDEN_BREAKPOINT = 800

export function useBuilderLayout() {
  const [viewportWidth, setViewportWidth] = React.useState<number>(
    () => window.innerWidth
  )
  const [isRail, setIsRail] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_RAIL_BREAKPOINT
  )
  const [isEditorHidden, setIsEditorHidden] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_EDITOR_HIDDEN_BREAKPOINT
  )

  React.useEffect(() => {
    const railMql = window.matchMedia(`(max-width: ${BUILDER_RAIL_BREAKPOINT - 1}px)`)
    const editorHiddenMql = window.matchMedia(`(max-width: ${BUILDER_EDITOR_HIDDEN_BREAKPOINT - 1}px)`)
    const onResize = () => {
      setViewportWidth(window.innerWidth)
      setIsRail(railMql.matches)
      setIsEditorHidden(editorHiddenMql.matches)
    }
    const onRail = onResize
    const onEditorHidden = onResize
    railMql.addEventListener("change", onRail)
    editorHiddenMql.addEventListener("change", onEditorHidden)
    window.addEventListener("resize", onResize)
    onResize()
    return () => {
      railMql.removeEventListener("change", onRail)
      editorHiddenMql.removeEventListener("change", onEditorHidden)
      window.removeEventListener("resize", onResize)
    }
  }, [])

  return {
    isRail,
    isEditorHidden,
    viewportWidth,
    // Backward-compat aliases — deprecated; callers should migrate to isRail/isEditorHidden
    isCompact: isRail,
    isMobile: isEditorHidden,
  }
}
