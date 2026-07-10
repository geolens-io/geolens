import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * fix(#438): DS-03 — a shared textarea primitive. Eight-plus components had
 * hand-rolled `<textarea>` styles whose focus ring, radius, and padding all
 * drifted from each other and from `<Input>`. This mirrors input.tsx's
 * treatment so a textarea and an input read as the same control family.
 */
const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<"textarea">
>(({ className, ...props }, ref) => {
  return (
    <textarea
      ref={ref}
      data-slot="textarea"
      className={cn(
        "placeholder:text-muted-foreground dark:bg-input/30 border-input flex min-h-16 w-full rounded-md border bg-transparent px-3 py-2 text-base shadow-xs transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
        className
      )}
      {...props}
    />
  )
})

Textarea.displayName = "Textarea"

export { Textarea }
