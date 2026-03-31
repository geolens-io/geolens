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
    const mqlCompact = window.matchMedia(`(max-width: ${BUILDER_COMPACT_BREAKPOINT - 1}px)`)
    const mqlMobile = window.matchMedia(`(max-width: ${BUILDER_MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsCompact(window.innerWidth < BUILDER_COMPACT_BREAKPOINT)
      setIsMobile(window.innerWidth < BUILDER_MOBILE_BREAKPOINT)
    }
    mqlCompact.addEventListener("change", onChange)
    mqlMobile.addEventListener("change", onChange)
    onChange()
    return () => {
      mqlCompact.removeEventListener("change", onChange)
      mqlMobile.removeEventListener("change", onChange)
    }
  }, [])

  return { isCompact, isMobile }
}
