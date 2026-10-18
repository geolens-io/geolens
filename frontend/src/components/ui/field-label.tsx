import * as React from "react"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"

interface FieldLabelProps {
  /** The id of the form control this label is associated with. */
  htmlFor: string
  /** Additional Tailwind classes, e.g. "not-sr-only" for a visible label. */
  className?: string
  children: React.ReactNode
}

/**
 * Visually hidden field label: a radix Label associated to a control via
 * `htmlFor`, `sr-only` by default but still in the accessibility tree so
 * screen readers announce the control's name. The shared primitive for
 * controls needing an accessible name without a visible label; pass
 * `className="not-sr-only"` for a visible one.
 */
export function FieldLabel({ htmlFor, className, children }: FieldLabelProps) {
  return (
    <Label htmlFor={htmlFor} className={cn("sr-only", className)}>
      {children}
    </Label>
  )
}
