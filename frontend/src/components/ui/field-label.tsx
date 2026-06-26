import * as React from "react"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"

interface FieldLabelProps {
  /** The id of the form control this label is associated with. */
  htmlFor: string
  /** Additional Tailwind classes. A caller can pass "not-sr-only" or any
   *  visible-text utility to opt into a visible label; sr-only is the default
   *  so the label stays in the accessibility tree without being painted. */
  className?: string
  children: React.ReactNode
}

/**
 * Visually-hidden field label primitive (GLUX-002).
 *
 * Wraps the existing radix Label to produce a `<label>` element that:
 *  - is associated to a control via `htmlFor`
 *  - is hidden from sighted users by default (`sr-only`)
 *  - is still present in the accessibility tree so screen readers announce
 *    the control's accessible name
 *
 * Use this as the single shared primitive for every interactive control that
 * needs an accessible name without a visible label. Callers that want a
 * visible label can override with `className="not-sr-only"` or remove
 * sr-only by passing a Tailwind class that contradicts it.
 */
export function FieldLabel({ htmlFor, className, children }: FieldLabelProps) {
  return (
    <Label htmlFor={htmlFor} className={cn("sr-only", className)}>
      {children}
    </Label>
  )
}
