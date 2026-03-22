import * as React from "react"

const BUILDER_COMPACT_BREAKPOINT = 1024

export function useBuilderLayout() {
  const [isCompact, setIsCompact] = React.useState<boolean>(
    () => window.innerWidth < BUILDER_COMPACT_BREAKPOINT
  )

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${BUILDER_COMPACT_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsCompact(window.innerWidth < BUILDER_COMPACT_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    setIsCompact(window.innerWidth < BUILDER_COMPACT_BREAKPOINT)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return { isCompact }
}
