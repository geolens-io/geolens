import * as React from "react"

const BUILDER_COMPACT_BREAKPOINT = 1024
const BUILDER_MOBILE_BREAKPOINT = 768

export function useBuilderLayout() {
  const [isCompact, setIsCompact] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_COMPACT_BREAKPOINT
  )
  const [isMobile, setIsMobile] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_MOBILE_BREAKPOINT
  )

  React.useEffect(() => {
    const compactMql = window.matchMedia(`(max-width: ${BUILDER_COMPACT_BREAKPOINT - 1}px)`)
    const mobileMql = window.matchMedia(`(max-width: ${BUILDER_MOBILE_BREAKPOINT - 1}px)`)
    const onCompact = () => setIsCompact(compactMql.matches)
    const onMobile = () => setIsMobile(mobileMql.matches)
    compactMql.addEventListener("change", onCompact)
    mobileMql.addEventListener("change", onMobile)
    onCompact()
    onMobile()
    return () => {
      compactMql.removeEventListener("change", onCompact)
      mobileMql.removeEventListener("change", onMobile)
    }
  }, [])

  return { isCompact, isMobile }
}
