import * as React from "react"

const BUILDER_COMPACT_BREAKPOINT = 1024
const BUILDER_MOBILE_BREAKPOINT = 768

export function useBuilderLayout() {
  const [viewportWidth, setViewportWidth] = React.useState<number>(
    () => window.innerWidth
  )
  const [isCompact, setIsCompact] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_COMPACT_BREAKPOINT
  )
  const [isMobile, setIsMobile] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_MOBILE_BREAKPOINT
  )

  React.useEffect(() => {
    const compactMql = window.matchMedia(`(max-width: ${BUILDER_COMPACT_BREAKPOINT - 1}px)`)
    const mobileMql = window.matchMedia(`(max-width: ${BUILDER_MOBILE_BREAKPOINT - 1}px)`)
    const onResize = () => {
      setViewportWidth(window.innerWidth)
      setIsCompact(compactMql.matches)
      setIsMobile(mobileMql.matches)
    }
    const onCompact = onResize
    const onMobile = onResize
    compactMql.addEventListener("change", onCompact)
    mobileMql.addEventListener("change", onMobile)
    window.addEventListener("resize", onResize)
    onResize()
    return () => {
      compactMql.removeEventListener("change", onCompact)
      mobileMql.removeEventListener("change", onMobile)
      window.removeEventListener("resize", onResize)
    }
  }, [])

  return { isCompact, isMobile, viewportWidth }
}
