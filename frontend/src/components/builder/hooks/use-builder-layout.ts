import * as React from "react"

// Locked breakpoints
// At < BUILDER_RAIL_BREAKPOINT: sidebar collapses to 64px icon rail
// At < BUILDER_EDITOR_HIDDEN_BREAKPOINT: editor column hidden entirely
const BUILDER_RAIL_BREAKPOINT = 1100
const BUILDER_EDITOR_HIDDEN_BREAKPOINT = 800
// Below this the top bar cramps and the builder is not a real editing surface,
// so a "desktop recommended" affordance is shown.
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

  // isRail/isEditorHidden are read directly by MapBuilderPage.
  return {
    isRail,
    isEditorHidden,
    isMobile,
  }
}
