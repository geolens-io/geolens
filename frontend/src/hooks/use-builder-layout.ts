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
    const mql = window.matchMedia(`(max-width: ${BUILDER_COMPACT_BREAKPOINT - 1}px)`)
    const onChange = () => {
      const w = window.innerWidth
      setIsCompact(w < BUILDER_COMPACT_BREAKPOINT)
      setIsMobile(w < BUILDER_MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    onChange()
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return { isCompact, isMobile }
}
